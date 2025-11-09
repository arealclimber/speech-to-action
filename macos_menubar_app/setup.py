"""
Setup script for creating macOS app bundle
使用 py2app 打包應用

使用方法:
    python setup.py py2app

打包後的應用位置:
    dist/Speech to Clipboard.app
"""

from setuptools import setup
import os

APP = ['speech_to_clipboard.py']
DATA_FILES = []

# 可選：如果有圖標文件，則使用它
ICON_FILE = 'icon.icns' if os.path.exists('icon.icns') else None

OPTIONS = {
    'argv_emulation': False,
    'packages': ['rumps', 'sounddevice', 'openai', 'pyperclip', 'numpy', 'scipy'],
    'excludes': ['tkinter', 'matplotlib'],  # 排除不需要的包以減小體積
    'plist': {
        'LSUIElement': True,  # 不顯示在 Dock（只在狀態列顯示）
        'CFBundleName': 'Speech to Clipboard',
        'CFBundleDisplayName': 'Speech to Clipboard',
        'CFBundleGetInfoString': "語音轉文字工具 - 使用 OpenAI Whisper API",
        'CFBundleIdentifier': "com.funnow.speech-to-clipboard",
        'CFBundleVersion': "1.0.0",
        'CFBundleShortVersionString': "1.0.0",
        'NSMicrophoneUsageDescription': '此應用需要訪問麥克風以進行語音識別',
        'NSAppleEventsUsageDescription': '此應用需要訪問系統事件',

        # 環境變量配置（可選 - 用戶需要在此設置 API Key）
        # 注意：出於安全考慮，建議用戶自行設置環境變量而非硬編碼
        # 'LSEnvironment': {
        #     'OPENAI_API_KEY': 'your-api-key-here'  # 不建議在此硬編碼
        # },
    },
    'iconfile': ICON_FILE,

    # 優化選項
    'strip': True,  # 移除調試符號以減小體積
    'semi_standalone': False,  # 完全獨立的應用
}

setup(
    name='Speech to Clipboard',
    version='1.0.0',
    author='FunNow AI Team',
    description='macOS 狀態列語音轉文字應用',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
