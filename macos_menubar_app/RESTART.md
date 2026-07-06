# Restart the menubar app to load the new toggle

The "即時轉錄一律走 OpenAI" toggle is in the working tree but the running
process (started before the edit) hasn't loaded it. rumps builds the menu once
at launch; Python doesn't hot-reload source. Restart to pick up the change.

```bash
# Stop the running instance
pkill -f speech_to_clipboard.py

# Relaunch from the app directory (must be a shell that has OPENAI_API_KEY,
# e.g. one that sources ~/.zshrc — otherwise the toggle is hidden)
cd /Users/shirley/arealclimber/speech-to-action/macos_menubar_app
python speech_to_clipboard.py
```

After relaunch: menubar 🎤 → 設定 → you should see "✓ 即時轉錄一律走 OpenAI".
The ✓ means it's already ON (default).
```
