#!/usr/bin/env python3
"""
Batch transcription functionality for processing multiple audio files
"""

import os
import json
import struct
import subprocess
import tempfile
import shutil
import wave
import urllib.request
import urllib.error
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Gemini SDK — optional, lazy import
_GEMINI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types as genai_types
    _GEMINI_AVAILABLE = True
except ImportError:
    pass

# 超過此秒數的音頻自動使用 long transcription endpoint
LONG_AUDIO_DURATION_THRESHOLD = 300  # 5 分鐘

# AI Builder API 上傳大小限制（實測 51MB 觸發 413）
_AI_BUILDER_MAX_FILE_SIZE = 24 * 1024 * 1024  # 24 MB, conservative

# 無法取得精確時長時，用檔案大小估算（保守估計，以 wav 16kHz mono 16bit = 32KB/s 為準）
_WAV_BYTES_PER_SEC = 32_000
# 壓縮格式粗估（mp3 128kbps ≈ 16KB/s）
_COMPRESSED_BYTES_PER_SEC = 16_000


@dataclass
class TranscriptionResult:
    """Result of transcribing a single file"""
    file_path: str
    success: bool
    text: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: Optional[float] = None
    used_long_endpoint: bool = False
    sentences: Optional[List[Dict[str, Any]]] = field(default_factory=lambda: None)
    speakers: Optional[List[Dict[str, Any]]] = field(default_factory=lambda: None)


def estimate_audio_duration(file_path: str) -> Optional[float]:
    """
    估算音頻檔案的時長（秒）。

    WAV 檔案從 header 精確計算；其他格式用檔案大小粗估。

    Returns:
        估算秒數，無法判斷時回傳 None
    """
    p = Path(file_path)
    ext = p.suffix.lower()

    if ext == ".wav":
        try:
            with open(file_path, "rb") as f:
                riff = f.read(44)
                if len(riff) >= 44 and riff[:4] == b"RIFF" and riff[8:12] == b"WAVE":
                    # fmt chunk: sample_rate at offset 24 (4 bytes LE)
                    # byte_rate at offset 28 (4 bytes LE)
                    byte_rate = struct.unpack_from("<I", riff, 28)[0]
                    if byte_rate > 0:
                        file_size = p.stat().st_size
                        # data starts after header (~44 bytes), good enough estimate
                        return max(0, (file_size - 44)) / byte_rate
        except Exception as e:
            logger.debug(f"Failed to parse WAV header for {file_path}: {e}")

    # 其他格式：用檔案大小粗估
    try:
        file_size = p.stat().st_size
        bytes_per_sec = _COMPRESSED_BYTES_PER_SEC if ext in {".mp3", ".m4a", ".ogg", ".flac"} else _WAV_BYTES_PER_SEC
        return file_size / bytes_per_sec
    except Exception:
        return None


def find_audio_files(directory: str) -> List[str]:
    """
    Find all supported audio files in directory.

    Args:
        directory: Path to directory to search

    Returns:
        List of absolute paths to audio files
    """
    supported_extensions = {'.wav', '.mp3', '.m4a', '.flac', '.ogg'}
    audio_files = []

    directory_path = Path(directory)
    if not directory_path.exists() or not directory_path.is_dir():
        return []

    for file_path in directory_path.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
            audio_files.append(str(file_path))

    return sorted(audio_files)


def _build_multipart_body(
    boundary: str,
    file_path: str,
    audio_bytes: bytes,
    language: Optional[str] = None,
    speaker_labels: bool = True,
    disfluencies: bool = False,
    is_long: bool = False,
) -> bytes:
    """構建 multipart/form-data body"""
    filename = Path(file_path).name
    suffix = Path(file_path).suffix[1:]
    content_type = f"audio/{suffix}" if suffix else "audio/wav"

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio_file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + audio_bytes

    if language:
        body += (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="language"\r\n\r\n'
            f"{language}"
        ).encode("utf-8")

    if is_long:
        body += (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="speaker_labels"\r\n\r\n'
            f"{'true' if speaker_labels else 'false'}"
        ).encode("utf-8")

        body += (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="disfluencies"\r\n\r\n'
            f"{'true' if disfluencies else 'false'}"
        ).encode("utf-8")

    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body


import re as _re


def _clean_ai_builder_text(text: str) -> str:
    """清理 AI Builder 回傳文字。

    AI Builder 有時在 text 欄位塞入 nested JSON，例如：
      {"query": "實際文字\\n\\n更多"}
    需要解析取出真正的轉錄文字。
    """
    text = text.strip()

    # 偵測 nested JSON（text 本身是 JSON object 或 string）
    if text.startswith("{") or text.startswith('"'):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                # 取 "query" 或第一個字串值
                text = (
                    parsed.get("query")
                    or parsed.get("text")
                    or next((v for v in parsed.values() if isinstance(v, str)), text)
                )
            elif isinstance(parsed, str):
                text = parsed
        except (json.JSONDecodeError, StopIteration):
            pass

    # 清理尾端 JSON 殘留
    text = _re.sub(r'["\}\{]+\s*$', '', text)
    return text.strip()


# 20 MB inline upload limit for Gemini
_GEMINI_INLINE_LIMIT = 20 * 1024 * 1024

_GEMINI_TRANSCRIBE_PROMPT = (
    "請將這段語音完整轉錄為文字。"
    "只輸出轉錄的純文字，保留原始語言，不要翻譯、潤飾或摘要。"
    "不要用 JSON、markdown、引號或任何格式包裝，直接輸出文字內容。"
)


def _clean_gemini_response(raw: str) -> str:
    """清理 Gemini 回傳的轉錄文字，移除 JSON/markdown 包裝。

    Gemini 是 LLM 而非專用 STT API，有時會把結果包在 JSON 或 markdown 裡，例如：
      {"text": "你好\\n"}
      ```\n你好\n```
    """
    text = raw.strip()

    # 1) 移除 markdown code block 包裝
    m = _re.match(r"^```(?:json|text)?\s*\n?(.*?)\n?\s*```$", text, _re.DOTALL)
    if m:
        text = m.group(1).strip()

    # 2) 嘗試 JSON 解析（常見: {"text": "..."} 或純 JSON string）
    if text.startswith("{") or text.startswith('"'):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                # 取第一個字串值（通常是 "text" key）
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


def _transcribe_with_gemini(
    audio_path: str,
    gemini_api_key: str,
    language: Optional[str] = None,
) -> str:
    """
    使用 Gemini 2.5 Flash 轉錄音頻。

    < 20 MB: inline bytes 上傳
    >= 20 MB: Files API 上傳

    Args:
        audio_path: 音頻檔路徑
        gemini_api_key: Gemini API key
        language: 語言提示（可選）

    Returns:
        轉錄文字

    Raises:
        ImportError: google-genai 未安裝
        Exception: API 呼叫失敗
    """
    if not _GEMINI_AVAILABLE:
        raise ImportError("google-genai package is not installed")

    client = genai.Client(api_key=gemini_api_key)
    file_size = os.path.getsize(audio_path)
    suffix = Path(audio_path).suffix.lstrip(".")
    mime_type = f"audio/{suffix}" if suffix else "audio/wav"

    prompt = _GEMINI_TRANSCRIBE_PROMPT
    if language:
        prompt += f"\n語言提示: {language}"

    if file_size < _GEMINI_INLINE_LIMIT:
        # Inline upload
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    else:
        # Files API upload for large files
        logger.info("Gemini: file >= 20MB, using Files API upload...")
        uploaded = client.files.upload(file=audio_path)
        audio_part = uploaded

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[audio_part, prompt],
    )
    return _clean_gemini_response(response.text)


def _is_timeout_error(error_str: str) -> bool:
    """判斷錯誤是否為 timeout 相關"""
    timeout_keywords = ["timed out", "timeout", "TimeoutError", "urlopen error"]
    return any(kw.lower() in error_str.lower() for kw in timeout_keywords)


def _is_payload_too_large(error_str: str) -> bool:
    """判斷錯誤是否為 413 Request Entity Too Large"""
    return "413" in error_str or "Request Entity Too Large" in error_str


def _find_ffmpeg() -> Optional[str]:
    """Find ffmpeg binary: PATH → Homebrew → pip-installed packages."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    # pip install imageio-ffmpeg bundles a ffmpeg binary
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return None


def _split_audio_ffmpeg(
    file_path: str,
    max_size_bytes: int = _AI_BUILDER_MAX_FILE_SIZE,
) -> Optional[List[str]]:
    """用 ffmpeg segment 把大檔切成 <= max_size_bytes 的 chunks。

    Returns:
        chunk 檔案路徑 list（放在 tempdir 裡），或 None（ffmpeg 不存在/失敗）。
        呼叫者需自行清理 tempdir。
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None

    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]

    est_duration = estimate_audio_duration(file_path)
    if not est_duration or est_duration <= 0:
        return None

    num_chunks = -(-file_size // max_size_bytes)  # ceil division
    segment_duration = int(est_duration / num_chunks)
    if segment_duration < 10:
        return None

    ext = Path(file_path).suffix
    tmp_dir = tempfile.mkdtemp(prefix="stt_chunks_")
    output_pattern = os.path.join(tmp_dir, f"chunk_%03d{ext}")

    try:
        result = subprocess.run(
            [
                ffmpeg, "-i", file_path,
                "-f", "segment",
                "-segment_time", str(segment_duration),
                "-c", "copy",
                "-y",
                output_pattern,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("ffmpeg split failed: %s", result.stderr[:300])
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        chunks = sorted(str(p) for p in Path(tmp_dir).glob(f"chunk_*{ext}"))
        if not chunks:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        logger.info("Split %s into %d chunks via ffmpeg (segment ~%ds)", file_path, len(chunks), segment_duration)
        return chunks
    except Exception as e:
        logger.warning("Failed to split audio with ffmpeg: %s", e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


def _split_audio_native(
    file_path: str,
    max_size_bytes: int = _AI_BUILDER_MAX_FILE_SIZE,
) -> Optional[List[str]]:
    """macOS fallback: afconvert to WAV + Python wave module split.

    No ffmpeg required. Uses macOS built-in afconvert for format conversion,
    then splits the raw PCM data with Python's wave module.
    """
    afconvert = shutil.which("afconvert") or "/usr/bin/afconvert"
    if not os.path.isfile(afconvert):
        return None

    tmp_dir = tempfile.mkdtemp(prefix="stt_chunks_")
    wav_path = os.path.join(tmp_dir, "converted.wav")

    try:
        # Convert to 16kHz mono 16-bit WAV
        result = subprocess.run(
            [afconvert, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
             file_path, wav_path],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("afconvert failed: %s", result.stderr[:300])
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        # Split WAV by frame count
        with wave.open(wav_path, "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frame_rate = wf.getframerate()
            total_frames = wf.getnframes()
            bytes_per_frame = n_channels * sample_width

            # leave room for 44-byte WAV header
            frames_per_chunk = (max_size_bytes - 44) // bytes_per_frame

            chunks: List[str] = []
            frames_read = 0
            while frames_read < total_frames:
                n = min(frames_per_chunk, total_frames - frames_read)
                data = wf.readframes(n)
                frames_read += n

                chunk_path = os.path.join(tmp_dir, f"chunk_{len(chunks):03d}.wav")
                with wave.open(chunk_path, "wb") as cw:
                    cw.setnchannels(n_channels)
                    cw.setsampwidth(sample_width)
                    cw.setframerate(frame_rate)
                    cw.writeframes(data)
                chunks.append(chunk_path)

        os.unlink(wav_path)

        if not chunks:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        logger.info(
            "Split %s into %d WAV chunks via afconvert (16kHz mono)",
            file_path, len(chunks),
        )
        return chunks
    except Exception as e:
        logger.warning("Native audio split failed: %s", e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


def _split_audio(
    file_path: str,
    max_size_bytes: int = _AI_BUILDER_MAX_FILE_SIZE,
) -> Optional[List[str]]:
    """Split audio, trying ffmpeg first, then macOS native fallback."""
    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]

    chunks = _split_audio_ffmpeg(file_path, max_size_bytes)
    if chunks:
        return chunks

    logger.info("ffmpeg unavailable, trying macOS native split (afconvert)...")
    chunks = _split_audio_native(file_path, max_size_bytes)
    if chunks:
        return chunks

    logger.error(
        "Cannot split audio: install ffmpeg (`pip install imageio-ffmpeg` "
        "or `brew install ffmpeg`) or set GEMINI_API_KEY for large-file fallback"
    )
    return None


def _transcribe_chunked(
    file_path: str,
    api_key: str,
    api_base: str,
    language: Optional[str],
    gemini_api_key: Optional[str],
) -> Optional[TranscriptionResult]:
    """Split a large file into chunks and transcribe each one."""
    chunks = _split_audio(file_path)
    if not chunks:
        return None

    tmp_dir = str(Path(chunks[0]).parent) if chunks[0] != file_path else None
    try:
        texts = []
        for i, chunk_path in enumerate(chunks):
            logger.info("Transcribing chunk %d/%d: %s", i + 1, len(chunks), chunk_path)
            result = transcribe_file_with_retry(
                file_path=chunk_path,
                api_key=api_key,
                api_base=api_base,
                language=language,
                max_retries=1,
                force_long=None,
                gemini_api_key=gemini_api_key,
            )
            if not result.success:
                logger.error("Chunk %d failed: %s", i + 1, result.error)
                return TranscriptionResult(
                    file_path=file_path,
                    success=False,
                    error=f"Chunk {i+1}/{len(chunks)} failed: {result.error}",
                    used_long_endpoint=True,
                )
            texts.append(result.text or "")

        combined = "\n".join(texts)
        logger.info("Chunked transcription succeeded (%d chunks)", len(chunks))
        return TranscriptionResult(
            file_path=file_path,
            success=True,
            text=combined,
            used_long_endpoint=True,
        )
    finally:
        if tmp_dir and tmp_dir != str(Path(file_path).parent):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def transcribe_file_with_retry(
    file_path: str,
    api_key: str,
    api_base: str,
    language: Optional[str] = None,
    max_retries: int = 1,
    force_long: Optional[bool] = None,
    gemini_api_key: Optional[str] = None,
) -> TranscriptionResult:
    """
    Transcribe a single audio file with retry logic.
    自動偵測音頻時長，超過閾值時使用 long transcription endpoint。
    AI Builder 全部重試失敗且錯誤為 timeout 時，自動嘗試 Gemini fallback。

    Args:
        file_path: Path to audio file
        api_key: AI Builder API key
        api_base: AI Builder API base URL
        language: Optional language code
        max_retries: Number of retries on failure (default 1)
        force_long: 強制使用 long endpoint (True) 或短 endpoint (False)。
                    None = 自動依時長判斷。
        gemini_api_key: Optional Gemini API key for fallback transcription

    Returns:
        TranscriptionResult with success status and transcription or error
    """
    # 決定使用哪個 endpoint
    est_duration = estimate_audio_duration(file_path)
    if force_long is not None:
        use_long = force_long
    else:
        use_long = est_duration is not None and est_duration > LONG_AUDIO_DURATION_THRESHOLD

    if use_long:
        logger.info(
            f"Using long transcription for {file_path} (est. duration: {est_duration:.0f}s)"
            if est_duration else f"Using long transcription for {file_path}"
        )

    endpoint = "/v1/audio/transcriptions_long" if use_long else "/v1/audio/transcriptions"

    # Dynamic timeout: scale with file size to avoid write-phase timeouts
    base_timeout = 600 if use_long else 60
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    except OSError:
        file_size_mb = 0
    timeout = max(base_timeout, int(file_size_mb * 30))
    if timeout != base_timeout:
        logger.info(f"Dynamic timeout: {timeout}s (file size: {file_size_mb:.1f}MB)")

    attempts = 0
    last_error = None

    while attempts <= max_retries:
        try:
            attempts += 1
            logger.info(f"Transcribing {file_path} (attempt {attempts}/{max_retries + 1}, endpoint={endpoint})")

            with open(file_path, 'rb') as audio_file:
                audio_bytes = audio_file.read()

            boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
            body = _build_multipart_body(
                boundary=boundary,
                file_path=file_path,
                audio_bytes=audio_bytes,
                language=language,
                is_long=use_long,
            )

            url = f"{api_base}{endpoint}"
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
            logger.debug("AI Builder raw response: %s", raw[:500])
            result = json.loads(raw)

            text = _clean_ai_builder_text(result.get("text", ""))
            logger.info(f"Successfully transcribed {file_path}")

            return TranscriptionResult(
                file_path=file_path,
                success=True,
                text=text,
                error=None,
                duration_seconds=result.get("duration_seconds"),
                used_long_endpoint=use_long,
                sentences=result.get("sentences"),
                speakers=result.get("speakers"),
            )

        except Exception as e:
            last_error = str(e)
            logger.warning(f"Attempt {attempts} failed for {file_path}: {last_error}")

            if _is_payload_too_large(last_error):
                break  # 413 won't resolve with retries

            if attempts > max_retries:
                break

    # 413 fallback: split with ffmpeg then transcribe chunks
    if _is_payload_too_large(last_error or ""):
        logger.info("File too large for API, attempting chunked transcription...")
        chunked = _transcribe_chunked(file_path, api_key, api_base, language, gemini_api_key)
        if chunked is not None:
            return chunked

    # Gemini fallback: on timeout OR 413 (when chunking unavailable)
    should_try_gemini = _is_timeout_error(last_error or "") or _is_payload_too_large(last_error or "")
    if gemini_api_key and _GEMINI_AVAILABLE and should_try_gemini:
        logger.info("Attempting Gemini fallback...")
        try:
            text = _transcribe_with_gemini(file_path, gemini_api_key, language)
            logger.info(f"Gemini fallback succeeded for {file_path}")
            return TranscriptionResult(
                file_path=file_path,
                success=True,
                text=text,
                error=None,
                used_long_endpoint=use_long,
            )
        except Exception as gemini_err:
            logger.warning(f"Gemini fallback also failed for {file_path}: {gemini_err}")
            last_error = f"AI Builder: {last_error}; Gemini: {gemini_err}"

    logger.error(f"Failed to transcribe {file_path} after {attempts} attempts: {last_error}")
    return TranscriptionResult(
        file_path=file_path,
        success=False,
        text=None,
        error=last_error,
        used_long_endpoint=use_long,
    )


def batch_transcribe_directory(
    directory: str,
    api_key: str,
    api_base: str,
    language: Optional[str] = None,
    save_txt: bool = True,
    max_retries: int = 1,
    force_long: Optional[bool] = None,
    gemini_api_key: Optional[str] = None,
) -> List[TranscriptionResult]:
    """
    Transcribe all audio files in a directory.

    Args:
        directory: Path to directory containing audio files
        api_key: AI Builder API key
        api_base: AI Builder API base URL
        language: Optional language code
        save_txt: Whether to save transcriptions as .txt files
        max_retries: Number of retries per file on failure (default 1)
        force_long: 強制使用 long endpoint (True) 或短 endpoint (False)。
                    None = 自動依時長判斷。
        gemini_api_key: Optional Gemini API key for fallback transcription

    Returns:
        List of TranscriptionResult for each file
    """
    audio_files = find_audio_files(directory)

    if not audio_files:
        logger.warning(f"No audio files found in {directory}")
        return []

    logger.info(f"Found {len(audio_files)} audio files to transcribe")
    results = []

    for file_path in audio_files:
        result = transcribe_file_with_retry(
            file_path=file_path,
            api_key=api_key,
            api_base=api_base,
            language=language,
            max_retries=max_retries,
            force_long=force_long,
            gemini_api_key=gemini_api_key,
        )
        results.append(result)

        # Save transcription to .txt file if successful and requested
        if save_txt and result.success and result.text:
            txt_path = Path(file_path).with_suffix('.txt')
            try:
                txt_path.write_text(result.text, encoding='utf-8')
                logger.info(f"Saved transcription to {txt_path}")
            except Exception as e:
                logger.error(f"Failed to save transcription to {txt_path}: {e}")

            # 長音頻額外保存帶時間戳的 JSON 格式
            if result.used_long_endpoint and (result.sentences or result.speakers):
                json_path = Path(file_path).with_suffix('.transcript.json')
                try:
                    structured = {
                        "text": result.text,
                        "duration_seconds": result.duration_seconds,
                    }
                    if result.sentences:
                        structured["sentences"] = result.sentences
                    if result.speakers:
                        structured["speakers"] = result.speakers
                    json_path.write_text(
                        json.dumps(structured, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(f"Saved structured transcript to {json_path}")
                except Exception as e:
                    logger.error(f"Failed to save structured transcript to {json_path}: {e}")

    # Log summary
    successes = sum(1 for r in results if r.success)
    failures = len(results) - successes
    long_count = sum(1 for r in results if r.used_long_endpoint)
    logger.info(
        f"Batch transcription complete: {successes} succeeded, {failures} failed "
        f"({long_count} used long endpoint)"
    )

    return results
