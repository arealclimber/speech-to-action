#!/bin/bash
# 打包腳本 - 將 Python 應用打包成獨立的 macOS .app

set -e

echo "================================"
echo "語音轉文字應用 - 打包工具"
echo "================================"
echo ""

# 檢查虛擬環境
if [ ! -d "venv" ]; then
    echo "❌ 錯誤: 虛擬環境不存在"
    echo "請先運行: ./install.sh"
    exit 1
fi

# 激活虛擬環境
source venv/bin/activate

# 安裝 py2app
echo "安裝打包工具..."
pip install py2app > /dev/null 2>&1
echo "✓ py2app 已安裝"

# 清理舊的構建
echo ""
echo "清理舊的構建..."
rm -rf build dist
echo "✓ 清理完成"

# 創建應用圖標（如果不存在）
if [ ! -f "icon.icns" ]; then
    echo ""
    echo "⚠️  提示: 未找到 icon.icns，將使用默認圖標"
    echo "   您可以創建自己的圖標並命名為 icon.icns"
fi

# 執行打包
echo ""
echo "開始打包應用..."
python setup.py py2app

if [ $? -eq 0 ]; then
    echo ""
    echo "================================"
    echo "✅ 打包成功！"
    echo "================================"
    echo ""
    echo "應用位置: dist/Speech to Clipboard.app"
    echo ""
    echo "安裝方法:"
    echo "  1. 將 dist/Speech to Clipboard.app 複製到 /Applications"
    echo "  2. 或者雙擊直接運行"
    echo ""
    echo "⚠️  注意事項:"
    echo "  - 首次運行需要在「系統偏好設置」→「安全性與隱私」中允許"
    echo "  - 需要授予麥克風權限"
    echo "  - 需要設置 OPENAI_API_KEY（見下方說明）"
    echo ""
    echo "設置 API Key 的方法:"
    echo "  1. 編輯 setup.py 中的 plist，添加 OPENAI_API_KEY"
    echo "  2. 或者在終端運行應用時設置環境變量"
    echo ""
    echo "分發給其他用戶:"
    echo "  - 可以直接分享 .app 文件（約 50-100MB）"
    echo "  - 建議壓縮成 .zip 或 .dmg 格式"
    echo "  - 如需在其他 Mac 上使用，需要代碼簽名（見 DISTRIBUTION.md）"
    echo ""
else
    echo "❌ 打包失敗"
    exit 1
fi
