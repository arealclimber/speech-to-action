#!/usr/bin/env python3
"""
自動粘貼功能測試腳本
Test script for auto-paste functionality
"""

import sys
from AppKit import NSWorkspace
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap, CGEventSetFlags, kCGEventFlagMaskCommand
import time
import pyperclip


def check_accessibility_permission():
    """檢查輔助功能權限"""
    print("檢查輔助功能權限...")
    options = {kAXTrustedCheckOptionPrompt: True}
    trusted = AXIsProcessTrustedWithOptions(options)

    if trusted:
        print("✅ 已授予輔助功能權限")
        return True
    else:
        print("❌ 需要輔助功能權限")
        print("請在「系統偏好設置」→「安全性與隱私」→「輔助功能」中授權")
        return False


def get_focused_app():
    """獲取當前焦點應用"""
    print("\n檢測焦點應用...")
    try:
        frontmost_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if frontmost_app:
            app_name = frontmost_app.localizedName()
            bundle_id = frontmost_app.bundleIdentifier()
            print(f"✅ 焦點應用: {app_name} ({bundle_id})")
            return app_name
        else:
            print("❌ 無法獲取焦點應用")
            return None
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return None


def test_clipboard():
    """測試剪貼板功能"""
    print("\n測試剪貼板...")
    test_text = "自動粘貼測試文字 - Test Auto Paste"
    try:
        pyperclip.copy(test_text)
        copied = pyperclip.paste()
        if copied == test_text:
            print(f"✅ 剪貼板工作正常: {copied}")
            return True
        else:
            print(f"❌ 剪貼板內容不符")
            return False
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return False


def test_simulate_command_v():
    """測試模擬 Command+V"""
    print("\n測試鍵盤事件模擬...")

    if not check_accessibility_permission():
        return False

    try:
        # 設置測試文字
        test_text = "🎉 自動粘貼測試成功！Auto-paste test successful!"
        pyperclip.copy(test_text)
        print(f"已複製到剪貼板: {test_text}")

        print("\n⚠️ 注意：")
        print("1. 請打開任意文本編輯器（如 Notes、TextEdit）")
        print("2. 點擊輸入框，確保光標在編輯區域")
        print("3. 5 秒後將自動執行 Command+V")
        print("\n倒數計時...")

        for i in range(5, 0, -1):
            print(f"{i}...")
            time.sleep(1)

        # 模擬 Command+V
        v_keycode = 0x09
        cmd_down = CGEventCreateKeyboardEvent(None, 0x37, True)
        CGEventSetFlags(cmd_down, kCGEventFlagMaskCommand)
        v_down = CGEventCreateKeyboardEvent(None, v_keycode, True)
        CGEventSetFlags(v_down, kCGEventFlagMaskCommand)
        v_up = CGEventCreateKeyboardEvent(None, v_keycode, False)
        CGEventSetFlags(v_up, kCGEventFlagMaskCommand)
        cmd_up = CGEventCreateKeyboardEvent(None, 0x37, False)

        CGEventPost(kCGHIDEventTap, cmd_down)
        time.sleep(0.01)
        CGEventPost(kCGHIDEventTap, v_down)
        time.sleep(0.01)
        CGEventPost(kCGHIDEventTap, v_up)
        time.sleep(0.01)
        CGEventPost(kCGHIDEventTap, cmd_up)

        print("✅ Command+V 已執行")
        print("\n請檢查文本編輯器中是否出現測試文字")
        print("如果看到測試文字，說明自動粘貼功能正常！")
        return True

    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return False


def run_all_tests():
    """運行所有測試"""
    print("=" * 60)
    print("自動粘貼功能測試")
    print("Auto-Paste Functionality Test")
    print("=" * 60)

    results = []

    # 測試 1: 權限檢查
    print("\n[測試 1/4] 權限檢查")
    results.append(("權限檢查", check_accessibility_permission()))

    # 測試 2: 焦點應用檢測
    print("\n[測試 2/4] 焦點應用檢測")
    app = get_focused_app()
    results.append(("焦點應用檢測", app is not None))

    # 測試 3: 剪貼板
    print("\n[測試 3/4] 剪貼板功能")
    results.append(("剪貼板功能", test_clipboard()))

    # 測試 4: 鍵盤事件模擬
    print("\n[測試 4/4] 鍵盤事件模擬（自動粘貼）")
    results.append(("自動粘貼", test_simulate_command_v()))

    # 總結
    print("\n" + "=" * 60)
    print("測試總結")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通過" if result else "❌ 失敗"
        print(f"{name}: {status}")

    print(f"\n通過: {passed}/{total}")

    if passed == total:
        print("\n🎉 所有測試通過！自動粘貼功能正常！")
        return 0
    else:
        print("\n⚠️ 部分測試失敗，請檢查上述錯誤信息")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
