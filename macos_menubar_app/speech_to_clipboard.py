#!/usr/bin/env python3
"""
macOS 狀態列語音轉文字應用
Speech-to-Text macOS Menubar App
"""

import json
import re
import urllib.request
import urllib.error
import rumps
import sounddevice as sd
import numpy as np
import subprocess
import threading
import queue
import os
import time
from openai import OpenAI
import pyperclip
from scipy.io import wavfile
import tempfile
import logging
from opencc import OpenCC
from batch_transcribe import batch_transcribe_directory, TranscriptionResult, _find_ffmpeg

# Gemini SDK — optional, lazy import for fallback transcription
_GEMINI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types as genai_types
    _GEMINI_AVAILABLE = True
except ImportError:
    pass

# 將不常用的繁體字改成常用的（來自 clip2trad-python）
MANUAL_MAPPINGS = {
    '瞭解': '了解',
    '羣': '群',
    '臺': '台',
    '峯': '峰',
    '喫': '吃',
    '纔': '才',
    '爲': '為'
}

# 超過此秒數的錄音自動使用 long transcription endpoint（AssemblyAI）
LONG_AUDIO_DURATION_THRESHOLD = 300  # 5 分鐘

# 成功轉錄後的錄音存檔目錄，改為按天數保留而非轉錄完立即刪除
RECORDINGS_DIR = os.path.expanduser("~/Documents/SpeechToText/recordings")
RECORDINGS_RETENTION_DAYS = 7

REFINE_SYSTEM_PROMPT = (
    "你是一個文字潤飾助手。你的唯一任務是潤飾用戶提供的文字。\n"
    "規則：\n"
    "1. 只輸出潤飾後的文字，不要有任何其他內容\n"
    "2. 不要加開頭語、解釋、分析、編號、標題\n"
    "3. 不要說「潤飾後的內容：」之類的前綴\n"
    "4. 不要搜尋網路、不要引用資料\n"
    "5. 直接回覆潤飾結果，一個字的前綴都不要有"
)

REFINE_USER_PROMPT = (
    "潤飾以下內容。保留原話語言（中文／英文／中英夾雜），嚴守 3 條件：\n"
    "- 最小幅度修改：保留原本詞彙和句型，不要大幅重寫\n"
    "- 維持口語：保留真誠自然的聊天風格和語氣詞\n"
    "- 優化閱讀：拆斷過長句子、補標點、順邏輯\n\n"
)


def apply_manual_mappings(text, mappings):
    """
    根據手動映射字典替換文本中的指定詞彙。

    :param text: 要處理的文本
    :param mappings: 替換映射字典
    :return: 替換後的文本
    """
    for key, value in mappings.items():
        text = text.replace(key, value)
    return text


def get_ai_builder_api_key():
    """
    取得 AI_BUILDER_API_KEY：先檢查環境變數，若無則從 ~/.zshrc 解析。
    若 ~/.zshrc 中有 export AI_BUILDER_API_KEY=... 或 AI_BUILDER_API_KEY=...，則回傳其值。
    """
    key = os.environ.get("AI_BUILDER_API_KEY")
    if key and key.strip():
        return key.strip()

    zshrc = os.path.expanduser("~/.zshrc")
    if not os.path.isfile(zshrc):
        return None

    # 匹配 export AI_BUILDER_API_KEY=value 或 AI_BUILDER_API_KEY=value
    pattern = re.compile(
        r"^\s*(?:export\s+)?AI_BUILDER_API_KEY\s*=\s*(?:(['\"])(.*?)\1|(\S+))\s*(?:#.*)?$",
        re.MULTILINE,
    )
    try:
        with open(zshrc, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        m = pattern.search(content)
        if m:
            value = m.group(2) if m.group(2) is not None else (m.group(3) or "")
            return value.strip() if value else None
    except OSError:
        pass
    return None


def get_gemini_api_key():
    """
    取得 Gemini API key：依序檢查 GEMINI_API_KEY → GOOGLE_API_KEY（環境變數或 ~/.zshrc）。
    """
    for var_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        key = os.environ.get(var_name)
        if key and key.strip():
            return key.strip()

    zshrc = os.path.expanduser("~/.zshrc")
    if not os.path.isfile(zshrc):
        return None

    try:
        with open(zshrc, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None

    for var_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        pattern = re.compile(
            rf"^\s*(?:export\s+)?{var_name}\s*=\s*(?:(['\"])(.*?)\1|(\S+))\s*(?:#.*)?$",
            re.MULTILINE,
        )
        m = pattern.search(content)
        if m:
            value = m.group(2) if m.group(2) is not None else (m.group(3) or "")
            if value.strip():
                return value.strip()
    return None


# 20 MB inline upload limit for Gemini
_GEMINI_INLINE_LIMIT = 20 * 1024 * 1024

# macOS Accessibility 和按鍵模擬
from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateSystemWide,
    AXUIElementCopyAttributeValue,
    kAXFocusedApplicationAttribute,
    kAXFocusedUIElementAttribute,
    kAXRoleAttribute,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGHIDEventTap,
    CGEventSetFlags,
    kCGEventFlagMaskCommand
)
from CoreFoundation import CFPreferencesCopyAppValue

# 全局快捷鍵
from pynput import keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SpeechToClipboardApp(rumps.App):
    """macOS 狀態列語音轉文字應用"""

    def __init__(self):
        super(SpeechToClipboardApp, self).__init__(
            "🎤",  # 狀態列圖示
            title="STT",
            quit_button=None  # 自定義退出按鈕
        )

        # 偵測所有可用的轉錄 provider，建立 fallback chain
        ai_builder_key = get_ai_builder_api_key()
        gemini_key = get_gemini_api_key() if _GEMINI_AVAILABLE else None
        openai_key = os.getenv("OPENAI_API_KEY")

        self.use_ai_builder = bool(ai_builder_key)
        self.ai_builder_api_key = ai_builder_key
        self.ai_builder_base = "https://space.ai-builders.com/backend" if ai_builder_key else None
        self.gemini_api_key = gemini_key
        self.gemini_client = None  # lazy init
        self.client = OpenAI(api_key=openai_key) if openai_key else None

        # 至少需要一個 provider
        if not any([ai_builder_key, gemini_key, openai_key]):
            rumps.alert("錯誤", "請設置至少一個轉錄 API Key\n(AI_BUILDER_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY)")
            raise ValueError("No transcription API key found")

        # Log fallback chain
        chain_names = []
        if ai_builder_key:
            chain_names.append("AI Builder")
        if gemini_key:
            chain_names.append("Gemini")
        if openai_key:
            chain_names.append("OpenAI")
        logger.info("Transcription chain: %s", " → ".join(chain_names))

        # 初始化簡繁轉換器（簡體轉繁體）
        self.cc = OpenCC('s2t')

        # 錄音參數
        self.sample_rate = 16000  # Whisper 推薦 16kHz
        self.channels = 1
        self.recording = False
        self.processing = False  # 新增：標記是否正在處理音頻
        self.audio_queue = queue.Queue()
        self.audio_data = []
        self.audio_lock = threading.Lock()  # 新增：保護 audio_data
        self.recording_thread = None
        self.recording_mode = "transcribe"  # "transcribe" or "refine"

        # Checkpoint 錄音模式 state
        self.checkpoint_mode = False
        self.checkpoint_session_id = None
        self.checkpoint_save_dir = None
        self.checkpoint_last_chunk_idx = 0
        self.checkpoint_seg_count = 0
        self.checkpoint_md_path = None
        self.checkpoint_md_lock = threading.Lock()

        # OpenAI 單檔轉錄 session 的 markdown log（lazy 建立、整個 app session 共用）
        self.openai_session_md_path = None
        self.openai_session_md_lock = threading.Lock()

        # 設置菜單
        self.menu = [
            rumps.MenuItem("開始錄音 (⌃⌥R)", callback=self.toggle_recording, key="a"),
            rumps.MenuItem("停止並送出 (⌃⌥E)", callback=self.toggle_transcribe_and_send_recording),
            rumps.MenuItem("潤飾語音 (⌃⌥S)", callback=self.toggle_refine_recording),
            rumps.MenuItem("Checkpoint 錄音 (⌃⌥Q)", callback=self.toggle_checkpoint_recording_menu),
            rumps.MenuItem("標記 Checkpoint (⌃⌥W)", callback=self.mark_checkpoint_menu),
            rumps.separator,
            rumps.MenuItem("錄音中...", callback=None),
            rumps.separator,
            rumps.MenuItem("最近結果"),
            rumps.separator,
            rumps.MenuItem("批次轉錄...", callback=self.batch_transcribe),
            rumps.MenuItem("轉錄音檔 (OpenAI)...", callback=self.transcribe_audio_file),
            rumps.MenuItem("WebM 轉 MP3...", callback=self.convert_webm_to_mp3),
            rumps.separator,
            rumps.MenuItem("設定"),
            rumps.MenuItem("關於"),
            rumps.separator,
            rumps.MenuItem("退出", callback=self.quit_app)
        ]

        # 隱藏錄音狀態項
        self.menu["錄音中..."].set_callback(None)
        self.menu["錄音中..."].state = False

        # 初始化最近結果子菜單
        self.recent_results = []
        self.update_recent_results_menu()

        # 自動粘貼設置（默認開啟）
        self.auto_paste_enabled = True

        # 全局快捷鍵設置
        self.global_hotkey_enabled = True
        self.hotkey_listener = None

        # 強制即時轉錄一律走 OpenAI（繞過成本排序 fallback chain）
        self.force_openai = False

        # 啟動時清除超過保留期的舊錄音（取代轉錄成功即刪的舊行為）
        self._cleanup_old_recordings()

        # 初始化設定子菜單
        self.setup_settings_menu()

        # 檢查輔助功能權限
        self.check_accessibility_permission()

        # 啟動全局快捷鍵監聽
        self.start_global_hotkey_listener()

        # Chat client（用於潤飾功能）
        openai_key = os.getenv("OPENAI_API_KEY")
        if self.client:
            # use_ai_builder=False → 已有 OpenAI client
            self.chat_client = self.client
            self.refine_model = "gpt-4o-mini"
        elif openai_key:
            # AI Builder 轉錄，但有 OpenAI key 可用於 chat
            self.chat_client = OpenAI(api_key=openai_key)
            self.refine_model = "gpt-4o-mini"
        elif self.use_ai_builder:
            # 用 AI Builder chat completions endpoint
            self.chat_client = OpenAI(
                api_key=self.ai_builder_api_key,
                base_url=self.ai_builder_base + "/v1"
            )
            self.refine_model = "gemini-3-flash-preview"
        else:
            self.chat_client = None
            self.refine_model = None

    def check_accessibility_permission(self):
        """檢查輔助功能權限"""
        options = {kAXTrustedCheckOptionPrompt: True}
        trusted = AXIsProcessTrustedWithOptions(options)
        if not trusted:
            logger.warning("Accessibility permission required for auto-paste")
        return trusted

    def setup_settings_menu(self):
        """設置設定子菜單"""
        if self.use_ai_builder and self.gemini_api_key:
            model_label = "轉錄: AI Builder (+Gemini fallback)"
        elif self.use_ai_builder:
            model_label = "轉錄: AI Builder"
        else:
            model_label = "轉錄: gpt-4o-mini-transcribe"
        settings_menu = [
            rumps.MenuItem("語言: 自動偵測", callback=self.change_language),
            rumps.MenuItem("✓ 自動粘貼到焦點應用", callback=self.toggle_auto_paste),
            rumps.MenuItem("✓ 全局快捷鍵 (⌃⌥R/⌃⌥E/⌃⌥S/⌃⌥Q/⌃⌥W)", callback=self.toggle_global_hotkey),
        ]
        # 只有在有 OpenAI key 時，強制走 OpenAI 才有意義
        if self.client:
            force_title = "✓ 即時轉錄一律走 OpenAI" if self.force_openai else "即時轉錄一律走 OpenAI"
            settings_menu.append(rumps.MenuItem(force_title, callback=self.toggle_force_openai))
        settings_menu.append(rumps.MenuItem(model_label, callback=None))
        self.menu["設定"] = settings_menu

    def toggle_auto_paste(self, sender):
        """切換自動粘貼功能"""
        self.auto_paste_enabled = not self.auto_paste_enabled
        if self.auto_paste_enabled:
            sender.title = "✓ 自動粘貼到焦點應用"
            # 檢查權限
            if not self.check_accessibility_permission():
                rumps.alert(
                    "需要輔助功能權限",
                    "請在「系統偏好設置」→「安全性與隱私」→「輔助功能」中\n"
                    "授予此應用權限以使用自動粘貼功能"
                )
        else:
            sender.title = "自動粘貼到焦點應用"
        logger.info(f"Auto-paste: {'Enabled' if self.auto_paste_enabled else 'Disabled'}")

    def toggle_global_hotkey(self, sender):
        """切換全局快捷鍵功能"""
        self.global_hotkey_enabled = not self.global_hotkey_enabled
        if self.global_hotkey_enabled:
            sender.title = "✓ 全局快捷鍵 (⌃⌥R/⌃⌥E/⌃⌥S/⌃⌥Q/⌃⌥W)"
            self.start_global_hotkey_listener()
            logger.info("Global hotkey enabled")
        else:
            sender.title = "全局快捷鍵 (⌃⌥R/⌃⌥E/⌃⌥S/⌃⌥Q/⌃⌥W)"
            self.stop_global_hotkey_listener()
            logger.info("Global hotkey disabled")

    def toggle_force_openai(self, sender):
        """切換即時轉錄是否一律走 OpenAI（繞過 fallback chain）"""
        self.force_openai = not self.force_openai
        sender.title = "✓ 即時轉錄一律走 OpenAI" if self.force_openai else "即時轉錄一律走 OpenAI"
        logger.info("Force OpenAI: %s", "Enabled" if self.force_openai else "Disabled")

    def start_global_hotkey_listener(self):
        """啟動全局快捷鍵監聽"""
        if not self.global_hotkey_enabled:
            return

        # 停止舊的監聽器
        self.stop_global_hotkey_listener()

        try:
            # 定義快捷鍵組合
            hotkey_transcribe = keyboard.HotKey(
                keyboard.HotKey.parse('<ctrl>+<alt>+r'),
                self.on_hotkey_pressed
            )
            hotkey_transcribe_send = keyboard.HotKey(
                keyboard.HotKey.parse('<ctrl>+<alt>+e'),
                self.on_transcribe_and_send_hotkey_pressed
            )
            hotkey_refine = keyboard.HotKey(
                keyboard.HotKey.parse('<ctrl>+<alt>+s'),
                self.on_refine_hotkey_pressed
            )
            hotkey_checkpoint_toggle = keyboard.HotKey(
                keyboard.HotKey.parse('<ctrl>+<alt>+q'),
                self.on_checkpoint_toggle_hotkey
            )
            hotkey_checkpoint_mark = keyboard.HotKey(
                keyboard.HotKey.parse('<ctrl>+<alt>+w'),
                self.on_checkpoint_mark_hotkey
            )

            # 創建監聽器（支援多組快捷鍵）
            self.hotkey_listener = keyboard.Listener(
                on_press=lambda key: (
                    hotkey_transcribe.press(self.hotkey_listener.canonical(key)),
                    hotkey_transcribe_send.press(self.hotkey_listener.canonical(key)),
                    hotkey_refine.press(self.hotkey_listener.canonical(key)),
                    hotkey_checkpoint_toggle.press(self.hotkey_listener.canonical(key)),
                    hotkey_checkpoint_mark.press(self.hotkey_listener.canonical(key)),
                ),
                on_release=lambda key: (
                    hotkey_transcribe.release(self.hotkey_listener.canonical(key)),
                    hotkey_transcribe_send.release(self.hotkey_listener.canonical(key)),
                    hotkey_refine.release(self.hotkey_listener.canonical(key)),
                    hotkey_checkpoint_toggle.release(self.hotkey_listener.canonical(key)),
                    hotkey_checkpoint_mark.release(self.hotkey_listener.canonical(key)),
                )
            )

            # 啟動監聽器（在後台線程運行）
            self.hotkey_listener.start()
            logger.info("Global hotkey listener started (⌃⌥R: start/stop transcribe, ⌃⌥E: stop+send, ⌃⌥S: refine, ⌃⌥Q: checkpoint, ⌃⌥W: mark)")

        except Exception as e:
            logger.error(f"Failed to start global hotkey listener: {e}")
            rumps.notification(
                "快捷鍵錯誤",
                "無法啟動全局快捷鍵",
                "請檢查輔助功能權限"
            )

    def stop_global_hotkey_listener(self):
        """停止全局快捷鍵監聽"""
        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
                self.hotkey_listener = None
                logger.info("Global hotkey listener stopped")
            except Exception as e:
                logger.error(f"Failed to stop global hotkey listener: {e}")

    def on_hotkey_pressed(self):
        """全局快捷鍵被按下的回調（⌃⌥R 語音轉文字）"""
        logger.info("Global hotkey pressed (Control+Option+R)")
        if self.checkpoint_mode:
            logger.warning("⌃⌥R ignored: checkpoint mode is active (use ⌃⌥Q to stop first)")
            rumps.notification("Checkpoint 模式進行中", "請先按 ⌃⌥Q 結束 checkpoint 錄音", "")
            return
        if not self.recording:
            self.recording_mode = "transcribe"
        self.toggle_recording(None)

    def on_refine_hotkey_pressed(self):
        """潤飾快捷鍵被按下的回調（⌃⌥S 語音潤飾）"""
        logger.info("Refine hotkey pressed (Control+Option+S)")
        if self.checkpoint_mode:
            logger.warning("⌃⌥S ignored: checkpoint mode is active (use ⌃⌥Q to stop first)")
            rumps.notification("Checkpoint 模式進行中", "請先按 ⌃⌥Q 結束 checkpoint 錄音", "")
            return
        if not self.recording:
            self.recording_mode = "refine"
        self.toggle_recording(None)

    def on_transcribe_and_send_hotkey_pressed(self):
        """⌃⌥E：stop-with-send terminator。

        新邏輯：錄音永遠用 ⌃⌥R 起頭，⌃⌥E 只在錄音進行中作用，按下即停止並把 mode 切成
        transcribe_and_send，讓 _process_audio 在 paste 後自動 fire Enter 送出。
        當沒有錄音時按 ⌃⌥E 不會啟動錄音（避免改變「start 永遠是 ⌃⌥R」的約定）。
        """
        logger.info("Transcribe-and-send hotkey pressed (Control+Option+E)")
        if self.checkpoint_mode:
            logger.warning("⌃⌥E ignored: checkpoint mode is active (use ⌃⌥Q to stop first)")
            rumps.notification("Checkpoint 模式進行中", "請先按 ⌃⌥Q 結束 checkpoint 錄音", "")
            return
        if not self.recording:
            logger.info("⌃⌥E ignored: no active recording — use ⌃⌥R to start recording first")
            rumps.notification("尚未錄音", "請先用 ⌃⌥R 開始錄音", "⌃⌥E 只用於結束錄音並送出")
            return
        if self.processing:
            return
        # 切換到送出模式後停止
        self.recording_mode = "transcribe_and_send"
        self.toggle_recording(None)

    def toggle_refine_recording(self, sender):
        """從菜單觸發潤飾錄音"""
        if not self.recording:
            self.recording_mode = "refine"
        self.toggle_recording(sender)

    def toggle_transcribe_and_send_recording(self, sender):
        """從菜單觸發 停止並送出。同 on_transcribe_and_send_hotkey_pressed：
        只有在錄音中才作用，並切換 mode 後停止；未錄音時不啟動。"""
        self.on_transcribe_and_send_hotkey_pressed()

    # ------------------------------------------------------------------
    # Checkpoint recording mode (⌃⌥Q start/stop, ⌃⌥W mark checkpoint)
    # ------------------------------------------------------------------

    def on_checkpoint_toggle_hotkey(self):
        """⌃⌥Q 開始/結束 checkpoint 錄音模式"""
        logger.info("Checkpoint toggle hotkey pressed (Control+Option+Q)")
        if self.checkpoint_mode:
            self.stop_checkpoint_recording()
        else:
            self.start_checkpoint_recording()

    def on_checkpoint_mark_hotkey(self):
        """⌃⌥W 在 checkpoint 錄音中標記一個 checkpoint，把上次到現在這段轉文字"""
        logger.info("Checkpoint mark hotkey pressed (Control+Option+W)")
        if not self.checkpoint_mode:
            logger.warning("⌃⌥W pressed but not in checkpoint mode — ignored")
            rumps.notification("Checkpoint 模式未開啟", "請先按 ⌃⌥Q 開始 checkpoint 錄音", "")
            return
        self.mark_checkpoint()

    def toggle_checkpoint_recording_menu(self, _):
        """菜單觸發 checkpoint 切換"""
        self.on_checkpoint_toggle_hotkey()

    def mark_checkpoint_menu(self, _):
        """菜單觸發 checkpoint 標記"""
        self.on_checkpoint_mark_hotkey()

    def start_checkpoint_recording(self):
        """開始 checkpoint 錄音模式"""
        if self.recording or self.processing:
            logger.warning("Cannot start checkpoint mode: another recording/processing is active")
            rumps.notification("無法開始", "目前有其他錄音或處理中", "請先結束")
            return

        # 為這次 session 建立持久儲存目錄
        session_id = time.strftime("%Y%m%d_%H%M%S")
        save_dir = os.path.expanduser("~/Documents/SpeechToText/checkpoint_recordings")
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create checkpoint save dir: {e}")
            rumps.notification("錯誤", "無法建立 checkpoint 目錄", str(e))
            return

        self.checkpoint_mode = True
        self.checkpoint_session_id = session_id
        self.checkpoint_save_dir = save_dir
        self.checkpoint_last_chunk_idx = 0
        self.checkpoint_seg_count = 0
        self.recording_mode = "checkpoint"

        # 建立 Markdown log 並用系統預設 app 開啟
        md_filename = f"checkpoint_{session_id}.md"
        md_path = os.path.join(save_dir, md_filename)
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# Checkpoint Session {session_id}\n\n")
                f.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            self.checkpoint_md_path = md_path
            logger.info(f"[Checkpoint MD created] path={md_path}")
            try:
                subprocess.Popen(["open", md_path])
            except Exception as e:
                logger.warning(f"Failed to `open` markdown file: {e}")
        except OSError as e:
            logger.error(f"Failed to create checkpoint MD file: {e}")
            self.checkpoint_md_path = None

        logger.info(f"Checkpoint recording session started: id={session_id}, save_dir={save_dir}")

        # 重用既有錄音 infra
        self.recording = True
        with self.audio_lock:
            self.audio_data = []
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        self.title = "⏺"
        self.menu["Checkpoint 錄音 (⌃⌥Q)"].title = "停止 Checkpoint 錄音 (⌃⌥Q)"
        self.menu["錄音中..."].state = True

        self.recording_thread = threading.Thread(target=self._record_audio, daemon=True)
        self.recording_thread.start()

        rumps.notification(
            "Checkpoint 錄音開始",
            f"Session: {session_id}",
            f"按 ⌃⌥W 標記 checkpoint，再按 ⌃⌥Q 結束"
        )

    def mark_checkpoint(self):
        """在錄音持續中切出上次 checkpoint 到目前為止的音檔做轉錄"""
        with self.audio_lock:
            current_len = len(self.audio_data)
            segment_chunks = self.audio_data[self.checkpoint_last_chunk_idx:current_len]
            self.checkpoint_last_chunk_idx = current_len

        if not segment_chunks:
            logger.warning("Checkpoint marked but no new audio since last checkpoint — skipped")
            rumps.notification("Checkpoint 跳過", "上次 checkpoint 後沒有新音檔", "")
            return

        self.checkpoint_seg_count += 1
        seg_idx = self.checkpoint_seg_count
        mark_time = time.strftime("%H:%M:%S")
        logger.info(f"Checkpoint #{seg_idx} marked at {mark_time}: {len(segment_chunks)} new audio chunks")

        # 在背景轉錄這段 segment
        threading.Thread(
            target=self._process_checkpoint_segment,
            args=(segment_chunks, seg_idx, False, self.checkpoint_session_id, self.checkpoint_save_dir, None, self.checkpoint_md_path, mark_time),
            daemon=True,
        ).start()

    def stop_checkpoint_recording(self):
        """結束 checkpoint 錄音模式：處理最後一段並存完整錄音檔"""
        if not self.checkpoint_mode:
            return

        logger.info("Stopping checkpoint recording session...")
        self.recording = False
        self.title = "🔄"
        self.menu["Checkpoint 錄音 (⌃⌥Q)"].title = "處理中..."
        self.menu["錄音中..."].state = False

        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=2.0)
            if self.recording_thread.is_alive():
                logger.warning("Recording thread did not finish in time")

        time.sleep(0.1)

        # 抓最後一段未處理的音檔
        with self.audio_lock:
            current_len = len(self.audio_data)
            final_chunks = self.audio_data[self.checkpoint_last_chunk_idx:current_len]
            self.checkpoint_last_chunk_idx = current_len
            all_chunks = list(self.audio_data)

        # 存完整錄音檔
        full_path = self._save_checkpoint_full_recording(all_chunks)

        # 處理最後一段（如果有）
        if final_chunks:
            self.checkpoint_seg_count += 1
            seg_idx = self.checkpoint_seg_count
            mark_time = time.strftime("%H:%M:%S")
            logger.info(f"Final checkpoint #{seg_idx} at {mark_time}: {len(final_chunks)} chunks")
            threading.Thread(
                target=self._process_checkpoint_segment,
                args=(final_chunks, seg_idx, True, self.checkpoint_session_id, self.checkpoint_save_dir, full_path, self.checkpoint_md_path, mark_time),
                daemon=True,
            ).start()
        else:
            logger.info("No remaining audio after last checkpoint — no final segment to transcribe")
            self._finalize_checkpoint_session(full_path)

    def _save_checkpoint_full_recording(self, all_chunks):
        """把整段 checkpoint session 的錄音存成一個完整 WAV，回傳路徑"""
        if not all_chunks:
            logger.warning("Checkpoint session ended with no audio — nothing to save")
            return None
        try:
            audio_array = np.concatenate(all_chunks, axis=0)
            duration = len(audio_array) / self.sample_rate
            filename = f"checkpoint_{self.checkpoint_session_id}_full.wav"
            full_path = os.path.join(self.checkpoint_save_dir, filename)
            wavfile.write(full_path, self.sample_rate, audio_array)
            logger.info(
                f"[Checkpoint FULL recording saved] path={full_path} "
                f"duration={duration:.2f}s chunks={len(all_chunks)}"
            )
            return full_path
        except Exception as e:
            logger.error(f"Failed to save full checkpoint recording: {e}", exc_info=True)
            return None

    def _finalize_checkpoint_session(self, full_path):
        """checkpoint session 結束時 reset UI"""
        self.title = "🎤"
        self.menu["Checkpoint 錄音 (⌃⌥Q)"].title = "Checkpoint 錄音 (⌃⌥Q)"
        md_path = self.checkpoint_md_path
        if md_path:
            logger.info(f"[Checkpoint session ended] md={md_path}")
        notify_msg = full_path if full_path else "(無音檔)"
        rumps.notification(
            "Checkpoint 錄音結束",
            f"Session: {self.checkpoint_session_id}",
            f"完整錄音: {notify_msg}"
        )
        self.checkpoint_mode = False
        self.checkpoint_session_id = None
        self.checkpoint_save_dir = None
        self.checkpoint_last_chunk_idx = 0
        self.checkpoint_seg_count = 0
        self.checkpoint_md_path = None

    def _process_checkpoint_segment(self, segment_chunks, seg_idx, is_final, session_id, save_dir, full_path_for_finalize=None, md_path=None, mark_time=None):
        """轉錄一個 checkpoint segment：存 WAV、log 路徑、轉文字、複製剪貼簿、自動貼上、append MD

        Args:
            segment_chunks: 這段 segment 的 audio chunks list
            seg_idx: 第幾個 segment（1-based）
            is_final: 是否為最後一段（⌃⌥Q 觸發），決定要不要 finalize session
            session_id: 此 session 的 timestamp id（call site 傳入，避免 race）
            save_dir: 此 session 的存檔目錄
            full_path_for_finalize: is_final 時用來通知顯示完整錄音路徑
            md_path: checkpoint session Markdown log 檔案路徑（append 每段轉錄）
            mark_time: checkpoint 被標記時的 wall-clock 時間（HH:MM:SS）。比轉錄完成時間早，能反映實際說話時間。
        """
        seg_path = None
        try:
            audio_array = np.concatenate(segment_chunks, axis=0)
            duration = len(audio_array) / self.sample_rate

            filename = f"checkpoint_{session_id}_seg{seg_idx:03d}.wav"
            seg_path = os.path.join(save_dir, filename)
            wavfile.write(seg_path, self.sample_rate, audio_array)
            logger.info(
                f"[Checkpoint SEGMENT saved] seg={seg_idx} path={seg_path} "
                f"duration={duration:.2f}s"
            )

            use_long = self.use_ai_builder and duration > LONG_AUDIO_DURATION_THRESHOLD
            text, provider_name = self._transcribe_with_fallback(seg_path, use_long=use_long)
            logger.info(f"[Checkpoint seg{seg_idx}] transcription (via {provider_name}): {text}")

            text = self.cc.convert(text)
            text = apply_manual_mappings(text, MANUAL_MAPPINGS)
            logger.info(f"[Checkpoint seg{seg_idx}] traditional: {text}")

            self.recent_results.append(text)
            self.update_recent_results_menu()

            # Append 到 session 的 Markdown log
            if md_path:
                self._append_to_checkpoint_md(md_path, text, mark_time)

            preview = text[:100] + "..." if len(text) > 100 else text
            rumps.notification(
                f"Checkpoint #{seg_idx} ({provider_name})",
                f"已寫入 MD | {os.path.basename(seg_path)}",
                preview,
            )

        except Exception as e:
            logger.error(f"Checkpoint segment processing error: {e}", exc_info=True)
            rumps.notification(
                f"Checkpoint #{seg_idx} 轉錄失敗",
                str(e)[:100],
                seg_path or "",
            )
        finally:
            if is_final:
                self._finalize_checkpoint_session(full_path_for_finalize)

    def _append_to_checkpoint_md(self, md_path, text, mark_time):
        """把 checkpoint 轉錄結果 append 到 session MD 檔案最底下，格式 [HH:MM:SS] <text>。

        Why: mark_time 由 mark_checkpoint/stop_checkpoint_recording 在按鍵當下捕捉，反映
        真正說話的時間；若改在這裡 strftime，會晚到轉錄結束才被記下來，長音檔差距可達分鐘級。
        """
        timestamp = mark_time or time.strftime("%H:%M:%S")
        block = f"[{timestamp}] {text}\n\n"
        try:
            with self.checkpoint_md_lock:
                with open(md_path, "a", encoding="utf-8") as f:
                    f.write(block)
            logger.info(f"[Checkpoint MD appended] time={timestamp} path={md_path}")
        except OSError as e:
            logger.error(f"Failed to append to checkpoint MD: {e}")

    def change_language(self, sender):
        """更改語言設定"""
        response = rumps.Window(
            "設定語言",
            "輸入語言代碼 (例如: zh, en, ja) 或留空自動偵測:",
            default_text="",
            ok="確定",
            cancel="取消"
        ).run()

        if response.clicked:
            lang = response.text.strip()
            if lang:
                sender.title = f"語言: {lang}"
                self.language = lang
            else:
                sender.title = "語言: 自動偵測"
                self.language = None

    def get_focused_app_info(self):
        """獲取當前焦點應用信息"""
        try:
            # 使用 NSWorkspace 獲取前台應用
            frontmost_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if frontmost_app:
                app_name = frontmost_app.localizedName()
                bundle_id = frontmost_app.bundleIdentifier()
                return {
                    'name': app_name,
                    'bundle_id': bundle_id
                }
        except Exception as e:
            logger.error(f"Failed to get focused app: {e}")
        return None

    def simulate_command_v(self):
        """模擬按下 Command+V"""
        try:
            # V 鍵的虛擬鍵碼
            v_keycode = 0x09

            # 創建 Command 按下事件
            cmd_down = CGEventCreateKeyboardEvent(None, 0x37, True)  # 0x37 是 Command 鍵
            CGEventSetFlags(cmd_down, kCGEventFlagMaskCommand)

            # 創建 V 按下事件
            v_down = CGEventCreateKeyboardEvent(None, v_keycode, True)
            CGEventSetFlags(v_down, kCGEventFlagMaskCommand)

            # 創建 V 釋放事件
            v_up = CGEventCreateKeyboardEvent(None, v_keycode, False)
            CGEventSetFlags(v_up, kCGEventFlagMaskCommand)

            # 創建 Command 釋放事件
            cmd_up = CGEventCreateKeyboardEvent(None, 0x37, False)

            # 發送事件序列
            CGEventPost(kCGHIDEventTap, cmd_down)
            time.sleep(0.01)
            CGEventPost(kCGHIDEventTap, v_down)
            time.sleep(0.01)
            CGEventPost(kCGHIDEventTap, v_up)
            time.sleep(0.01)
            CGEventPost(kCGHIDEventTap, cmd_up)

            logger.info("Simulated Command+V")
            return True
        except Exception as e:
            logger.error(f"Failed to simulate key press: {e}")
            return False

    def simulate_return_key(self):
        """模擬按下 Return（Enter）鍵，用於 transcribe_and_send 模式自動送出"""
        try:
            return_keycode = 0x24  # macOS virtual keycode for Return
            down = CGEventCreateKeyboardEvent(None, return_keycode, True)
            up = CGEventCreateKeyboardEvent(None, return_keycode, False)
            CGEventPost(kCGHIDEventTap, down)
            time.sleep(0.01)
            CGEventPost(kCGHIDEventTap, up)
            logger.info("Simulated Return key")
            return True
        except Exception as e:
            logger.error(f"Failed to simulate Return key: {e}")
            return False

    def auto_paste_to_focused_app(self, text):
        """自動粘貼文字到焦點應用"""
        if not self.auto_paste_enabled:
            logger.info("Auto-paste disabled")
            return False

        # 檢查權限
        if not AXIsProcessTrustedWithOptions(None):
            logger.warning("No accessibility permission, cannot auto-paste")
            return False

        try:
            # 獲取當前焦點應用
            app_info = self.get_focused_app_info()
            if app_info:
                app_name = app_info['name']
                logger.info(f"Target app: {app_name}")

                # 先確保文字在剪貼板中
                pyperclip.copy(text)
                time.sleep(0.1)  # 等待剪貼板更新

                # 模擬 Command+V
                if self.simulate_command_v():
                    logger.info(f"Auto-pasted to {app_name}")
                    return True
            else:
                logger.warning("Cannot get focused app")
                return False

        except Exception as e:
            logger.error(f"Auto-paste failed: {e}")
            return False

    def update_recent_results_menu(self):
        """更新最近結果菜單"""
        if not self.recent_results:
            self.menu["最近結果"] = [
                rumps.MenuItem("(無記錄)", callback=None)
            ]
        else:
            recent_menu = []
            for i, text in enumerate(self.recent_results[-5:]):  # 最多顯示 5 條
                # 截取前 50 個字符
                display_text = text[:50] + "..." if len(text) > 50 else text
                menu_item = rumps.MenuItem(
                    display_text,
                    callback=lambda sender, t=text: self.copy_to_clipboard(t)
                )
                recent_menu.append(menu_item)
            self.menu["最近結果"] = recent_menu

    def toggle_recording(self, sender):
        """切換錄音狀態"""
        # 如果正在處理音頻，忽略請求
        if self.processing:
            logger.warning("Still processing previous recording, please wait...")
            rumps.notification(
                "請稍候",
                "正在處理上一段錄音",
                "請等待處理完成後再開始新錄音"
            )
            return
        
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        """開始錄音"""
        if self.recording_thread and self.recording_thread.is_alive():
            logger.warning("Previous recording thread still running, waiting for it to finish...")
            self.recording_thread.join(timeout=1.0)
            if self.recording_thread.is_alive():
                logger.error("Previous recording thread did not finish in time")
        
        self.recording = True
        
        # 清空之前的音頻數據和隊列
        with self.audio_lock:
            self.audio_data = []
        
        # 清空 audio_queue 中的殘留數據
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        
        self.title = "🔴"  # 改變狀態列圖示為紅點
        self.menu["開始錄音 (⌃⌥R)"].title = "停止錄音 (⌃⌥R)"
        if self.recording_mode == "refine":
            self.menu["潤飾語音 (⌃⌥S)"].title = "⏺ 潤飾錄音中..."
        # 錄音中時，⌃⌥E 才有意義：把 menu 提示成「按 ⌃⌥E 停止並送出」
        self.menu["停止並送出 (⌃⌥E)"].title = "停止並送出 (⌃⌥E)"
        self.menu["錄音中..."].state = True

        logger.info("Recording started...")

        self.recording_thread = threading.Thread(target=self._record_audio, daemon=True)
        self.recording_thread.start()

    def _record_audio(self):
        """錄音線程"""
        def audio_callback(indata, frames, time, status):
            if status:
                logger.warning(f"Recording status: {status}")
            # 只有在錄音狀態時才將數據放入隊列
            if self.recording:
                try:
                    self.audio_queue.put_nowait(indata.copy())
                except queue.Full:
                    logger.warning("Audio queue full, dropping audio chunk")

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=audio_callback,
                dtype=np.int16,
                blocksize=1024
            ):
                while self.recording:
                    try:
                        data = self.audio_queue.get(timeout=0.1)
                        with self.audio_lock:
                            self.audio_data.append(data)
                    except queue.Empty:
                        if not self.recording:
                            break
                        continue
                
                end_time = time.time() + 1.0
                while time.time() < end_time:
                    try:
                        data = self.audio_queue.get(timeout=0.1)
                        with self.audio_lock:
                            self.audio_data.append(data)
                    except queue.Empty:
                        if self.audio_queue.empty():
                            break
                        continue
                    
            remaining_count = 0
            while not self.audio_queue.empty():
                try:
                    data = self.audio_queue.get_nowait()
                    with self.audio_lock:
                        self.audio_data.append(data)
                    remaining_count += 1
                except queue.Empty:
                    break
            
            if remaining_count > 0:
                logger.info(f"Processed {remaining_count} remaining audio chunks after stream closed")
                    
            with self.audio_lock:
                total_chunks = len(self.audio_data)
            logger.info(f"Recording thread ended, collected {total_chunks} audio chunks")
            
        except Exception as e:
            logger.error(f"Recording error: {e}", exc_info=True)
            rumps.notification(
                "錄音錯誤",
                "無法訪問麥克風",
                str(e)
            )

    def stop_recording(self):
        """停止錄音並轉換為文字"""
        self.recording = False
        self.processing = True  # 標記開始處理
        self.title = "🔄"  # 立即顯示處理中圖標
        self.menu["開始錄音 (⌃⌥R)"].title = "處理中..."
        if self.recording_mode == "refine":
            self.menu["潤飾語音 (⌃⌥S)"].title = "處理中..."
        elif self.recording_mode == "transcribe_and_send":
            self.menu["停止並送出 (⌃⌥E)"].title = "處理中..."
        self.menu["錄音中..."].state = False

        logger.info("Recording stopped, waiting for audio thread to finish...")

        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=2.0)
            if self.recording_thread.is_alive():
                logger.warning("Recording thread did not finish in time, proceeding anyway")
            else:
                logger.info("Recording thread finished successfully")
        
        time.sleep(0.1)

        with self.audio_lock:
            audio_data_copy = list(self.audio_data)
        
        logger.info(f"Collected {len(audio_data_copy)} audio chunks, starting transcription...")

        if not audio_data_copy:
            self.title = "🎤"  # 恢復狀態列圖示
            self.processing = False
            self.menu["開始錄音 (⌃⌥R)"].title = "開始錄音 (⌃⌥R)"
            self.menu["潤飾語音 (⌃⌥S)"].title = "潤飾語音 (⌃⌥S)"
            self.menu["停止並送出 (⌃⌥E)"].title = "停止並送出 (⌃⌥E)"
            rumps.notification(
                "語音轉文字",
                "未錄到音頻",
                "請確保麥克風已開啟"
            )
            return

        # 在新線程中處理音頻，傳入複製的數據
        threading.Thread(target=self._process_audio, args=(audio_data_copy,), daemon=True).start()

    def _process_audio(self, audio_data_copy):
        """處理音頻並轉換為文字
        
        Args:
            audio_data_copy: 音頻數據的副本，避免競爭條件
        """
        temp_path = None
        try:
            logger.info(f"Processing {len(audio_data_copy)} audio chunks...")
            
            # 合併音頻數據
            if not audio_data_copy:
                raise ValueError("No audio data to process")
            
            audio_array = np.concatenate(audio_data_copy, axis=0)
            logger.info(f"Audio array shape: {audio_array.shape}, duration: {len(audio_array)/self.sample_rate:.2f}s")

            # 保存為臨時 WAV 文件
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_path = temp_file.name
                wavfile.write(temp_path, self.sample_rate, audio_array)

            logger.info(f"Audio saved to: {temp_path}")

            # 計算音頻時長，決定是否用 long endpoint
            audio_duration = len(audio_array) / self.sample_rate
            use_long = self.use_ai_builder and audio_duration > LONG_AUDIO_DURATION_THRESHOLD

            # Fallback chain: AI Builder → Gemini → OpenAI
            text, provider_name = self._transcribe_with_fallback(temp_path, use_long=use_long)
            logger.info(f"Transcription result (original, via {provider_name}): {text}")
            
            # 將簡體中文轉換為繁體中文
            text = self.cc.convert(text)
            # 將不常用的繁體字改成常用的
            text = apply_manual_mappings(text, MANUAL_MAPPINGS)
            logger.info(f"Transcription result (traditional): {text}")

            # 潤飾模式：呼叫 LLM 潤飾
            original_text = text
            if self.recording_mode == "refine":
                # 先把原始文字稿存到剪貼簿（轉錄完成即可用）
                self.copy_to_clipboard(original_text)
                logger.info(f"[Original → clipboard] {original_text}")

                self.title = "✨"
                refined = self._refine_text(original_text)
                if refined:
                    text = refined
                    logger.info(f"[Refined] {text}")
                else:
                    logger.warning("Refine failed, keeping original in clipboard")

            # 恢復圖示和狀態
            self.title = "🎤"
            self.menu["開始錄音 (⌃⌥R)"].title = "開始錄音 (⌃⌥R)"
            self.menu["潤飾語音 (⌃⌥S)"].title = "潤飾語音 (⌃⌥S)"
            self.menu["停止並送出 (⌃⌥E)"].title = "停止並送出 (⌃⌥E)"

            # 複製到剪貼板（refine 模式下覆蓋為潤飾結果）
            self.copy_to_clipboard(text)

            # 添加到最近結果
            self.recent_results.append(text)
            self.update_recent_results_menu()

            # 自動粘貼到焦點應用
            pasted = False
            if self.auto_paste_enabled:
                pasted = self.auto_paste_to_focused_app(text)

            # transcribe_and_send 模式：粘貼成功後再模擬 Enter 自動送出
            # Why: 一些 chat UI（Slack/iMessage/ChatGPT 等）粘貼後仍需 Enter 才會送出，
            # 因此先確保 paste 成功再 fire Return，避免 Enter 落到沒文字的輸入框觸發空送出。
            sent = False
            if self.recording_mode == "transcribe_and_send" and pasted:
                time.sleep(0.05)  # 給目標 app 一點時間處理 paste 後再送 Enter
                sent = self.simulate_return_key()

            # 顯示通知（含 provider 名稱）
            if self.recording_mode == "refine":
                mode_label = "語音潤飾完成"
            elif self.recording_mode == "transcribe_and_send":
                mode_label = f"語音轉文字並送出（{provider_name}）"
            else:
                mode_label = f"語音轉文字完成（{provider_name}）"
            if pasted:
                app_info = self.get_focused_app_info()
                app_name = app_info['name'] if app_info else "應用"
                if self.recording_mode == "transcribe_and_send":
                    paste_msg = f"已粘貼並送出到 {app_name}" if sent else f"已粘貼到 {app_name}（Enter 送出失敗）"
                else:
                    paste_msg = f"已自動粘貼到 {app_name}"
                rumps.notification(
                    mode_label,
                    paste_msg,
                    text[:100] + "..." if len(text) > 100 else text
                )
            else:
                rumps.notification(
                    mode_label,
                    "已複製到剪貼板" if not self.auto_paste_enabled else "已複製到剪貼板（粘貼失敗）",
                    text[:100] + "..." if len(text) > 100 else text
                )

        except Exception as e:
            logger.error(f"Audio processing error: {e}", exc_info=True)
            # 恢復圖示和狀態
            self.title = "🎤"
            self.menu["開始錄音 (⌃⌥R)"].title = "開始錄音 (⌃⌥R)"
            self.menu["潤飾語音 (⌃⌥S)"].title = "潤飾語音 (⌃⌥S)"
            self.menu["停止並送出 (⌃⌥E)"].title = "停止並送出 (⌃⌥E)"

            # 全部失敗：保存錄音到持久目錄
            if temp_path and os.path.exists(temp_path):
                self._save_failed_recording(temp_path)

            rumps.notification(
                "轉換錯誤",
                "無法轉換語音為文字",
                str(e)[:100]
            )
        finally:
            # 確保 processing 標誌被重置
            self.processing = False
            logger.info("Processing completed, ready for next recording")

            # 成功時把錄音搬到持久目錄保留（失敗時已搬到 failed_recordings）
            # 舊檔改由啟動時的 _cleanup_old_recordings() 按 7 天保留期清除
            if temp_path and os.path.exists(temp_path):
                self._archive_recording(temp_path)

    def _save_failed_recording(self, temp_path: str):
        """將失敗的錄音保存到持久目錄，並自動清理舊檔"""
        try:
            import shutil
            save_dir = os.path.expanduser("~/Documents/SpeechToText/failed_recordings")
            os.makedirs(save_dir, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(save_dir, f"recording_{timestamp}.wav")
            shutil.move(temp_path, dest)
            logger.info(f"Failed recording saved to: {dest}")
            rumps.notification("錄音已保存", "轉錄失敗，錄音已保存", dest)

            # 自動清理：保留最新 50 個
            files = sorted(
                [os.path.join(save_dir, f) for f in os.listdir(save_dir)],
                key=os.path.getmtime,
            )
            for old_file in files[:-50]:
                try:
                    os.unlink(old_file)
                except OSError:
                    pass
        except Exception as e:
            logger.warning(f"Failed to save recording: {e}")

    def _archive_recording(self, temp_path: str):
        """成功轉錄後把錄音搬到持久目錄，之後由啟動時的保留期清理負責刪除"""
        try:
            import shutil
            os.makedirs(RECORDINGS_DIR, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(RECORDINGS_DIR, f"recording_{timestamp}.wav")
            shutil.move(temp_path, dest)
            logger.info(f"Recording archived to: {dest}")
        except Exception as e:
            # 搬移失敗時退回刪除，避免臨時檔殘留在系統暫存目錄
            logger.warning(f"Failed to archive recording, deleting temp file instead: {e}")
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _cleanup_old_recordings(self):
        """啟動時清除超過保留期的錄音檔"""
        try:
            if not os.path.isdir(RECORDINGS_DIR):
                return
            cutoff = time.time() - RECORDINGS_RETENTION_DAYS * 86400
            removed = 0
            for name in os.listdir(RECORDINGS_DIR):
                path = os.path.join(RECORDINGS_DIR, name)
                try:
                    if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                        os.unlink(path)
                        removed += 1
                except OSError:
                    pass
            if removed:
                logger.info(
                    f"Cleaned up {removed} recording(s) older than "
                    f"{RECORDINGS_RETENTION_DAYS} days from {RECORDINGS_DIR}"
                )
        except Exception as e:
            logger.warning(f"Failed to clean up old recordings: {e}")

    # ------------------------------------------------------------------
    # Transcription provider helpers
    # ------------------------------------------------------------------

    def _transcribe_ai_builder(self, audio_path: str) -> str:
        """使用 AI Builder 短音頻轉錄 API"""
        url = f"{self.ai_builder_base}/v1/audio/transcriptions"
        lang = getattr(self, "language", None)
        boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
        with open(audio_path, "rb") as audio_file:
            audio_bytes = audio_file.read()
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="audio_file"; filename="audio.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8") + audio_bytes
        if lang:
            body += f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{lang}\r\n".encode("utf-8")
        body += f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.ai_builder_api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
        logger.debug("AI Builder raw response: %s", raw[:500])
        result = json.loads(raw)
        text = self._clean_ai_builder_text(result.get("text", ""))
        logger.info("AI Builder transcription result (original): %s", text)
        return text

    def _transcribe_openai(self, audio_path: str) -> str:
        """使用 OpenAI Whisper API 轉錄"""
        logger.info("Calling OpenAI Whisper API...")
        with open(audio_path, "rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
                language=getattr(self, "language", None),
            )
        return transcript.text

    @staticmethod
    def _clean_ai_builder_text(text: str) -> str:
        """清理 AI Builder 回傳文字。

        AI Builder 有時在 text 欄位塞入 nested JSON，例如：
          {"query": "實際文字\\n\\n更多"}
        需要解析取出真正的轉錄文字。
        """
        text = text.strip()
        if text.startswith("{") or text.startswith('"'):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    text = (
                        parsed.get("query")
                        or parsed.get("text")
                        or next((v for v in parsed.values() if isinstance(v, str)), text)
                    )
                elif isinstance(parsed, str):
                    text = parsed
            except (json.JSONDecodeError, StopIteration):
                pass
        text = re.sub(r'["\}\{]+\s*$', '', text)
        return text.strip()

    @staticmethod
    def _clean_gemini_response(raw: str) -> str:
        """清理 Gemini 回傳的轉錄文字，移除 JSON/markdown 包裝。

        Gemini 是 LLM 而非專用 STT API，有時會把結果包在 JSON 或 markdown 裡，例如：
          {"text": "你好\\n"}
          ```\\n你好\\n```
        """
        text = raw.strip()

        # 1) 移除 markdown code block
        m = re.match(r"^```(?:json|text)?\s*\n?(.*?)\n?\s*```$", text, re.DOTALL)
        if m:
            text = m.group(1).strip()

        # 2) 嘗試 JSON 解析
        if text.startswith("{") or text.startswith('"'):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    text = parsed.get("text") or next(
                        (v for v in parsed.values() if isinstance(v, str)), text
                    )
                elif isinstance(parsed, str):
                    text = parsed
            except (json.JSONDecodeError, StopIteration):
                pass

        # 3) 移除首尾殘留引號
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
            text = text[1:-1]

        return text.strip()

    def _transcribe_gemini(self, audio_path: str) -> str:
        """使用 Gemini 2.5 Flash 轉錄音頻"""
        if not _GEMINI_AVAILABLE:
            raise ImportError("google-genai package is not installed")

        if self.gemini_client is None:
            self.gemini_client = genai.Client(api_key=self.gemini_api_key)

        file_size = os.path.getsize(audio_path)
        suffix = os.path.splitext(audio_path)[1].lstrip(".")
        mime_type = f"audio/{suffix}" if suffix else "audio/wav"

        prompt = (
            "請將這段語音完整轉錄為文字。"
            "只輸出轉錄的純文字，保留原始語言，不要翻譯、潤飾或摘要。"
            "不要用 JSON、markdown、引號或任何格式包裝，直接輸出文字內容。"
        )
        lang = getattr(self, "language", None)
        if lang:
            prompt += f"\n語言提示: {lang}"

        if file_size < _GEMINI_INLINE_LIMIT:
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        else:
            logger.info("Gemini: file >= 20MB, using Files API upload...")
            audio_part = self.gemini_client.files.upload(file=audio_path)

        response = self.gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[audio_part, prompt],
        )
        text = self._clean_gemini_response(response.text)
        logger.info("Gemini transcription result (original): %s", text)
        return text

    def _build_provider_chain(self, use_long: bool = False):
        """依成本排序建立 provider fallback chain。

        Returns:
            list of (name, callable) tuples
        """
        # 強制走 OpenAI：繞過成本排序，只用 OpenAI（含長錄音 checkpoint segment）
        if self.force_openai and self.client:
            return [("OpenAI", self._transcribe_openai)]

        chain = []
        if self.use_ai_builder:
            if use_long:
                chain.append(("AI Builder (long)", self._transcribe_ai_builder_long))
            else:
                chain.append(("AI Builder", self._transcribe_ai_builder))
        if self.gemini_api_key:
            chain.append(("Gemini", self._transcribe_gemini))
        if self.client:
            chain.append(("OpenAI", self._transcribe_openai))
        return chain

    def _transcribe_with_fallback(self, audio_path: str, use_long: bool = False):
        """
        依序嘗試 provider chain，成功即回傳。

        Returns:
            (text, provider_name)

        Raises:
            RuntimeError: 所有 provider 皆失敗
        """
        chain = self._build_provider_chain(use_long)
        errors = []
        for i, (name, fn) in enumerate(chain):
            try:
                if i > 0:
                    self.title = "🔁"
                    rumps.notification("切換轉錄服務", f"改用 {name} 重試...", errors[-1][:60])
                return fn(audio_path), name
            except Exception as e:
                errors.append(f"{name}: {e}")
                logger.warning("Provider failed: %s", errors[-1])
        raise RuntimeError("所有轉錄服務皆失敗: " + "; ".join(errors))

    def _refine_text(self, text):
        """使用 LLM 潤飾文字"""
        if not self.chat_client:
            logger.warning("No chat client available for refine feature")
            rumps.notification("潤飾失敗", "需要 OpenAI API Key", "請設置 OPENAI_API_KEY")
            return None
        try:
            logger.info(f"Refining with model: {self.refine_model}")
            response = self.chat_client.chat.completions.create(
                model=self.refine_model,
                messages=[
                    {"role": "system", "content": REFINE_SYSTEM_PROMPT},
                    {"role": "user", "content": REFINE_USER_PROMPT + text}
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Refine error: {e}", exc_info=True)
            rumps.notification("潤飾失敗", "LLM 呼叫失敗", str(e)[:100])
            return None

    def _transcribe_ai_builder_long(self, audio_path: str) -> str:
        """使用 AI Builder long transcription API 轉錄長音頻（小時級）

        呼叫 /v1/audio/transcriptions_long（AssemblyAI），支援：
        - sentence-level timestamps
        - speaker diarization
        - disfluency removal

        Args:
            audio_path: WAV/MP3/M4A 音頻檔路徑

        Returns:
            轉錄文字
        """
        url = f"{self.ai_builder_base}/v1/audio/transcriptions_long"
        lang = getattr(self, "language", None)
        boundary = "----WebKitFormBoundary" + os.urandom(16).hex()

        filename = os.path.basename(audio_path)
        suffix = os.path.splitext(audio_path)[1].lstrip(".")
        content_type = f"audio/{suffix}" if suffix else "audio/wav"

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        # 構建 multipart body
        parts = []
        # audio_file
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio_file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        )
        body = parts[0].encode("utf-8") + audio_bytes

        # language（可選）
        if lang:
            body += (
                f"\r\n--{boundary}\r\n"
                f'Content-Disposition: form-data; name="language"\r\n\r\n'
                f"{lang}"
            ).encode("utf-8")

        # speaker_labels=true
        body += (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="speaker_labels"\r\n\r\n'
            f"true"
        ).encode("utf-8")

        # disfluencies=false（保留原始語音）
        body += (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="disfluencies"\r\n\r\n'
            f"false"
        ).encode("utf-8")

        body += f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.ai_builder_api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )

        # 長音頻需要更長的 timeout（1 小時音頻大約需要 5-10 分鐘處理）
        timeout = 600  # 10 分鐘
        logger.info("Calling long transcription API (timeout=%ds)...", timeout)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
        logger.debug("AI Builder long raw response: %s", raw[:500])
        result = json.loads(raw)

        text = self._clean_ai_builder_text(result.get("text", ""))
        duration = result.get("duration_seconds")
        confidence = result.get("confidence")
        speakers = result.get("speakers")
        logger.info(
            "Long transcription done: duration=%.1fs, confidence=%.3f, speakers=%d segments",
            duration or 0,
            confidence or 0,
            len(speakers) if speakers else 0,
        )
        logger.info("Long transcription result (original): %s", text[:200] + "..." if len(text) > 200 else text)
        return text

    def copy_to_clipboard(self, text):
        """複製文字到剪貼板"""
        try:
            pyperclip.copy(text)
            logger.info("Copied to clipboard")
        except Exception as e:
            logger.error(f"Failed to copy to clipboard: {e}")

    def batch_transcribe(self, _):
        """批次轉錄目錄中的所有音頻文件"""
        # 使用 rumps.Window 讓用戶輸入目錄路徑
        response = rumps.Window(
            "批次轉錄",
            "請輸入包含音頻文件的目錄路徑:",
            default_text="~/Downloads/recordings",
            ok="開始轉錄",
            cancel="取消"
        ).run()

        if not response.clicked:
            return

        directory = response.text.strip()
        if not directory:
            rumps.alert("錯誤", "請輸入有效的目錄路徑")
            return

        # 展開 ~ 符號
        directory = os.path.expanduser(directory)

        if not os.path.isdir(directory):
            rumps.alert("錯誤", f"目錄不存在: {directory}")
            return

        # 在後台線程中處理，避免阻塞 UI
        threading.Thread(
            target=self._process_batch_transcription,
            args=(directory,),
            daemon=True
        ).start()

    def _process_batch_transcription(self, directory: str):
        """在後台處理批次轉錄"""
        try:
            # 顯示開始通知
            rumps.notification(
                "批次轉錄",
                "開始處理...",
                f"正在掃描目錄: {directory}"
            )

            # 確定使用哪個 API
            if self.use_ai_builder:
                api_key = self.ai_builder_api_key
                api_base = self.ai_builder_base
            else:
                api_key = os.getenv("OPENAI_API_KEY")
                api_base = "https://api.openai.com"

            # 執行批次轉錄
            language = getattr(self, "language", None)
            gemini_key = get_gemini_api_key() if _GEMINI_AVAILABLE else None
            results = batch_transcribe_directory(
                directory=directory,
                api_key=api_key,
                api_base=api_base,
                language=language,
                save_txt=True,
                max_retries=1,
                gemini_api_key=gemini_key,
            )

            # 統計結果
            successes = [r for r in results if r.success]
            failures = [r for r in results if not r.success]

            # 應用繁體轉換到所有成功的轉錄
            processed_texts = []
            for result in successes:
                if result.text:
                    # 轉換為繁體中文
                    text = self.cc.convert(result.text)
                    # 應用手動映射
                    text = apply_manual_mappings(text, MANUAL_MAPPINGS)
                    processed_texts.append(f"[{os.path.basename(result.file_path)}]\n{text}")

                    # 更新保存的 .txt 文件（用繁體版本）
                    from pathlib import Path
                    txt_path = Path(result.file_path).with_suffix('.txt')
                    try:
                        txt_path.write_text(text, encoding='utf-8')
                    except Exception as e:
                        logger.error(f"Failed to update txt file: {e}")

            # 將所有轉錄複製到剪貼板
            if processed_texts:
                all_text = "\n\n".join(processed_texts)
                self.copy_to_clipboard(all_text)

            # 顯示完成通知
            if failures:
                rumps.notification(
                    "批次轉錄完成",
                    f"成功: {len(successes)}, 失敗: {len(failures)}",
                    f"結果已複製到剪貼板\n失敗的文件:\n" + "\n".join([os.path.basename(f.file_path) for f in failures[:3]])
                )
            else:
                rumps.notification(
                    "批次轉錄完成",
                    f"成功轉錄 {len(successes)} 個文件",
                    "所有結果已複製到剪貼板並保存為 .txt 文件"
                )

        except Exception as e:
            logger.error(f"Batch transcription error: {e}", exc_info=True)
            rumps.notification(
                "批次轉錄錯誤",
                "處理失敗",
                str(e)[:100]
            )

    def convert_webm_to_mp3(self, _):
        """將 .webm 檔案轉換為 .mp3"""
        response = rumps.Window(
            "WebM 轉 MP3",
            "請輸入 .webm 檔案或目錄路徑:",
            default_text="~/Downloads",
            ok="開始轉換",
            cancel="取消"
        ).run()

        if not response.clicked:
            return

        path = os.path.expanduser(response.text.strip())
        if not path:
            rumps.alert("錯誤", "請輸入有效的路徑")
            return

        if not os.path.exists(path):
            rumps.alert("錯誤", f"路徑不存在: {path}")
            return

        threading.Thread(
            target=self._process_webm_conversion,
            args=(path,),
            daemon=True
        ).start()

    def _process_webm_conversion(self, path: str):
        """在後台處理 webm → mp3 轉換"""
        try:
            ffmpeg = _find_ffmpeg()
            if not ffmpeg:
                rumps.notification(
                    "轉換失敗",
                    "找不到 ffmpeg",
                    "請安裝: brew install ffmpeg 或 pip install imageio-ffmpeg"
                )
                return

            from pathlib import Path as P
            target = P(path)
            if target.is_dir():
                webm_files = sorted(target.glob("*.webm"))
            elif target.is_file() and target.suffix.lower() == ".webm":
                webm_files = [target]
            else:
                rumps.notification("轉換失敗", "無效輸入", "請提供 .webm 檔案或包含 .webm 的目錄")
                return

            if not webm_files:
                rumps.notification("轉換完成", "沒有找到 .webm 檔案", path)
                return

            rumps.notification("WebM 轉 MP3", "開始轉換...", f"{len(webm_files)} 個檔案")

            succeeded, failed = 0, 0
            for webm in webm_files:
                mp3 = webm.with_suffix(".mp3")
                result = subprocess.run(
                    [ffmpeg, "-i", str(webm), "-vn", "-ab", "192k", "-y", str(mp3)],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    succeeded += 1
                    logger.info(f"Converted: {webm} -> {mp3}")
                else:
                    failed += 1
                    logger.error(f"Failed to convert {webm}: {result.stderr[:200]}")

            rumps.notification(
                "WebM 轉 MP3 完成",
                f"成功: {succeeded}, 失敗: {failed}",
                f"輸出目錄: {P(path).parent if P(path).is_file() else path}"
            )

        except Exception as e:
            logger.error(f"WebM conversion error: {e}", exc_info=True)
            rumps.notification("轉換錯誤", "處理失敗", str(e)[:100])

    # ------------------------------------------------------------------
    # OpenAI single-file transcription (gpt-4o-transcribe)
    # ------------------------------------------------------------------

    OPENAI_TRANSCRIBE_MODEL = "gpt-4o-transcribe"
    OPENAI_TRANSCRIBE_SIZE_LIMIT = 25 * 1024 * 1024

    def _ensure_openai_session_md(self):
        """第一次呼叫時建一個 session log MD 並用系統預設 app 開啟，回傳路徑。"""
        if self.openai_session_md_path:
            return self.openai_session_md_path

        session_id = time.strftime("%Y%m%d_%H%M%S")
        save_dir = os.path.expanduser("~/Documents/SpeechToText/openai_transcriptions")
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create OpenAI transcriptions dir: {e}")
            return None

        md_path = os.path.join(save_dir, f"openai_{session_id}.md")
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# OpenAI Transcription Session {session_id}\n\n")
                f.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Model: {self.OPENAI_TRANSCRIBE_MODEL}\n\n")
            self.openai_session_md_path = md_path
            logger.info(f"[OpenAI session MD created] path={md_path}")
        except OSError as e:
            logger.error(f"Failed to create OpenAI session MD: {e}")
            return None

        try:
            subprocess.Popen(["open", md_path])
        except Exception as e:
            logger.warning(f"Failed to `open` OpenAI session MD: {e}")

        return md_path

    def _append_to_openai_session_md(self, source_path: str, text: str):
        """把一次單檔轉錄結果 append 到 session MD（lock 保護平行寫入）"""
        md_path = self.openai_session_md_path
        if not md_path:
            return
        timestamp = time.strftime("%H:%M:%S")
        block = (
            f"## {os.path.basename(source_path)} — {timestamp}\n\n"
            f"`{source_path}`\n\n"
            f"{text}\n\n"
        )
        try:
            with self.openai_session_md_lock:
                with open(md_path, "a", encoding="utf-8") as f:
                    f.write(block)
            logger.info(f"[OpenAI MD appended] source={source_path}")
        except OSError as e:
            logger.error(f"Failed to append to OpenAI session MD: {e}")

    def transcribe_audio_file(self, _):
        """選一個音檔，用 OpenAI 最新 STT 模型轉錄"""
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            rumps.alert(
                "需要 OpenAI API Key",
                "此功能需要直連 OpenAI，請設置 OPENAI_API_KEY"
            )
            return

        response = rumps.Window(
            f"轉錄音檔 ({self.OPENAI_TRANSCRIBE_MODEL})",
            "請輸入音檔路徑 (支援 mp3/wav/m4a/webm/flac/ogg):",
            default_text="~/Downloads/",
            ok="開始轉錄",
            cancel="取消",
            dimensions=(420, 24),
        ).run()

        if not response.clicked:
            return

        path = os.path.expanduser(response.text.strip())
        if not path:
            rumps.alert("錯誤", "請輸入有效的路徑")
            return
        if not os.path.isfile(path):
            rumps.alert("錯誤", f"檔案不存在: {path}")
            return

        threading.Thread(
            target=self._process_openai_file_transcription,
            args=(path,),
            daemon=True,
        ).start()

    def _process_openai_file_transcription(self, path: str):
        """背景執行單檔 OpenAI 轉錄"""
        try:
            size = os.path.getsize(path)
            if size > self.OPENAI_TRANSCRIBE_SIZE_LIMIT:
                rumps.notification(
                    "檔案過大",
                    f"OpenAI API 限制 25MB（此檔 {size / 1024 / 1024:.1f}MB）",
                    "請先壓縮或分段，再使用批次轉錄"
                )
                return

            md_path = self._ensure_openai_session_md()

            rumps.notification(
                "OpenAI 轉錄",
                f"開始處理 ({self.OPENAI_TRANSCRIBE_MODEL})",
                f"{os.path.basename(path)} → {os.path.basename(md_path) if md_path else '(無 log)'}",
            )

            openai_key = os.getenv("OPENAI_API_KEY")
            client = self.client if self.client else OpenAI(api_key=openai_key)
            language = getattr(self, "language", None)

            with open(path, "rb") as audio_file:
                kwargs = {
                    "model": self.OPENAI_TRANSCRIBE_MODEL,
                    "file": audio_file,
                }
                if language:
                    kwargs["language"] = language
                transcript = client.audio.transcriptions.create(**kwargs)

            text = transcript.text or ""
            text = self.cc.convert(text)
            text = apply_manual_mappings(text, MANUAL_MAPPINGS)

            from pathlib import Path
            txt_path = Path(path).with_suffix(".txt")
            try:
                txt_path.write_text(text, encoding="utf-8")
            except OSError as e:
                logger.error(f"Failed to save txt: {e}")
                txt_path = None

            self.copy_to_clipboard(text)
            self.recent_results.append(text)
            self.update_recent_results_menu()

            self._append_to_openai_session_md(path, text)

            preview = text[:100] + "..." if len(text) > 100 else text
            saved_msg = f"已存 {txt_path.name}" if txt_path else "(txt 寫入失敗)"
            md_msg = f" | append→{os.path.basename(self.openai_session_md_path)}" if self.openai_session_md_path else ""
            rumps.notification(
                f"轉錄完成 ({self.OPENAI_TRANSCRIBE_MODEL})",
                f"已複製到剪貼板 | {saved_msg}{md_msg}",
                preview,
            )
            logger.info(
                f"[OpenAI file transcription done] file={path} chars={len(text)} "
                f"txt={txt_path} session_md={self.openai_session_md_path}"
            )

        except Exception as e:
            logger.error(f"OpenAI file transcription error: {e}", exc_info=True)
            rumps.notification("轉錄失敗", "OpenAI API 呼叫失敗", str(e)[:100])

    @rumps.clicked("關於")
    def about(self, _):
        """顯示關於信息"""
        rumps.alert(
            "語音轉文字 v1.2",
            "一個簡單的 macOS 狀態列應用\n"
            "使用 OpenAI Whisper API 進行語音識別\n\n"
            "快捷鍵:\n"
            "  ⌃⌥R - 開始錄音；再按一次停止並只轉文字\n"
            "  ⌃⌥E - （錄音中按）停止錄音、轉文字後自動按 Enter 送出\n"
            "  ⌃⌥S - 語音潤飾（轉文字＋LLM 潤飾）\n"
            "  ⌃⌥Q - Checkpoint 錄音開始/結束（長錄音）\n"
            "  ⌃⌥W - 在 checkpoint 錄音中標記一段轉文字\n"
            "  ⌘A - 菜單快捷鍵（需打開菜單）\n\n"
            "功能:\n"
            "  • 語音轉文字\n"
            "  • 語音潤飾（AI 修飾口語）\n"
            "  • Checkpoint 模式（持續錄音，分段即時轉文字）\n"
            "  • 轉錄音檔（OpenAI gpt-4o-transcribe）\n"
            "  • 自動粘貼到焦點應用\n"
            "  • 全局快捷鍵\n\n"
            "© 2025"
        )

    def quit_app(self, _):
        """退出應用"""
        # 停止全局快捷鍵監聽器
        self.stop_global_hotkey_listener()
        logger.info("Application quitting...")
        rumps.quit_application()


def main():
    """主函數"""
    # 至少需要 OPENAI_API_KEY 或 AI_BUILDER_API_KEY（可寫在 ~/.zshrc）
    if not get_ai_builder_api_key() and not os.getenv("OPENAI_API_KEY"):
        print("錯誤: 請設置 OPENAI_API_KEY 或 AI_BUILDER_API_KEY")
        print("  OpenAI: export OPENAI_API_KEY='your-api-key'")
        print("  AI Builder: 在 ~/.zshrc 加入 export AI_BUILDER_API_KEY='your-key'")
        return

    app = SpeechToClipboardApp()
    app.run()


if __name__ == "__main__":
    main()
