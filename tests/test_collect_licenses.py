import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    p = _ROOT / "scripts" / "collect_licenses.py"
    spec = importlib.util.spec_from_file_location("collect_licenses", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_format_bundle_includes_all_sections():
    cl = _load()
    out = cl.format_license_bundle([
        ("FFmpeg", "GPL-3.0", "FFMPEG GPL TEXT"),
        ("PySide6", "LGPL-3.0", "QT LGPL TEXT"),
    ])
    assert "FFmpeg" in out and "GPL-3.0" in out and "FFMPEG GPL TEXT" in out
    assert "PySide6" in out and "LGPL-3.0" in out and "QT LGPL TEXT" in out
    # 컴포넌트 사이 구분선이 있어 사람이 읽을 수 있어야 함.
    assert out.count("=" * 8) >= 2 or out.count("-" * 8) >= 2


def test_license_data_files_present():
    # 법적 필수 데이터 파일이 레포에 있어야 함.
    for name in ("gpl-3.0.txt", "lgpl-3.0.txt", "summary.txt", "SOURCES.md"):
        assert (_ROOT / "licenses" / name).exists(), name


def test_build_bundle_embeds_full_texts_and_provenance():
    cl = _load()
    bundle = cl.build_bundle()
    # 전문 임베드(링크만이 아니라 실제 GPL/LGPL 텍스트):
    assert "GNU GENERAL PUBLIC LICENSE" in bundle
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in bundle
    # 기존 큐레이션 보존(예: dxcam 항목):
    assert "dxcam" in bundle
    # ffmpeg 소스조달 + 정확한 빌드 커밋:
    assert "de18feb0f0" in bundle
    assert "Corresponding Source" in bundle
