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
        'dify.company_resolution_client',
        'dify.metric_client',
        'dify.workflow',
        'core.metric_discovery',
        'core.company_resolution',
        'core.metric_catalogs',
        'core.analysis_result',
        'core.analysis_contract',
        'core.data_access',
        'llm',
        'llm.gemini_client',
        'matplotlib',
        'matplotlib.backends.backend_agg',
        'matplotlib.pyplot',
        'pandas',
        'pyarrow',
        'pyarrow.parquet',
        'duckdb',
        'psutil',
        'openpyxl',
        'xlrd',
        'workers.metric_discovery_worker',
        'workers.company_resolution_worker',
        'ui.company_selection_dialog',
        'ui.metric_discovery_page',
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
