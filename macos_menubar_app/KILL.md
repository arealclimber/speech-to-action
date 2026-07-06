# 找到並 kill 語音轉文字 menubar 進程

## 方法 A：一行直接 kill（最快）

```bash
pkill -f speech_to_clipboard.py
```

## 方法 B：先找 PID 確認，再 kill（比較安全）

```bash
# 1. 找出進程 PID（會列出 PID 和啟動指令）
pgrep -fl speech_to_clipboard.py

# 2. 用上一步看到的 PID 來 kill（把 <PID> 換成實際數字）
kill <PID>

# 若不理會，再用強制 kill
kill -9 <PID>
```

## 確認已經關掉

```bash
pgrep -fl speech_to_clipboard.py || echo "已關閉，沒有殘留進程"
```

## 重新啟動（要在有 OPENAI_API_KEY 的終端機，例如有 source ~/.zshrc 的）

```bash
cd /Users/shirley/arealclimber/speech-to-action/macos_menubar_app
python speech_to_clipboard.py
```
