# macOS 語音轉文字狀態列應用

一個簡單易用的 macOS 狀態列應用，讓您可以隨時使用語音輸入，自動轉換為文字並複製到剪貼板。

<img width="300" alt="應用示意圖" src="https://img.shields.io/badge/macOS-Status%20Bar%20App-blue">

## ✨ 功能特色

- 🎤 **狀態列快速訪問** - 始終顯示在 macOS 狀態列，隨時可用
- 🗣️ **語音轉文字** - 使用 OpenAI Whisper API 進行高精度語音識別
- 📋 **自動複製** - 轉換完成後自動複製到系統剪貼板
- ✨ **自動粘貼** - 自動粘貼到當前焦點應用（支持 Slack、Notes、Terminal 等所有應用）
- ⚡ **全局快捷鍵** - 🆕 按 `⌃⌥R` 隨時開始錄音，無需點擊菜單！
- ⌨️ **快捷鍵支持** - 使用 `⌘R` 開始/停止錄音（打開菜單後）
- 🌍 **多語言支持** - 支持中文、英文、日文等多種語言
- 📝 **歷史記錄** - 保存最近 5 條轉換結果，方便查看和復制

## 📋 文檔索引

- **[README.md](README.md)** - 開發者文檔（本文件）
- **[QUICKSTART.md](QUICKSTART.md)** - ⚡ 5 分鐘快速開始
- **[GLOBAL_HOTKEY_GUIDE.md](GLOBAL_HOTKEY_GUIDE.md)** - 🆕 全局快捷鍵完整指南
- **[AUTO_PASTE_GUIDE.md](AUTO_PASTE_GUIDE.md)** - 自動粘貼功能完整指南
- **[USER_GUIDE.md](USER_GUIDE.md)** - 用戶使用指南（分享給最終用戶）
- **[DISTRIBUTION.md](DISTRIBUTION.md)** - 應用分發指南（打包和分發）
- **[NATIVE_SWIFT_OPTION.md](NATIVE_SWIFT_OPTION.md)** - 原生 Swift 應用選項

## 🚀 快速開始

### 系統要求

- macOS 10.14 或更高版本
- Python 3.8 或更高版本
- 有效的 OpenAI API Key

### 開發者安裝步驟

1. **克隆或下載此專案**

```bash
cd macos_menubar_app
```

2. **創建虛擬環境（推薦）**

```bash
python3 -m venv venv
source venv/bin/activate
```

3. **安裝依賴**

```bash
pip install -r requirements.txt
```

4. **設置 OpenAI API Key**

```bash
export OPENAI_API_KEY='your-api-key-here'
```

> 💡 建議將此命令添加到您的 `~/.zshrc` 或 `~/.bash_profile` 中，以便自動加載

5. **運行應用**

```bash
python3 speech_to_clipboard.py
```

## 📖 使用方法

### 基本使用

1. **啟動應用** - 運行 `python3 speech_to_clipboard.py`，您會在狀態列看到 🎤 圖標
2. **開始錄音** - 點擊狀態列圖標，選擇「開始錄音」或使用快捷鍵 ⌘R
3. **說話** - 對著麥克風說話，狀態列圖標會變成紅色 🔴
4. **停止錄音** - 再次點擊「停止錄音」或按 ⌘R
5. **自動複製** - 轉換完成後，文字會自動複製到剪貼板，並顯示通知

### 快捷鍵

- `⌘R` - 開始/停止錄音

### 菜單功能

- **開始錄音** - 開始語音錄製
- **錄音中...** - 顯示當前錄音狀態
- **最近結果** - 查看和復制最近 5 條轉換結果
- **設定** - 配置語言等選項
  - 語言設定：可設置特定語言（zh, en, ja）或自動偵測
- **關於** - 顯示應用信息
- **退出** - 關閉應用

## ⚙️ 配置

### 語言設定

默認情況下，應用會自動偵測語言。您也可以手動設置：

1. 點擊狀態列圖標
2. 選擇「設定」→「語言: 自動偵測」
3. 輸入語言代碼（例如：`zh` 中文，`en` 英文，`ja` 日文）

### 環境變量

```bash
# OpenAI API Key（必需）
export OPENAI_API_KEY='your-api-key-here'
```

## 🔧 進階設置

### 作為後台服務運行

如果您想讓應用在登錄時自動啟動，可以創建一個 Launch Agent：

1. 創建 plist 文件：

```bash
mkdir -p ~/Library/LaunchAgents
nano ~/Library/LaunchAgents/com.speech-to-clipboard.plist
```

2. 添加以下內容（記得修改路徑）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.speech-to-clipboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/python3</string>
        <string>/path/to/speech_to_clipboard.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENAI_API_KEY</key>
        <string>your-api-key-here</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

3. 加載 Launch Agent：

```bash
launchctl load ~/Library/LaunchAgents/com.speech-to-clipboard.plist
```

### 打包為獨立應用（可選）

使用 `py2app` 將 Python 腳本打包為 macOS 應用：

```bash
pip install py2app
python3 setup.py py2app
```

## 🛠️ 技術架構

- **rumps** - macOS 狀態列應用框架
- **sounddevice** - 音頻錄製
- **OpenAI Whisper API** - 語音轉文字
- **pyperclip** - 剪貼板操作
- **NumPy & SciPy** - 音頻處理

## 📋 依賴項

```
rumps>=0.4.0
pyobjc-framework-Cocoa>=10.0
sounddevice>=0.4.6
numpy>=1.24.0
openai>=1.0.0
pyperclip>=1.8.2
scipy>=1.11.0
```

## ❓ 常見問題

### Q: 應用無法訪問麥克風？

A: 請在「系統偏好設置」→「安全性與隱私」→「麥克風」中授予 Python/Terminal 訪問權限。

### Q: 轉換速度慢？

A: 轉換速度取決於網絡速度和音頻長度。建議每次錄音不超過 30 秒。

### Q: 支持哪些語言？

A: 支持 Whisper API 的所有語言，包括中文、英文、日文、韓文、法文、德文、西班牙文等 100+ 種語言。

### Q: 如何獲取 OpenAI API Key？

A: 訪問 [OpenAI 平台](https://platform.openai.com/api-keys) 註冊並創建 API Key。

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

## 📄 授權

MIT License

## 🙏 致謝

- [OpenAI Whisper](https://openai.com/research/whisper) - 語音識別 API
- [rumps](https://github.com/jaredks/rumps) - macOS 狀態列應用框架

---

## 📦 打包和分發

### 為其他用戶打包

如果您想將應用分享給其他用戶使用：

```bash
# 使用自動打包腳本
./build.sh
```

這會創建一個獨立的 .app 文件在 `dist/` 目錄中。

詳細的打包和分發指南請查看：
- **[DISTRIBUTION.md](DISTRIBUTION.md)** - 完整的打包、簽名、公證和分發指南
- **[USER_GUIDE.md](USER_GUIDE.md)** - 用戶安裝和使用指南

### 應用分發選項

1. **py2app 打包**（當前方案）
   - ✅ 快速簡單
   - ✅ 適合內部使用
   - ⚠️ 應用體積較大（50-100 MB）
   - ⚠️ 未簽名需手動允許

2. **原生 Swift 應用**（專業方案）
   - ✅ 體積小（5-10 MB）
   - ✅ 啟動快速
   - ✅ 可上架 App Store
   - ⚠️ 需額外開發時間

   詳見：**[NATIVE_SWIFT_OPTION.md](NATIVE_SWIFT_OPTION.md)**

## 🎯 適用場景

### 當前 Python 版本適合：
- ✅ 內部團隊使用
- ✅ 快速原型驗證
- ✅ 小範圍分發（<100 用戶）
- ✅ 開發和測試

### 建議使用原生 Swift 版本如果：
- 📱 需要公開發布
- 📱 預期大量用戶
- 📱 需要上架 App Store
- 📱 看重性能和用戶體驗

如有問題或建議，請隨時聯繫！
