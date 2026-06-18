"""KStudio 버전 올리기 — 단일 소스(`src/screen_recorder/__init__.py`) 한 곳만 수정.

이 한 줄(`__version__`)이 유일한 진실원이고 pyproject 메타데이터 · 정보창 ·
인스톨러(.iss)는 모두 여기서 *유도*된다. 그래서 버전 올리기 = 이 파일 한 줄 수정
+ git 태그. 본 스크립트가 그 두 가지를 도와준다.

사용법:
    python scripts/bump_version.py patch     # 0.1.0 -> 0.1.1 (버그픽스)
    python scripts/bump_version.py minor     # 0.1.5 -> 0.2.0 (기능 추가)
    python scripts/bump_version.py major     # 0.3.7 -> 1.0.0 (호환성 변경)
    python scripts/bump_version.py 1.4.2     # 명시적 버전으로
    python scripts/bump_version.py patch --tag   # 위 + git 태그 v0.1.1 까지 생성

`--tag` 없이 실행하면 파일만 고치고 태그 명령은 출력만 한다(사람이 검토 후 실행).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_INIT_PATH = Path(__file__).resolve().parent.parent / "src" / "screen_recorder" / "__init__.py"
_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')
_PARTS = ("major", "minor", "patch")


# ---------- 순수 함수(테스트 대상) ----------
def parse_semver(s: str) -> tuple[int, int, int]:
    """'1.2.3' -> (1, 2, 3). 형식이 어긋나면 ValueError."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", s.strip())
    if not m:
        raise ValueError(f"SemVer(X.Y.Z) 형식이 아님: {s!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_semver(t: tuple[int, int, int]) -> str:
    return f"{t[0]}.{t[1]}.{t[2]}"


def bump(version: str, part: str) -> str:
    """part('major'|'minor'|'patch') 를 1 올리고 하위 자리는 0으로."""
    major, minor, patch = parse_semver(version)
    if part == "major":
        return format_semver((major + 1, 0, 0))
    if part == "minor":
        return format_semver((major, minor + 1, 0))
    if part == "patch":
        return format_semver((major, minor, patch + 1))
    raise ValueError(f"part 는 {_PARTS} 중 하나여야 함: {part!r}")


def read_version(init_path: Path) -> str:
    """`__init__.py` 텍스트에서 __version__ 값을 읽는다."""
    m = _VERSION_RE.search(init_path.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"__version__ 를 찾을 수 없음: {init_path}")
    return m.group(1)


def set_version(text: str, new: str) -> str:
    """`__init__.py` 텍스트의 __version__ 값을 new 로 치환(다른 줄 보존)."""
    parse_semver(new)  # 잘못된 버전으로 덮어쓰지 않게 검증
    if not _VERSION_RE.search(text):
        raise ValueError("__version__ 라인을 찾을 수 없음")
    return _VERSION_RE.sub(f'__version__ = "{new}"', text, count=1)


# ---------- CLI ----------
def _resolve_target(current: str, arg: str) -> str:
    if arg in _PARTS:
        return bump(current, arg)
    parse_semver(arg)  # 명시 버전 — 형식 검증
    return arg


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    want_tag = "--tag" in argv
    positional = [a for a in argv if a != "--tag"]
    if not positional:
        print("올릴 part(major/minor/patch) 또는 명시 버전을 지정하세요.", file=sys.stderr)
        return 2

    current = read_version(_INIT_PATH)
    try:
        new = _resolve_target(current, positional[0])
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    text = _INIT_PATH.read_text(encoding="utf-8")
    _INIT_PATH.write_text(set_version(text, new), encoding="utf-8")
    print(f"[OK] 버전 {current} -> {new}  ({_INIT_PATH})")
    print("     pyproject · 정보창 · 인스톨러(.iss)는 이 값을 자동으로 따라갑니다.")

    tag = f"v{new}"
    if want_tag:
        subprocess.run(["git", "tag", tag], check=True)
        print(f"[OK] git 태그 생성: {tag}  (푸시: git push origin {tag})")
    else:
        print(f"     태그를 만들려면:  git tag {tag} && git push origin {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
