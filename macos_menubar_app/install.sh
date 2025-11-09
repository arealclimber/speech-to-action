#!/bin/bash
# 安裝腳本

set -e

echo "================================"
echo "語音轉文字應用 - 安裝程序"
echo "================================"
echo ""

# 檢查 Python 版本
if ! command -v python3 &> /dev/null; then
    echo "❌ 錯誤: 未找到 Python 3"
    echo "請先安裝 Python 3.8 或更高版本"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d ' ' -f 2 | cut -d '.' -f 1,2)
echo "✓ 找到 Python $PYTHON_VERSION"

# 檢查是否設置了 API Key
if [ -z "$OPENAI_API_KEY" ]; then
    echo ""
    echo "⚠️  警告: 未設置 OPENAI_API_KEY 環境變量"
    echo ""
    read -p "請輸入您的 OpenAI API Key: " api_key
    if [ -n "$api_key" ]; then
        export OPENAI_API_KEY="$api_key"
        echo "export OPENAI_API_KEY='$api_key'" >> ~/.zshrc
        echo "✓ API Key 已保存到 ~/.zshrc"
    else
        echo "❌ 未輸入 API Key，稍後請手動設置"
    fi
else
    echo "✓ API Key 已設置"
fi

# 創建虛擬環境
echo ""
echo "創建虛擬環境..."
if [ -d "venv" ]; then
    echo "虛擬環境已存在，跳過"
else
    python3 -m venv venv
    echo "✓ 虛擬環境創建完成"
fi

# 激活虛擬環境
source venv/bin/activate

# 安裝依賴
echo ""
echo "安裝依賴項..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt

echo "✓ 所有依賴項安裝完成"

# 創建啟動腳本
echo ""
echo "創建啟動腳本..."
cat > run.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python3 speech_to_clipboard.py
EOF

chmod +x run.sh
echo "✓ 啟動腳本創建完成"

echo ""
echo "================================"
echo "✅ 安裝完成！"
echo "================================"
echo ""
echo "使用方法:"
echo "  ./run.sh          - 啟動應用"
echo ""
echo "或者:"
echo "  source venv/bin/activate"
echo "  python3 speech_to_clipboard.py"
echo ""
