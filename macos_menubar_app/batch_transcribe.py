#!/usr/bin/env python3
"""
Batch transcription functionality for processing multiple audio files
"""

import os
import json
import struct
import urllib.request
import urllib.error
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# 超過此秒數的音頻自動使用 long transcription endpoint
LONG_AUDIO_DURATION_THRESHOLD = 300  # 5 分鐘

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


def transcribe_file_with_retry(
    file_path: str,
    api_key: str,
    api_base: str,
    language: Optional[str] = None,
    max_retries: int = 1,
    force_long: Optional[bool] = None,
) -> TranscriptionResult:
    """
    Transcribe a single audio file with retry logic.
    自動偵測音頻時長，超過閾值時使用 long transcription endpoint。

    Args:
        file_path: Path to audio file
        api_key: AI Builder API key
        api_base: AI Builder API base URL
        language: Optional language code
        max_retries: Number of retries on failure (default 1)
        force_long: 強制使用 long endpoint (True) 或短 endpoint (False)。
                    None = 自動依時長判斷。

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
    timeout = 600 if use_long else 60  # 長音頻給 10 分鐘 timeout

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
                result = json.loads(resp.read().decode())

            text = result.get("text", "").strip()
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

            if attempts > max_retries:
                break

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
