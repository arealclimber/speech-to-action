#!/usr/bin/env python3
"""
全局快捷鍵功能測試腳本
Test script for global hotkey functionality
"""

import sys
import time
from pynput import keyboard

print("=" * 60)
print("全局快捷鍵測試")
print("Global Hotkey Test")
print("=" * 60)

# 測試快捷鍵組合
hotkey_combo = '<ctrl>+<alt>+r'
press_count = 0

def on_activate():
    """快捷鍵被激活時的回調"""
    global press_count
    press_count += 1
    timestamp = time.strftime("%H:%M:%S")
    print(f"\n[{timestamp}] ✅ 快捷鍵被觸發！(第 {press_count} 次)")
    print(f"    組合鍵: Control+Option+R")

    if press_count >= 3:
        print("\n✨ 測試完成！快捷鍵工作正常。")
        print("   按 Ctrl+C 退出測試")

print(f"\n測試快捷鍵組合: {hotkey_combo}")
print("映射為: Control+Option+R (⌃⌥R)")
print()
print("請按快捷鍵測試...")
print("(按 3 次快捷鍵後測試完成)")
print()

try:
    # 創建並啟動監聽器
    with keyboard.GlobalHotKeys({hotkey_combo: on_activate}) as listener:
        print("🎧 監聽器已啟動")
        print("   等待快捷鍵輸入...")
        print()

        # 保持運行
        listener.join()

except KeyboardInterrupt:
    print("\n\n👋 測試中止")
    sys.exit(0)
except Exception as e:
    print(f"\n❌ 錯誤: {e}")
    print("\n可能的原因：")
    print("1. 沒有輔助功能權限")
    print("   解決：系統偏好設置 → 安全性與隱私 → 輔助功能")
    print("2. pynput 未安裝")
    print("   解決：pip install pynput")
    sys.exit(1)
