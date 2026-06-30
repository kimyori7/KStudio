"""THIRD-PARTY-LICENSES.txt 생성 — 큐레이션 요약 + 전문 임베드 + ffmpeg 소스조달.

기존에 손으로 큐레이션한 컴포넌트 요약(licenses/summary.txt)을 머리에 두고, 그 뒤에
ffmpeg 소스조달(licenses/SOURCES.md)·GPL v3 전문(licenses/gpl-3.0.txt)·LGPL v3
전문(licenses/lgpl-3.0.txt)을 이어 붙여 하나의 동봉용 파일로 만든다. ffmpeg(GPL)·
Qt/PySide6(LGPL)는 전문이 법적으로 필요하므로 링크가 아니라 실제 텍스트를 싣는다.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LIC = _ROOT / "licenses"
_SEP = "=" * 72


def format_license_bundle(sections: list[tuple[str, str, str]]) -> str:
    """(component, license_name, license_text) 목록 → 단일 문서(순수)."""
    parts = ["KStudio — THIRD PARTY LICENSES", _SEP, ""]
    for component, license_name, text in sections:
        parts.append(f"## {component}  ({license_name})")
        parts.append("-" * 72)
        parts.append(text.strip())
        parts.append("")
        parts.append(_SEP)
        parts.append("")
    return "\n".join(parts)


def _read(name: str) -> str:
    return (_LIC / name).read_text(encoding="utf-8")


def build_bundle() -> str:
    """licenses/ 데이터를 모아 최종 번들 문자열을 만든다(순수 조합)."""
    sections = [
        ("KStudio third-party components (summary)", "various", _read("summary.txt")),
        ("FFmpeg — corresponding source & provenance", "GPL-3.0", _read("SOURCES.md")),
        ("GNU GENERAL PUBLIC LICENSE (v3)", "GPL-3.0", _read("gpl-3.0.txt")),
        ("GNU LESSER GENERAL PUBLIC LICENSE (v3)", "LGPL-3.0", _read("lgpl-3.0.txt")),
        ("MOZILLA PUBLIC LICENSE (v2.0) — applies to: certifi", "MPL-2.0", _read("mpl-2.0.txt")),
    ]
    return format_license_bundle(sections)


def main() -> int:
    out = build_bundle()
    dest = _ROOT / "THIRD-PARTY-LICENSES.txt"
    dest.write_text(out, encoding="utf-8")
    print(f"[OK] {dest}  ({len(out)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
