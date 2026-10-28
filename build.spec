# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for AI Bridge.
Build: pyinstaller build.spec
"""

block_cipher = None

a = Analysis(
    ['entry.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ai_bridge/ui', 'ai_bridge/ui'),
    ],
    hiddenimports=[
        'flask',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.routing',
        'werkzeug.exceptions',
        'httpx',
        'httpcore',
        'webview',
        'webview.platforms.winforms',
        'webview.platforms.gtk',
        'webview.platforms.cocoa',
        'clr',
        'clr_loader',
        'pystray',
        'pystray._util',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PyQt5', 'PyQt6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zlib_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AI-Bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
