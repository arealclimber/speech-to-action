# 應用分發指南

本文檔說明如何將語音轉文字應用打包並分發給其他用戶使用。

## 目錄

1. [方案對比](#方案對比)
2. [方案 A: py2app 打包](#方案-a-py2app-打包)
3. [方案 B: 原生 Swift 應用](#方案-b-原生-swift-應用)
4. [應用簽名與公證](#應用簽名與公證)
5. [創建 DMG 安裝包](#創建-dmg-安裝包)

---

## 方案對比

| 特性 | py2app 打包 | 原生 Swift 應用 |
|------|------------|----------------|
| 開發難度 | ⭐ 簡單 | ⭐⭐⭐ 中等 |
| 應用體積 | 50-100 MB | 5-10 MB |
| 啟動速度 | 較慢（1-2秒） | 快速（<0.5秒） |
| 性能 | 良好 | 優秀 |
| 維護性 | Python 易維護 | Swift 需要 macOS 開發經驗 |
| 適用場景 | 內部使用、快速原型 | 公開發布、App Store |

---

## 方案 A: py2app 打包

### 1. 自動打包

使用提供的自動打包腳本：

```bash
./build.sh
```

這會生成 `dist/Speech to Clipboard.app`

### 2. 手動打包

如果需要自定義配置：

```bash
# 激活虛擬環境
source venv/bin/activate

# 安裝 py2app
pip install py2app

# 清理舊構建
rm -rf build dist

# 執行打包
python setup.py py2app

# 測試應用
open dist/Speech\ to\ Clipboard.app
```

### 3. 配置 API Key

由於安全原因，API Key 不應該硬編碼在應用中。有兩種方式配置：

#### 方式 1: 環境變量（推薦）

用戶需要在啟動應用前設置：

```bash
export OPENAI_API_KEY='your-api-key'
open /Applications/Speech\ to\ Clipboard.app
```

#### 方式 2: 啟動腳本

創建一個啟動腳本 `launch_app.sh`：

```bash
#!/bin/bash
export OPENAI_API_KEY='your-api-key'
open "/Applications/Speech to Clipboard.app"
```

### 4. 分發給其他用戶

#### 4.1 壓縮應用

```bash
# 進入 dist 目錄
cd dist

# 創建 ZIP 文件
zip -r "Speech-to-Clipboard-v1.0.zip" "Speech to Clipboard.app"
```

#### 4.2 分享給用戶

將 ZIP 文件分享給用戶，並提供以下說明：

```markdown
# 安裝說明

1. 解壓下載的 ZIP 文件
2. 將 "Speech to Clipboard.app" 拖到「應用程式」文件夾
3. 首次運行時，在「系統偏好設置」→「安全性與隱私」中點擊「仍要打開」
4. 設置您的 OpenAI API Key（見下方）

## 設置 API Key

在終端執行：
\`\`\`bash
echo 'export OPENAI_API_KEY="your-api-key-here"' >> ~/.zshrc
source ~/.zshrc
\`\`\`

然後重新啟動應用。
```

### 5. 優缺點

**優點：**
- ✅ 打包簡單快速
- ✅ 無需額外開發
- ✅ 適合內部使用或小範圍分發

**缺點：**
- ❌ 應用體積大（50-100 MB）
- ❌ 未簽名的應用會被 macOS Gatekeeper 警告
- ❌ 啟動速度較慢
- ❌ 無法上架 App Store

---

## 方案 B: 原生 Swift 應用

如果您需要一個真正的原生應用用於公開發布，我可以為您創建一個 Swift 版本。

### 優勢

- 🚀 啟動速度快
- 📦 應用體積小
- 🔒 可以進行代碼簽名和公證
- 🍎 可以上架 Mac App Store
- ⚡ 更好的性能和系統整合

### 開發要求

- Xcode 14+
- macOS 12+
- Apple Developer Account（用於簽名）

### 是否需要創建？

如果您需要，我可以為您創建一個完整的 Swift 版本，包括：
- SwiftUI 界面
- 原生音頻錄製
- 狀態列集成
- 與 Python 版本相同的功能

---

## 應用簽名與公證

### 為什麼需要簽名？

- macOS Gatekeeper 會阻止未簽名的應用
- 用戶需要手動允許才能運行
- 簽名後的應用更可信

### 簽名步驟（需要 Apple Developer Account）

#### 1. 獲取開發者證書

在 [Apple Developer](https://developer.apple.com) 創建並下載：
- Developer ID Application 證書

#### 2. 簽名應用

```bash
# 查看可用證書
security find-identity -v -p codesigning

# 簽名應用（替換為您的證書名稱）
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name (XXXXXXXXXX)" \
  --options runtime \
  "dist/Speech to Clipboard.app"

# 驗證簽名
codesign --verify --verbose "dist/Speech to Clipboard.app"
spctl -a -v "dist/Speech to Clipboard.app"
```

#### 3. 公證應用（Notarization）

```bash
# 壓縮應用
ditto -c -k --keepParent "dist/Speech to Clipboard.app" "Speech-to-Clipboard.zip"

# 上傳公證
xcrun notarytool submit "Speech-to-Clipboard.zip" \
  --apple-id "your@email.com" \
  --password "app-specific-password" \
  --team-id "XXXXXXXXXX" \
  --wait

# 附加公證票據
xcrun stapler staple "dist/Speech to Clipboard.app"
```

### 免費替代方案

如果沒有 Apple Developer Account：

1. **提供安裝說明**：告訴用戶如何允許未簽名的應用
2. **使用自簽名證書**：可以創建本地證書，但用戶仍需手動允許
3. **開源發布**：用戶自行構建

---

## 創建 DMG 安裝包

DMG 是 macOS 應用的標準分發格式。

### 自動創建 DMG

```bash
# 安裝 create-dmg
brew install create-dmg

# 創建 DMG
create-dmg \
  --volname "Speech to Clipboard" \
  --volicon "icon.icns" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "Speech to Clipboard.app" 175 120 \
  --hide-extension "Speech to Clipboard.app" \
  --app-drop-link 425 120 \
  "Speech-to-Clipboard-v1.0.dmg" \
  "dist/"
```

### 手動創建 DMG

```bash
# 創建臨時 DMG
hdiutil create -volname "Speech to Clipboard" -srcfolder "dist" -ov -format UDZO "Speech-to-Clipboard-v1.0.dmg"
```

### DMG 優點

- 📦 專業的安裝體驗
- 🖱️ 拖拽安裝
- 💾 自包含，易於分發

---

## 建議的分發流程

### 快速內部分發（無需簽名）

1. 使用 `./build.sh` 打包
2. 壓縮成 ZIP
3. 提供安裝說明（包括如何允許未簽名的應用）

### 專業公開分發（推薦）

1. 創建原生 Swift 應用（可選）
2. 使用 Apple Developer 證書簽名
3. 公證應用
4. 創建 DMG 安裝包
5. 在網站或 GitHub Releases 發布

### App Store 分發（最專業）

1. 創建原生 Swift 應用
2. 符合 App Store 審核指南
3. 使用沙盒和應用內購買（如果需要）
4. 提交審核

---

## 常見問題

### Q: 用戶打開應用時顯示「無法打開，因為它來自身份不明的開發者」

A: 這是正常的，因為應用未簽名。用戶可以：
1. 右鍵點擊應用，選擇「打開」
2. 或在「系統偏好設置」→「安全性與隱私」中點擊「仍要打開」

### Q: 如何減小應用體積？

A:
1. 使用 `--strip` 選項移除調試符號
2. 排除不必要的依賴
3. 考慮創建原生 Swift 應用（體積小 10 倍）

### Q: 應用啟動很慢怎麼辦？

A: Python 應用啟動會慢一些。如果需要快速啟動，建議：
1. 創建原生 Swift 應用
2. 或使用 PyInstaller 替代 py2app

### Q: 如何更新應用？

A:
1. 重新打包新版本
2. 更改版本號（在 setup.py 中）
3. 重新分發

---

## 總結

- **快速測試/內部使用**：使用 py2app 打包（當前方案）
- **小範圍分發**：py2app + 簽名
- **公開發布**：創建原生 Swift 應用 + 簽名 + 公證 + DMG
- **最專業**：上架 Mac App Store

如需創建原生 Swift 版本或其他協助，請隨時告訴我！
