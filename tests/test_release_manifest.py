import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    import sys
    sys.path.insert(0, str(_ROOT / "src"))      # 패키지 Manifest import 용
    p = _ROOT / "scripts" / "release_manifest.py"
    spec = importlib.util.spec_from_file_location("release_manifest", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

REPO = "kimyori7/KStudio-releases"


def test_asset_url():
    rm = _load()
    assert rm.asset_url(REPO, "0.1.5", "KStudio.exe") == (
        "https://github.com/kimyori7/KStudio-releases/releases/download/v0.1.5/KStudio.exe"
    )


def test_manifest_full_only():
    rm = _load()
    d = rm.build_manifest_dict(REPO, "0.1.5", "n", "a" * 64, "ihash")
    assert d["version"] == "0.1.5"
    assert d["full_url"].endswith("KStudio-Setup-0.1.5.exe")
    assert d["full_sha256"] == "a" * 64
    assert d["code_url"] == ""                  # 코드 패치 없음
    assert d["internal_hash"] == "ihash"


def test_manifest_with_code():
    rm = _load()
    d = rm.build_manifest_dict(REPO, "0.1.5", "n", "a" * 64, "ihash",
                               code_sha256="b" * 64)
    assert d["code_url"].endswith("/v0.1.5/KStudio.exe")
    assert d["code_sha256"] == "b" * 64


def test_manifest_validates_against_plan1_schema():
    # 빌드한 dict 가 Plan 1 parse_manifest 를 통과해야 함(계약 일치).
    rm = _load()
    from screen_recorder.app.updater.manifest import parse_manifest
    d = rm.build_manifest_dict(REPO, "0.1.5", "n", "a" * 64, "ih", code_sha256="b" * 64)
    m = parse_manifest(d)
    assert m.version == "0.1.5"
    assert m.code_url.endswith("KStudio.exe")
