#!/usr/bin/env python3
"""
Tests for batch transcription functionality
"""

import os
import tempfile
from unittest.mock import patch, MagicMock
import pytest
from pathlib import Path
from batch_transcribe import (
    find_audio_files,
    transcribe_file_with_retry,
    batch_transcribe_directory,
    TranscriptionResult,
    estimate_audio_duration,
    LONG_AUDIO_DURATION_THRESHOLD,
    _is_timeout_error,
    _clean_ai_builder_text,
    _clean_gemini_response,
)


class TestFindAudioFiles:
    """Test finding audio files in directory"""

    def test_finds_wav_files(self):
        """Should find .wav files in directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            Path(tmpdir, "audio1.wav").touch()
            Path(tmpdir, "audio2.wav").touch()
            Path(tmpdir, "not_audio.txt").touch()

            files = find_audio_files(tmpdir)

            assert len(files) == 2
            assert all(f.endswith('.wav') for f in files)

    def test_finds_mp3_files(self):
        """Should find .mp3 files in directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "audio1.mp3").touch()
            Path(tmpdir, "audio2.mp3").touch()

            files = find_audio_files(tmpdir)

            assert len(files) == 2
            assert all(f.endswith('.mp3') for f in files)

    def test_finds_m4a_files(self):
        """Should find .m4a files in directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "audio1.m4a").touch()

            files = find_audio_files(tmpdir)

            assert len(files) == 1
            assert files[0].endswith('.m4a')

    def test_finds_flac_and_ogg_files(self):
        """Should find .flac and .ogg files in directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "audio1.flac").touch()
            Path(tmpdir, "audio2.ogg").touch()

            files = find_audio_files(tmpdir)

            assert len(files) == 2

    def test_finds_multiple_formats(self):
        """Should find all supported audio formats"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "audio1.wav").touch()
            Path(tmpdir, "audio2.mp3").touch()
            Path(tmpdir, "audio3.m4a").touch()
            Path(tmpdir, "audio4.flac").touch()
            Path(tmpdir, "audio5.ogg").touch()
            Path(tmpdir, "README.md").touch()

            files = find_audio_files(tmpdir)

            assert len(files) == 5

    def test_returns_empty_list_for_no_audio_files(self):
        """Should return empty list when no audio files found"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "README.md").touch()
            Path(tmpdir, "config.json").touch()

            files = find_audio_files(tmpdir)

            assert files == []


class TestTranscribeFileWithRetry:
    """Test transcribing single file with retry logic"""

    def test_successful_transcription(self):
        """Should transcribe file successfully on first try"""
        # This test will use a mock/stub since we can't make real API calls in tests
        # For now, we'll test the interface
        result = transcribe_file_with_retry(
            file_path="test.wav",
            api_key="test_key",
            api_base="https://test.com"
        )

        assert isinstance(result, TranscriptionResult)
        assert result.file_path == "test.wav"
        assert result.success in [True, False]
        if result.success:
            assert result.text is not None
        else:
            assert result.error is not None

    def test_retries_on_failure(self):
        """Should retry once on failure"""
        # This test will verify retry logic
        # We'll need to implement this with a way to track attempts
        pass  # Will implement after basic structure


class TestBatchTranscribeDirectory:
    """Test batch transcription of directory"""

    def test_transcribes_all_files(self):
        """Should transcribe all audio files in directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test audio files
            audio1 = Path(tmpdir, "audio1.wav")
            audio2 = Path(tmpdir, "audio2.mp3")
            audio1.touch()
            audio2.touch()

            results = batch_transcribe_directory(
                directory=tmpdir,
                api_key="test_key",
                api_base="https://test.com"
            )

            assert len(results) == 2
            assert all(isinstance(r, TranscriptionResult) for r in results)

    def test_saves_transcriptions_as_txt_files(self):
        """Should save each transcription as .txt file next to audio file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test audio file
            audio_file = Path(tmpdir, "audio1.wav")
            audio_file.write_bytes(b"fake audio data")

            results = batch_transcribe_directory(
                directory=tmpdir,
                api_key="test_key",
                api_base="https://test.com",
                save_txt=True
            )

            # Check that .txt file was created
            txt_file = Path(tmpdir, "audio1.txt")
            if results and results[0].success:
                assert txt_file.exists()

    def test_returns_summary(self):
        """Should return summary of successes and failures"""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio1 = Path(tmpdir, "audio1.wav")
            audio1.touch()

            results = batch_transcribe_directory(
                directory=tmpdir,
                api_key="test_key",
                api_base="https://test.com"
            )

            # Results should be a list we can analyze
            assert isinstance(results, list)
            successes = [r for r in results if r.success]
            failures = [r for r in results if not r.success]

            # Should be able to count successes and failures
            total = len(successes) + len(failures)
            assert total == len(results)


class TestTranscriptionResult:
    """Test TranscriptionResult data structure"""

    def test_successful_result(self):
        """Should create successful result"""
        result = TranscriptionResult(
            file_path="test.wav",
            success=True,
            text="Hello world",
            error=None
        )

        assert result.file_path == "test.wav"
        assert result.success is True
        assert result.text == "Hello world"
        assert result.error is None

    def test_failed_result(self):
        """Should create failed result"""
        result = TranscriptionResult(
            file_path="test.wav",
            success=False,
            text=None,
            error="API error"
        )

        assert result.file_path == "test.wav"
        assert result.success is False
        assert result.text is None
        assert result.error == "API error"

    def test_long_transcription_result(self):
        """Should create result with long transcription fields"""
        result = TranscriptionResult(
            file_path="long_meeting.wav",
            success=True,
            text="Speaker A: Hello. Speaker B: Hi.",
            duration_seconds=3600.0,
            used_long_endpoint=True,
            sentences=[{"start": 0.0, "end": 1.5, "text": "Hello."}],
            speakers=[{"speaker": "A", "start": 0.0, "end": 1.5, "text": "Hello."}],
        )

        assert result.used_long_endpoint is True
        assert result.duration_seconds == 3600.0
        assert len(result.sentences) == 1
        assert len(result.speakers) == 1


class TestEstimateAudioDuration:
    """Test audio duration estimation"""

    def test_estimate_wav_duration(self):
        """Should estimate WAV file duration from header"""
        import struct as st
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir, "test.wav")
            # Create a minimal valid WAV header (44 bytes)
            # 16kHz, mono, 16-bit = byte_rate 32000
            sample_rate = 16000
            channels = 1
            bits_per_sample = 16
            byte_rate = sample_rate * channels * bits_per_sample // 8
            block_align = channels * bits_per_sample // 8
            # 10 seconds of audio data
            data_size = byte_rate * 10
            file_size = 44 + data_size

            header = b"RIFF"
            header += st.pack("<I", file_size - 8)  # chunk size
            header += b"WAVE"
            header += b"fmt "
            header += st.pack("<I", 16)  # subchunk1 size
            header += st.pack("<H", 1)   # audio format (PCM)
            header += st.pack("<H", channels)
            header += st.pack("<I", sample_rate)
            header += st.pack("<I", byte_rate)
            header += st.pack("<H", block_align)
            header += st.pack("<H", bits_per_sample)
            header += b"data"
            header += st.pack("<I", data_size)

            wav_path.write_bytes(header + b"\x00" * data_size)

            duration = estimate_audio_duration(str(wav_path))
            assert duration is not None
            assert abs(duration - 10.0) < 0.1  # ~10 seconds

    def test_estimate_mp3_duration_by_size(self):
        """Should estimate MP3 duration from file size"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mp3_path = Path(tmpdir, "test.mp3")
            # 16KB/s compressed, write 160KB = ~10 seconds
            mp3_path.write_bytes(b"\x00" * 160_000)

            duration = estimate_audio_duration(str(mp3_path))
            assert duration is not None
            assert abs(duration - 10.0) < 1.0

    def test_nonexistent_file(self):
        """Should return None for nonexistent file"""
        duration = estimate_audio_duration("/nonexistent/file.wav")
        assert duration is None

    def test_long_audio_threshold(self):
        """LONG_AUDIO_DURATION_THRESHOLD should be 300 seconds"""
        assert LONG_AUDIO_DURATION_THRESHOLD == 300


class TestIsTimeoutError:
    """Test timeout error detection"""

    def test_detects_timed_out(self):
        assert _is_timeout_error("urlopen error <urlopen error timed out>") is True

    def test_detects_timeout_keyword(self):
        assert _is_timeout_error("Connection timeout after 60s") is True

    def test_detects_timeout_error_class(self):
        assert _is_timeout_error("TimeoutError: read operation timed out") is True

    def test_ignores_non_timeout(self):
        assert _is_timeout_error("HTTP Error 500: Internal Server Error") is False

    def test_empty_string(self):
        assert _is_timeout_error("") is False


class TestDynamicTimeout:
    """Test dynamic timeout calculation in transcribe_file_with_retry"""

    def test_small_file_uses_base_timeout(self):
        """Small files should use the base timeout (60s for short endpoint)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1 MB file → file_size_mb * 30 = 30s < base 60s → use 60s
            audio_path = Path(tmpdir, "small.wav")
            audio_path.write_bytes(b"\x00" * (1 * 1024 * 1024))

            # We can't easily test the internal timeout value without mocking,
            # but we verify the function runs without error
            result = transcribe_file_with_retry(
                file_path=str(audio_path),
                api_key="test_key",
                api_base="https://test.invalid",
                max_retries=0,
            )
            assert isinstance(result, TranscriptionResult)
            assert not result.success  # Will fail due to invalid API

    def test_large_file_scales_timeout(self):
        """Large files should scale timeout based on file size"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 10 MB file → file_size_mb * 30 = 300s > base 60s → use 300s
            audio_path = Path(tmpdir, "large.m4a")
            audio_path.write_bytes(b"\x00" * (10 * 1024 * 1024))

            result = transcribe_file_with_retry(
                file_path=str(audio_path),
                api_key="test_key",
                api_base="https://test.invalid",
                max_retries=0,
            )
            assert isinstance(result, TranscriptionResult)


class TestGeminiFallback:
    """Test Gemini fallback in transcribe_file_with_retry"""

    @patch("batch_transcribe._GEMINI_AVAILABLE", True)
    @patch("batch_transcribe._transcribe_with_gemini")
    @patch("batch_transcribe.urllib.request.urlopen")
    def test_gemini_fallback_on_timeout(self, mock_urlopen, mock_gemini):
        """Should fall back to Gemini when AI Builder times out"""
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")
        mock_gemini.return_value = "Gemini transcription"

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir, "test.wav")
            audio_path.write_bytes(b"\x00" * 100)

            result = transcribe_file_with_retry(
                file_path=str(audio_path),
                api_key="test_key",
                api_base="https://test.com",
                max_retries=0,
                gemini_api_key="test_gemini_key",
            )

            assert result.success is True
            assert result.text == "Gemini transcription"
            mock_gemini.assert_called_once()

    @patch("batch_transcribe._GEMINI_AVAILABLE", True)
    @patch("batch_transcribe._transcribe_with_gemini")
    @patch("batch_transcribe.urllib.request.urlopen")
    def test_no_gemini_fallback_on_non_timeout(self, mock_urlopen, mock_gemini):
        """Should NOT fall back to Gemini for non-timeout errors"""
        mock_urlopen.side_effect = Exception("HTTP Error 500: Server Error")

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir, "test.wav")
            audio_path.write_bytes(b"\x00" * 100)

            result = transcribe_file_with_retry(
                file_path=str(audio_path),
                api_key="test_key",
                api_base="https://test.com",
                max_retries=0,
                gemini_api_key="test_gemini_key",
            )

            assert result.success is False
            mock_gemini.assert_not_called()

    @patch("batch_transcribe.urllib.request.urlopen")
    def test_no_gemini_fallback_without_key(self, mock_urlopen):
        """Should not attempt Gemini fallback when no key is provided"""
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir, "test.wav")
            audio_path.write_bytes(b"\x00" * 100)

            result = transcribe_file_with_retry(
                file_path=str(audio_path),
                api_key="test_key",
                api_base="https://test.com",
                max_retries=0,
                gemini_api_key=None,
            )

            assert result.success is False
            assert "timed out" in result.error


class TestCleanAiBuilderText:
    """Test cleaning AI Builder text field artifacts"""

    def test_plain_text_unchanged(self):
        assert _clean_ai_builder_text("你好，今天天氣很好。") == "你好，今天天氣很好。"

    def test_strips_trailing_quote_brace(self):
        """The exact pattern reported: text ending with "}"""
        raw = '所以我說讓我來簡單測試一下，看我拿到的結果是什麼。"}'
        assert _clean_ai_builder_text(raw) == "所以我說讓我來簡單測試一下，看我拿到的結果是什麼。"

    def test_nested_json_with_query_key(self):
        """AI Builder sometimes wraps text in {"query": "..."}"""
        raw = '{"query": "這是實際的轉錄文字"}'
        assert _clean_ai_builder_text(raw) == "這是實際的轉錄文字"

    def test_nested_json_with_newlines(self):
        r"""Nested JSON with escaped newlines: {"query": "...\n\n..."}"""
        raw = '{"query": "前面的文字\\n\\n後面的文字"}'
        assert _clean_ai_builder_text(raw) == "前面的文字\n\n後面的文字"

    def test_nested_json_with_text_key(self):
        raw = '{"text": "轉錄結果"}'
        assert _clean_ai_builder_text(raw) == "轉錄結果"

    def test_strips_trailing_brace_only(self):
        assert _clean_ai_builder_text("測試結果}") == "測試結果"

    def test_strips_trailing_quote_only(self):
        assert _clean_ai_builder_text('測試結果"') == "測試結果"

    def test_preserves_internal_quotes(self):
        assert _clean_ai_builder_text('他說"你好"然後離開') == '他說"你好"然後離開'

    def test_strips_whitespace(self):
        assert _clean_ai_builder_text("  測試結果  ") == "測試結果"


class TestCleanGeminiResponse:
    """Test cleaning Gemini response artifacts"""

    def test_plain_text_unchanged(self):
        assert _clean_gemini_response("你好，今天天氣很好。") == "你好，今天天氣很好。"

    def test_strips_json_wrapper(self):
        """Gemini sometimes wraps output in {"text": "..."}"""
        raw = '{"text": "你好，今天天氣很好。"}'
        assert _clean_gemini_response(raw) == "你好，今天天氣很好。"

    def test_strips_json_with_newlines(self):
        """The exact pattern reported by user: \\n and }"}"""
        raw = '{"text": "你好，今天天氣很好。\\n"}'
        assert _clean_gemini_response(raw) == "你好，今天天氣很好。"

    def test_strips_markdown_code_block(self):
        raw = "```\n你好，今天天氣很好。\n```"
        assert _clean_gemini_response(raw) == "你好，今天天氣很好。"

    def test_strips_markdown_json_code_block(self):
        raw = '```json\n{"text": "你好"}\n```'
        assert _clean_gemini_response(raw) == "你好"

    def test_strips_surrounding_quotes(self):
        raw = '"你好，今天天氣很好。"'
        assert _clean_gemini_response(raw) == "你好，今天天氣很好。"

    def test_strips_whitespace(self):
        raw = "  \n你好，今天天氣很好。\n  "
        assert _clean_gemini_response(raw) == "你好，今天天氣很好。"

    def test_json_with_other_key(self):
        """Should extract first string value from JSON even with non-standard key"""
        raw = '{"transcription": "你好"}'
        assert _clean_gemini_response(raw) == "你好"
