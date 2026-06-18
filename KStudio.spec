# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for KStudio (onedir, Windowed)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(".").resolve()

# Markdown 미리보기 웹 에셋 (template.html / app.js / style.css / Phase2 vendor/*).
# screen_recorder/ui/markdown/assets/** 를 동일 구조로 동봉 → preview._resolve_assets_dir()
# 의 frozen 후보(_internal/screen_recorder/ui/markdown/assets)와 일치.
_markdown_assets = collect_data_files(
    "screen_recorder", includes=["ui/markdown/assets/**"]
)

a = Analysis(
    [str(ROOT / "src" / "screen_recorder" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[
        # ffmpeg.exe만 동봉 (ffplay/ffprobe 는 어플이 안 씀)
        (str(ROOT / "bin" / "ffmpeg.exe"), "bin"),
    ],
    datas=[
        (str(ROOT / "resources" / "app_icon.ico"), "resources"),
    ] + _markdown_assets,
    hiddenimports=collect_submodules("yt_dlp") + [
        # yt-dlp 는 extractor 를 지연 로딩 → PyInstaller 정적 분석이 놓침.
        # collect_submodules 로 모든 extractor/postprocessor 모듈을 동봉해야
        # 설치본(.exe)에서 다운로드가 동작한다 (dev 에선 되는데 exe 만 깨지는 함정).
        # truststore — run_download 가 함수 내부에서 lazy import 하므로 명시 (사내 TLS).
        "truststore",
        "dxcam",
        "pyaudiowpatch",
        "send2trash",
        "send2trash.plat_win",
        "pygetwindow",
        # pywin32 — 휴지통 복원(Shell.Application COM) 에 필요. PyInstaller 가
        # win32com 동적 import 를 자동으로 못 잡아 명시.
        "win32com",
        "win32com.client",
        "pywintypes",
        # QtWebEngine — Markdown 미리보기. preview.py 가 메서드 내부에서 import 하므로
        # PyInstaller 정적 분석이 놓침 → 명시. 이게 있어야 PySide6 hook 이 WebEngine
        # 런타임(QtWebEngineProcess.exe / *.pak / icudtl.dat / locales)을 동봉한다.
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        # QtNetwork — 단일 인스턴스(QLocalServer/QLocalSocket). Qt6Network.dll 동봉 보장.
        "PySide6.QtNetwork",
        # Markdown→HTML 렌더 (preview/render 가 사용).
        "markdown_it",
        "pygments",
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
        # 2026-06-18: 에이전트(로컬 LLM)·Whisper·자동편집·이미지 생성 기능 제거에 따라
        # GPU/AI 스택을 번들에서 제외 — 인스톨러 ~2.4GB→~0.7GB. 코드가 더 이상 import 하지
        # 않으므로 PyInstaller 가 자동으로 빼지만, 전이 의존으로 끌려오지 않도록 명시.
        # (남는 AI 기능 자동 누끼/업스케일은 CPU onnxruntime 기반 — torch/CUDA 불필요.)
        "torch",
        "torchvision",
        "torchgen",
        "torchaudio",
        "transformers",
        "diffusers",
        "accelerate",
        "bitsandbytes",
        "ctranslate2",
        "faster_whisper",
        "nvidia",
        "triton",
        "xformers",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KStudio",
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
    name="KStudio",
)
