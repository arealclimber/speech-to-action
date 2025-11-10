# Speech-to-Action

macOS menubar app for voice-to-text with OpenAI Whisper API.

Press `⌃⌥R` anywhere to transcribe speech into focused app.

## Demo

## Quick Start

Run the python in background:

```bash
git clone https://github.com/arealclimber/speech-to-action.git
cd macos_menubar_app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY='your-openai-api-key'
python3 speech_to_clipboard.py
```

## Features

- **Global hotkey** (`⌃⌥R`) - Start/stop recording from anywhere
- **Auto-paste** - Text appears in focused app automatically
- **Multi-language** - Auto-detect or specify language

## Requirements

- macOS 10.14+
- Python 3.8+
- OpenAI API key from [platform.openai.com](https://platform.openai.com/api-keys)

## Documentation

- [README](macos_menubar_app/README.md) - Full documentation
- [Quick Start](macos_menubar_app/QUICKSTART.md) - 2-minute setup guide

## Tech Stack

- OpenAI Whisper API (speech-to-text)
- rumps (menubar framework)
- sounddevice (audio recording)
- pynput (global hotkey)
- pyperclip (clipboard)
