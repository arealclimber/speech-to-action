# Quick Start

Get running in 2 minutes.

## Setup

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set API key (choose one)

# Option A: OpenAI Whisper
export OPENAI_API_KEY='your-openai-api-key'

# Option B: AI Builder transcription (add to ~/.zshrc to persist)
export AI_BUILDER_API_KEY='your-ai-builder-api-key'
# Or add to ~/.zshrc:
#   export AI_BUILDER_API_KEY='your-ai-builder-api-key'

# 4. Run app
python3 speech_to_clipboard.py
```

If `AI_BUILDER_API_KEY` is set (environment variable or in `~/.zshrc`), the app uses **AI Builder** transcription (`https://space.ai-builders.com/backend/v1/audio/transcriptions`); otherwise it uses **OpenAI** Whisper.

## First Use

1. **Grant permissions** when prompted:

   - Microphone (required)
   - Accessibility (for global hotkey + auto-paste)

   Or manually: System Preferences → Security & Privacy → Privacy

2. **Look for 🎤** in menubar (top right)

3. **Test it**:
   - Press `⌃⌥A` anywhere
   - Speak into microphone
   - Press `⌃⌥A` to stop
   - Text appears in focused app

### Terminal Commands

1. Focus Terminal
2. Press `⌃⌥A` → speak command → `⌃⌥A`
3. Command appears in terminal

### Batch Transcription

Process multiple audio files at once:

1. Click menubar icon 🎤 → **批次轉錄...** (Batch Transcribe...)
2. Enter directory path containing audio files (supports .wav, .mp3, .m4a)
   - Default: `~/Downloads/recordings`
3. App will:
   - Transcribe all audio files
   - Save each transcription as .txt file next to the audio file
   - Copy all transcriptions to clipboard
   - Show summary notification

**Example:**
```
Directory: ~/Downloads/recordings
Files: audio1.wav, audio2.mp3, audio3.m4a

Results:
- audio1.txt (transcription)
- audio2.txt (transcription)
- audio3.txt (transcription)
- All transcriptions copied to clipboard
```

**Features:**
- Automatic retry on failure (1 retry per file)
- Traditional Chinese output (simplified → traditional conversion)
- Progress notifications
- Error handling (continues on individual file failures)

## Troubleshooting

**No auto-paste?**

- Check Accessibility permission granted
- Ensure auto-paste enabled in Settings
- Click in input field before recording

**No menubar icon?**

- Set at least one of `OPENAI_API_KEY` or `AI_BUILDER_API_KEY` (e.g. in `~/.zshrc`)
- Run `python3 speech_to_clipboard.py` in terminal to see errors

**Recording doesn't start?**

- Check Microphone permission granted
- Test with `python3 test_auto_paste.py`
