#!/usr/bin/env python3
"""
macOS 狀態列語音轉文字應用
Speech-to-Text macOS Menubar App
"""

import rumps
import sounddevice as sd
import numpy as np
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

# 將不常用的繁體字改成常用的（來自 clip2trad-python）
MANUAL_MAPPINGS = {
    '瞭解': '了解',
    '羣': '群',
    '臺': '台',
    '峯': '峰',
    '喫': '吃',
    '纔': '才',
}


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

        # 初始化 OpenAI 客戶端
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            rumps.alert("錯誤", "請設置 OPENAI_API_KEY 環境變量")
            raise ValueError("OPENAI_API_KEY not set")

        self.client = OpenAI(api_key=api_key)

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

        # 設置菜單
        self.menu = [
            rumps.MenuItem("開始錄音 (⌃⌥A)", callback=self.toggle_recording, key="a"),
            rumps.separator,
            rumps.MenuItem("錄音中...", callback=None),
            rumps.separator,
            rumps.MenuItem("最近結果"),
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

        # 初始化設定子菜單
        self.setup_settings_menu()

        # 檢查輔助功能權限
        self.check_accessibility_permission()

        # 啟動全局快捷鍵監聽
        self.start_global_hotkey_listener()

    def check_accessibility_permission(self):
        """檢查輔助功能權限"""
        options = {kAXTrustedCheckOptionPrompt: True}
        trusted = AXIsProcessTrustedWithOptions(options)
        if not trusted:
            logger.warning("Accessibility permission required for auto-paste")
        return trusted

    def setup_settings_menu(self):
        """設置設定子菜單"""
        settings_menu = [
            rumps.MenuItem("語言: 自動偵測", callback=self.change_language),
            rumps.MenuItem("✓ 自動粘貼到焦點應用", callback=self.toggle_auto_paste),
            rumps.MenuItem("✓ 全局快捷鍵 (⌃⌥A)", callback=self.toggle_global_hotkey),
            rumps.MenuItem("模型: gpt-4o-mini-transcribe", callback=None),
        ]
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
            sender.title = "✓ 全局快捷鍵 (⌃⌥A)"
            self.start_global_hotkey_listener()
            logger.info("Global hotkey enabled")
        else:
            sender.title = "全局快捷鍵 (⌃⌥A)"
            self.stop_global_hotkey_listener()
            logger.info("Global hotkey disabled")

    def start_global_hotkey_listener(self):
        """啟動全局快捷鍵監聽"""
        if not self.global_hotkey_enabled:
            return

        # 停止舊的監聽器
        self.stop_global_hotkey_listener()

        try:
            # 定義快捷鍵組合：Control + Option + A
            hotkey_combination = keyboard.HotKey(
                keyboard.HotKey.parse('<ctrl>+<alt>+a'),
                self.on_hotkey_pressed
            )

            # 創建監聽器
            self.hotkey_listener = keyboard.Listener(
                on_press=lambda key: hotkey_combination.press(self.hotkey_listener.canonical(key)),
                on_release=lambda key: hotkey_combination.release(self.hotkey_listener.canonical(key))
            )

            # 啟動監聽器（在後台線程運行）
            self.hotkey_listener.start()
            logger.info("Global hotkey listener started (Control+Option+A)")

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
        """全局快捷鍵被按下的回調"""
        logger.info("Global hotkey pressed (Control+Option+A)")
        # 切換錄音狀態
        self.toggle_recording(None)

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
        self.menu["開始錄音 (⌃⌥A)"].title = "停止錄音 (⌃⌥A)"
        self.menu["錄音中..."].state = True

        logger.info("Recording started...")

        # 在新線程中錄音
        threading.Thread(target=self._record_audio, daemon=True).start()

    def _record_audio(self):
        """錄音線程"""
        def audio_callback(indata, frames, time, status):
            if status:
                logger.warning(f"Recording status: {status}")
            # 只有在錄音狀態時才將數據放入隊列
            if self.recording:
                self.audio_queue.put(indata.copy())

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=audio_callback,
                dtype=np.int16
            ):
                while self.recording:
                    try:
                        data = self.audio_queue.get(timeout=0.1)
                        with self.audio_lock:
                            self.audio_data.append(data)
                    except queue.Empty:
                        continue
            
            # 錄音結束後，處理隊列中剩餘的數據
            while not self.audio_queue.empty():
                try:
                    data = self.audio_queue.get_nowait()
                    with self.audio_lock:
                        self.audio_data.append(data)
                except queue.Empty:
                    break
                    
            logger.info(f"Recording thread ended, collected {len(self.audio_data)} audio chunks")
            
        except Exception as e:
            logger.error(f"Recording error: {e}")
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
        self.menu["開始錄音 (⌃⌥A)"].title = "處理中..."
        self.menu["錄音中..."].state = False

        logger.info("Recording stopped, waiting for audio thread to finish...")

        # 給錄音線程一點時間來收集剩餘數據
        time.sleep(0.2)

        # 使用鎖安全地複製音頻數據
        with self.audio_lock:
            audio_data_copy = list(self.audio_data)
        
        logger.info(f"Collected {len(audio_data_copy)} audio chunks, starting transcription...")

        if not audio_data_copy:
            self.title = "🎤"  # 恢復狀態列圖示
            self.processing = False
            self.menu["開始錄音 (⌃⌥A)"].title = "開始錄音 (⌃⌥A)"
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

            # 使用 OpenAI Whisper API 轉換
            logger.info("Calling OpenAI Whisper API...")
            with open(temp_path, 'rb') as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=audio_file,
                    language=getattr(self, 'language', None)  # 可選語言參數
                )

            text = transcript.text
            logger.info(f"Transcription result (original): {text}")
            
            # 將簡體中文轉換為繁體中文
            text = self.cc.convert(text)
            # 將不常用的繁體字改成常用的
            text = apply_manual_mappings(text, MANUAL_MAPPINGS)
            logger.info(f"Transcription result (traditional): {text}")

            # 恢復圖示和狀態
            self.title = "🎤"
            self.menu["開始錄音 (⌃⌥A)"].title = "開始錄音 (⌃⌥A)"

            # 複製到剪貼板
            self.copy_to_clipboard(text)

            # 添加到最近結果
            self.recent_results.append(text)
            self.update_recent_results_menu()

            # 自動粘貼到焦點應用
            pasted = False
            if self.auto_paste_enabled:
                pasted = self.auto_paste_to_focused_app(text)

            # 顯示通知
            if pasted:
                app_info = self.get_focused_app_info()
                app_name = app_info['name'] if app_info else "應用"
                rumps.notification(
                    "語音轉文字完成",
                    f"已自動粘貼到 {app_name}",
                    text[:100] + "..." if len(text) > 100 else text
                )
            else:
                rumps.notification(
                    "語音轉文字完成",
                    "已複製到剪貼板" if not self.auto_paste_enabled else "已複製到剪貼板（粘貼失敗）",
                    text[:100] + "..." if len(text) > 100 else text
                )

        except Exception as e:
            logger.error(f"Audio processing error: {e}", exc_info=True)
            # 恢復圖示和狀態
            self.title = "🎤"
            self.menu["開始錄音 (⌃⌥A)"].title = "開始錄音 (⌃⌥A)"
            rumps.notification(
                "轉換錯誤",
                "無法轉換語音為文字",
                str(e)[:100]
            )
        finally:
            # 確保 processing 標誌被重置
            self.processing = False
            logger.info("Processing completed, ready for next recording")
            
            # 清理臨時文件
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp file: {e}")

    def copy_to_clipboard(self, text):
        """複製文字到剪貼板"""
        try:
            pyperclip.copy(text)
            logger.info("Copied to clipboard")
        except Exception as e:
            logger.error(f"Failed to copy to clipboard: {e}")

    @rumps.clicked("關於")
    def about(self, _):
        """顯示關於信息"""
        rumps.alert(
            "語音轉文字 v1.1",
            "一個簡單的 macOS 狀態列應用\n"
            "使用 OpenAI Whisper API 進行語音識別\n\n"
            "快捷鍵:\n"
            "  ⌃⌥A - 全局快捷鍵（隨時可用）\n"
            "  ⌘A - 菜單快捷鍵（需打開菜單）\n\n"
            "功能:\n"
            "  • 語音轉文字\n"
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
    # 檢查是否設置了 API key
    if not os.getenv('OPENAI_API_KEY'):
        print("錯誤: 請設置 OPENAI_API_KEY 環境變量")
        print("使用方法: export OPENAI_API_KEY='your-api-key'")
        return

    app = SpeechToClipboardApp()
    app.run()


if __name__ == "__main__":
    main()
