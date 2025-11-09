#!/bin/bash
# 啟動腳本

cd "$(dirname "$0")"

# 檢查虛擬環境
if [ ! -d "venv" ]; then
    echo "❌ 錯誤: 虛擬環境不存在"
    echo "請先運行: ./install.sh"
    exit 1
fi

# 激活虛擬環境
source venv/bin/activate

# 檢查 API Key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ 錯誤: 未設置 OPENAI_API_KEY"
    echo "請運行: export OPENAI_API_KEY='your-api-key'"
    exit 1
fi

# 啟動應用
echo "🚀 啟動語音轉文字應用..."
python3 speech_to_clipboard.py
