# -*- mode: python ; coding: utf-8 -*-

import os

console_enabled = os.getenv('PYINSTALLER_CONSOLE', '0') == '1'

a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'dify.client',
        'dify.workflow',
        'core.analysis_result',
        'llm',
        'llm.gemini_client',
        'matplotlib',
        'matplotlib.backends.backend_agg',
        'matplotlib.pyplot',
        'pandas',
        'openpyxl',
        'xlrd',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EY-DAClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=console_enabled,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='EY-DAClient',
)
