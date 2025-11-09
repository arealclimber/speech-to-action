# Speech to Action

這個專案包含兩個語音轉文字應用：

## 📱 專案組成

### 1. Brainwave - Web 版語音轉文字工具

基於 Web 的即時語音識別和摘要工具，使用 OpenAI Realtime API。

- 📁 位置: `brainwave/`
- 📖 文檔: [brainwave/README.md](brainwave/README.md)
- ✨ 特色:
  - 即時語音轉文字
  - 智能摘要功能
  - 多語言支持
  - Web 界面

### 2. macOS 狀態列應用 - 語音轉剪貼板

macOS 原生狀態列應用，隨時可用的語音轉文字工具。

- 📁 位置: `macos_menubar_app/`
- 📖 文檔: [macos_menubar_app/README.md](macos_menubar_app/README.md)
- ✨ 特色:
  - 🎤 狀態列快速訪問
  - 📋 自動複製到剪貼板
  - ⌨️ 快捷鍵支持 (⌘R)
  - 🌍 多語言支持
  - 📝 歷史記錄

## 🚀 快速開始

### Brainwave (Web 版)

```bash
cd brainwave
pip install -r requirements.txt
export OPENAI_API_KEY='your-api-key'
uvicorn realtime_server:app --host 0.0.0.0 --port 3005
```

訪問 http://localhost:3005

### macOS 狀態列應用

```bash
cd macos_menubar_app
./install.sh
./run.sh
```

## 📋 系統要求

### Brainwave
- Python 3.8+
- 現代瀏覽器
- OpenAI API Key

### macOS 狀態列應用
- macOS 10.14+
- Python 3.8+
- OpenAI API Key

## 🛠️ 技術棧

### Brainwave
- FastAPI
- WebSocket
- OpenAI Realtime API
- Web Audio API

### macOS 狀態列應用
- rumps (macOS 狀態列框架)
- OpenAI Whisper API
- sounddevice (音頻錄製)
- pyperclip (剪貼板操作)

## 📖 詳細文檔

- [Brainwave 完整文檔](brainwave/README.md)
- [macOS 應用完整文檔](macos_menubar_app/README.md)

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

## 📄 授權

MIT License

## 🙏 致謝

- OpenAI Whisper & Realtime API
- rumps - macOS 狀態列應用框架
- FastAPI - 現代 Web 框架

---

**2025 AI FUNkathon 專案**
