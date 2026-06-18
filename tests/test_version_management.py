"""단일 소스 버전 관리 회귀 테스트.

핵심 불변식:
- `screen_recorder.__version__` 가 유일한 버전 진실원(single source of truth).
- 정보창(About), pyproject 메타데이터, 인스톨러(.iss)는 모두 이 값을 *유도*한다.
- bump 스크립트는 SemVer 규칙대로 part 를 올린다(상위 올리면 하위는 0).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_bump_module():
    """scripts/bump_version.py 를 패키지 밖에서 직접 로드(테스트 전용)."""
    path = _ROOT / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- SemVer 파싱/포맷 ----------
def test_parse_semver_roundtrip():
    bv = _load_bump_module()
    assert bv.parse_semver("1.2.3") == (1, 2, 3)
    assert bv.format_semver((1, 2, 3)) == "1.2.3"


def test_parse_semver_rejects_bad():
    bv = _load_bump_module()
    for bad in ["1.2", "v1.2.3", "1.2.3.4", "a.b.c", ""]:
        with pytest.raises(ValueError):
            bv.parse_semver(bad)


# ---------- bump 규칙 ----------
def test_bump_patch():
    bv = _load_bump_module()
    assert bv.bump("0.1.0", "patch") == "0.1.1"


def test_bump_minor_zeros_patch():
    bv = _load_bump_module()
    assert bv.bump("0.1.5", "minor") == "0.2.0"


def test_bump_major_zeros_minor_and_patch():
    bv = _load_bump_module()
    assert bv.bump("0.3.7", "major") == "1.0.0"


def test_bump_rejects_unknown_part():
    bv = _load_bump_module()
    with pytest.raises(ValueError):
        bv.bump("0.1.0", "build")


# ---------- __init__.py 읽기/쓰기 ----------
def test_read_and_set_version_roundtrip(tmp_path: Path):
    bv = _load_bump_module()
    f = tmp_path / "__init__.py"
    f.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    assert bv.read_version(f) == "0.1.0"
    new_text = bv.set_version(f.read_text(encoding="utf-8"), "0.2.0")
    assert new_text == '__version__ = "0.2.0"\n'


def test_set_version_preserves_other_lines():
    bv = _load_bump_module()
    text = '__version__ = "0.1.0"\n# trailing comment\n'
    out = bv.set_version(text, "9.9.9")
    assert '__version__ = "9.9.9"' in out
    assert "# trailing comment" in out


# ---------- 정보창(About) 유도 ----------
def test_about_html_embeds_version():
    from screen_recorder.ui.about import about_html
    html = about_html("3.4.5")
    assert "3.4.5" in html
    assert "KStudio" in html


def test_about_html_has_no_other_hardcoded_version():
    from screen_recorder.ui.about import about_html
    # 버전을 안 넘기면 다른 버전 문자열이 박혀 있으면 안 됨.
    html = about_html("X.Y.Z")
    versions = re.findall(r"\d+\.\d+\.\d+", html)
    assert versions == []  # 주입한 X.Y.Z 외에 하드코딩된 숫자 버전 없음


# ---------- 단일 소스 불변식 ----------
def test_package_version_is_semver():
    import screen_recorder
    assert re.fullmatch(r"\d+\.\d+\.\d+", screen_recorder.__version__)


def test_pyproject_version_is_dynamic():
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # [project] 아래 정적 version = "..." 가 남아 있으면 드리프트 위험 → 금지.
    assert not re.search(r'(?m)^\s*version\s*=\s*"\d', text)
    assert 'dynamic = ["version"]' in text
    assert 'attr = "screen_recorder.__version__"' in text


def test_main_window_about_not_hardcoded():
    # 회귀: _show_about 가 다시 "KStudio 0.1.0" 처럼 하드코딩으로 돌아가면 안 됨.
    src = (_ROOT / "src" / "screen_recorder" / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"KStudio \d+\.\d+\.\d+", src)
    assert "about_html" in src
