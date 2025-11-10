# Quick Start

Get running in 2 minutes.

## Setup

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set API key
export OPENAI_API_KEY='your-openai-api-key'

# 4. Run app
python3 speech_to_clipboard.py
```

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

## Troubleshooting

**No auto-paste?**

- Check Accessibility permission granted
- Ensure auto-paste enabled in Settings
- Click in input field before recording

**No menubar icon?**

- Check `OPENAI_API_KEY` is set
- Run `python3 speech_to_clipboard.py` in terminal to see errors

**Recording doesn't start?**

- Check Microphone permission granted
- Test with `python3 test_auto_paste.py`
