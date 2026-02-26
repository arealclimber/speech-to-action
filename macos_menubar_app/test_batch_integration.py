#!/usr/bin/env python3
"""
Integration test for batch transcription
This script tests the batch transcription with actual files
"""

import os
import tempfile
from pathlib import Path
from batch_transcribe import batch_transcribe_directory, find_audio_files
from speech_to_clipboard import get_ai_builder_api_key


def test_batch_with_empty_directory():
    """Test with empty directory"""
    print("Test 1: Empty directory")
    with tempfile.TemporaryDirectory() as tmpdir:
        files = find_audio_files(tmpdir)
        print(f"  Found {len(files)} files (expected: 0)")
        assert len(files) == 0, "Should find no files in empty directory"
    print("  ✓ Passed\n")


def test_batch_find_files():
    """Test finding audio files"""
    print("Test 2: Find audio files")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        Path(tmpdir, "test1.wav").touch()
        Path(tmpdir, "test2.mp3").touch()
        Path(tmpdir, "test3.m4a").touch()
        Path(tmpdir, "readme.txt").touch()

        files = find_audio_files(tmpdir)
        print(f"  Found {len(files)} files (expected: 3)")
        assert len(files) == 3, f"Should find 3 audio files, found {len(files)}"

        extensions = [Path(f).suffix for f in files]
        print(f"  Extensions: {extensions}")
        assert '.wav' in extensions
        assert '.mp3' in extensions
        assert '.m4a' in extensions
    print("  ✓ Passed\n")


def test_api_key_detection():
    """Test API key detection"""
    print("Test 3: API key detection")
    api_key = get_ai_builder_api_key()

    if api_key:
        print(f"  ✓ AI Builder API key found (length: {len(api_key)})")
    else:
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            print(f"  ✓ OpenAI API key found (length: {len(openai_key)})")
        else:
            print("  ✗ No API key found")
            print("  Please set AI_BUILDER_API_KEY or OPENAI_API_KEY")
            return False
    print()
    return True


def main():
    """Run integration tests"""
    print("=" * 60)
    print("Batch Transcription Integration Tests")
    print("=" * 60)
    print()

    try:
        test_batch_with_empty_directory()
        test_batch_find_files()
        has_api_key = test_api_key_detection()

        print("=" * 60)
        print("Summary:")
        print("  Basic functionality: ✓ All tests passed")
        if has_api_key:
            print("  API configuration: ✓ API key detected")
            print()
            print("To test actual transcription:")
            print("  1. Run the app: python3 speech_to_clipboard.py")
            print("  2. Click menubar icon → 批次轉錄...")
            print("  3. Enter a directory path with audio files")
            print("  4. Check that .txt files are created")
        else:
            print("  API configuration: ✗ No API key found")
            print()
            print("Set up API key before testing transcription:")
            print("  export AI_BUILDER_API_KEY='your-key'")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
