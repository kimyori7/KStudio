# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Screen Recorder (onedir, Windowed)."""

from pathlib import Path

ROOT = Path(".").resolve()

a = Analysis(
    [str(ROOT / "src" / "screen_recorder" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[
        # ffmpeg.exe만 동봉 (ffplay/ffprobe 는 어플이 안 씀)
        (str(ROOT / "bin" / "ffmpeg.exe"), "bin"),
    ],
    datas=[
        (str(ROOT / "resources" / "app_icon.ico"), "resources"),
    ],
    hiddenimports=[
        "dxcam",
        "pyaudiowpatch",
        "send2trash",
        "send2trash.plat_win",
        "pygetwindow",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        # 'unittest' 는 제외하면 안 됨 — pyrect/doctest 가 의존함
        "pytest",
        "pytest_qt",
        "pytest_cov",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScreenRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # GUI 앱이라 콘솔창 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "resources" / "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ScreenRecorder",
)
