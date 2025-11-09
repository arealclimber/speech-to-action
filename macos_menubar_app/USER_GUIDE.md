# 用戶使用指南

簡單易懂的安裝和使用說明，適合分享給最終用戶。

---

## 📥 下載和安裝

### 方式 1：使用打包好的應用（推薦）

1. **下載應用**
   - 從分享連結下載 `Speech-to-Clipboard.zip`
   - 解壓縮文件

2. **安裝應用**
   - 將 `Speech to Clipboard.app` 拖到「應用程式」文件夾
   - 或直接雙擊運行

3. **首次運行設置**

   首次打開時，macOS 可能會顯示安全警告：

   **方式 A**: 右鍵點擊應用，選擇「打開」

   **方式 B**:
   - 打開「系統偏好設置」
   - 進入「安全性與隱私」
   - 在「一般」標籤頁底部點擊「仍要打開」

4. **設置 OpenAI API Key**

   打開「終端」應用，執行以下命令：

   ```bash
   # 設置 API Key
   echo 'export OPENAI_API_KEY="你的-API-Key"' >> ~/.zshrc

   # 使配置生效
   source ~/.zshrc
   ```

   > 💡 如何獲取 API Key？訪問 [OpenAI 平台](https://platform.openai.com/api-keys)

5. **重新啟動應用**
   - 退出並重新打開應用
   - 狀態列應該會出現 🎤 圖標

### 方式 2：從源代碼安裝（開發者）

如果您收到的是源代碼：

```bash
# 進入應用目錄
cd macos_menubar_app

# 運行安裝腳本
./install.sh

# 啟動應用
./run.sh
```

---

## 🎙️ 使用方法

### 基本操作

1. **開始錄音**
   - 點擊狀態列的 🎤 圖標
   - 選擇「開始錄音 (⌘R)」
   - 或直接按快捷鍵 `⌘R`

2. **錄製語音**
   - 圖標變為紅色 🔴 表示正在錄音
   - 對著麥克風清晰地說話

3. **停止錄音**
   - 再次點擊「停止錄音 (⌘R)」
   - 或按 `⌘R`

4. **獲取結果**
   - 等待幾秒鐘進行轉換
   - 轉換完成後會收到系統通知
   - 文字已自動複製到剪貼板
   - 直接在任何地方按 `⌘V` 貼上

### 快捷鍵

- `⌘R` - 開始/停止錄音

### 查看歷史記錄

1. 點擊狀態列圖標
2. 選擇「最近結果」
3. 點擊任意歷史項目可重新複製到剪貼板

### 設置選項

#### 更改語言

1. 點擊狀態列圖標
2. 選擇「設定」→「語言: 自動偵測」
3. 輸入語言代碼：
   - `zh` - 中文
   - `en` - 英文
   - `ja` - 日文
   - `ko` - 韓文
   - 留空 - 自動偵測

---

## 🔧 進階設置

### 開機自動啟動

#### 方式 1：系統偏好設置（簡單）

1. 打開「系統偏好設置」
2. 進入「使用者與群組」
3. 選擇「登入項目」
4. 點擊 `+` 按鈕
5. 選擇「Speech to Clipboard.app」
6. 勾選「隱藏」（可選）

#### 方式 2：Launch Agent（進階）

創建啟動配置文件：

```bash
# 創建 plist 文件
nano ~/Library/LaunchAgents/com.speech-to-clipboard.plist
```

添加以下內容（記得修改路徑和 API Key）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.speech-to-clipboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/Speech to Clipboard.app/Contents/MacOS/Speech to Clipboard</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENAI_API_KEY</key>
        <string>你的-API-Key</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

加載配置：

```bash
launchctl load ~/Library/LaunchAgents/com.speech-to-clipboard.plist
```

### 更新 API Key

如果需要更改 API Key：

```bash
# 編輯配置文件
nano ~/.zshrc

# 找到並修改這一行
export OPENAI_API_KEY="新的-API-Key"

# 保存並生效
source ~/.zshrc

# 重啟應用
```

---

## ❓ 常見問題

### Q: 點擊應用沒有反應？

**A**: 可能是權限問題。請檢查：
1. 「系統偏好設置」→「安全性與隱私」→「麥克風」
2. 確保「Terminal」或應用本身有麥克風權限
3. 如果沒有，勾選啟用

### Q: 顯示「未設置 OPENAI_API_KEY」錯誤？

**A**: 需要設置 API Key：
```bash
echo 'export OPENAI_API_KEY="你的-API-Key"' >> ~/.zshrc
source ~/.zshrc
```
然後重啟應用。

### Q: 語音識別不準確？

**A**: 嘗試以下方法：
- 確保環境安靜
- 靠近麥克風清晰說話
- 在設定中指定正確的語言代碼
- 使用高質量的麥克風

### Q: 應用使用流量和費用？

**A**:
- 應用使用 OpenAI Whisper API
- 費用：約 $0.006/分鐘（1 分鐘音頻 = 0.6 美分）
- 計費方式：按使用量計費
- 可在 [OpenAI 使用面板](https://platform.openai.com/usage) 查看

### Q: 支持哪些語言？

**A**: 支持 100+ 種語言，包括：
- 中文（簡體/繁體）
- 英語
- 日語
- 韓語
- 法語
- 德語
- 西班牙語
- 等等...

完整列表見 [Whisper 語言支持](https://github.com/openai/whisper#available-models-and-languages)

### Q: 能離線使用嗎？

**A**: 不能。應用需要網絡連接調用 OpenAI API。

### Q: 隱私和安全性？

**A**:
- ✅ 音頻僅發送到 OpenAI API，不存儲在本地或其他服務器
- ✅ API Key 存儲在您的本地電腦
- ✅ 符合 OpenAI 隱私政策
- ✅ 可查閱 [OpenAI 隱私政策](https://openai.com/policies/privacy-policy)

### Q: 如何卸載？

**A**:
1. 從狀態列退出應用
2. 從「應用程式」文件夾刪除應用
3. 可選：刪除配置
   ```bash
   # 刪除 API Key 配置（可選）
   nano ~/.zshrc  # 刪除 OPENAI_API_KEY 那一行

   # 刪除啟動配置（如果有）
   rm ~/Library/LaunchAgents/com.speech-to-clipboard.plist
   ```

### Q: 應用啟動慢？

**A**:
- Python 應用首次啟動需要 1-2 秒，這是正常的
- 如果超過 5 秒，可能是依賴問題，請聯繫支持

### Q: 可以錄製多長時間？

**A**:
- 理論上沒有時間限制
- 建議每次錄製不超過 1 分鐘以獲得最佳體驗
- 更長的音頻需要更長的處理時間和更高的費用

---

## 💬 獲取幫助

如有問題或建議：

1. 查看 [完整文檔](README.md)
2. 查看 [常見問題](#常見問題)
3. 聯繫您的 IT 支持團隊

---

## 🎉 使用技巧

### 技巧 1: 快速筆記
錄製想法後直接貼到筆記應用（Notion、Evernote 等）

### 技巧 2: 會議記錄
在會議中快速記錄重點（需注意隱私）

### 技巧 3: 多語言輸入
切換語言設定，輕鬆輸入外語內容

### 技巧 4: 長文寫作
分段錄製，避免一次錄太長

### 技巧 5: 配合其他工具
與文字處理軟件、郵件客戶端等配合使用

---

**享受語音輸入的便利！** 🎤✨
