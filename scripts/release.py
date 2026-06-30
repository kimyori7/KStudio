"""KStudio 릴리스 오케스트레이션 — 버전 1개 올리면 전체 파이프라인 실행.

흐름:
 1. __init__.py 에서 version 읽기(단일 소스).
 2. 직전 릴리스 latest.json 의 internal_hash 조회(gh; 없으면 prev=None=부트스트랩).
 3. PyInstaller onedir 빌드 -> dist/KStudio/.
 4. compute_internal_hash(dist/KStudio/_internal)  (zip 멤버 정규화 → 의존성 불변 시 동일).
 5. ISCC 로 전체 인스톨러 빌드 -> dist/installer/KStudio-Setup-<v>.exe ; full_sha256.
 6. decide_code_patch 면 dist/KStudio/KStudio.exe 를 코드 자산으로 복사 ; code_sha256.
 7. build_manifest_dict(...) -> latest.json 기록.
 8. gh 로 릴리스 생성/업로드(자산: full installer (+code exe) + latest.json + THIRD-PARTY-LICENSES.txt).
 --dry-run 이면 8 생략(로컬 산출물만).

결정성: SOURCE_DATE_EPOCH 등 빌드 플래그 불필요 — compute_internal_hash 가 base_library.zip
멤버 순서 비결정성을 해시 단에서 정규화한다(PyInstaller 가 멤버를 매 빌드 다른 순서로 기록).
서명 안 함 → sha256 이 유일 신뢰닻. 각 subprocess 실패는 stderr 보존하고 중단.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "src"))

from internal_hash import compute_internal_hash, decide_code_patch  # noqa: E402
from release_manifest import build_manifest_dict, FULL_ASSET, CODE_ASSET  # noqa: E402
from bump_version import read_version  # noqa: E402
from screen_recorder.app.updater.download import sha256_file  # noqa: E402

# Task 0 에서 확정한 공개 릴리스 레포 — Plan 1 controller.RELEASES_REPO 와 동일해야 함.
RELEASES_REPO = "kimyori7/KStudio-releases"

_INIT = _ROOT / "src" / "screen_recorder" / "__init__.py"
_DIST = _ROOT / "dist"
_DIST_APP = _DIST / "KStudio"
_INSTALLER_DIR = _DIST / "installer"
_LICENSES = _ROOT / "THIRD-PARTY-LICENSES.txt"
_ISS = _ROOT / "installer" / "KStudio.iss"


def _iscc_exe() -> Path:
    """ISCC.exe 탐색: env ISCC → PF(x86) → PF → LocalAppData(빌드 .bat 과 동일 순서)."""
    cands = []
    env = os.environ.get("ISCC")
    if env:
        cands.append(Path(env))
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    lad = os.environ.get("LOCALAPPDATA", "")
    cands.append(Path(pf86) / "Inno Setup 6" / "ISCC.exe")
    cands.append(Path(pf) / "Inno Setup 6" / "ISCC.exe")
    if lad:
        cands.append(Path(lad) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    for c in cands:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "ISCC.exe(Inno Setup 6) 를 찾지 못했습니다. 환경변수 ISCC 로 경로를 지정하거나 "
        "https://jrsoftware.org/isdl.php 에서 설치하세요."
    )


def _run(cmd) -> subprocess.CompletedProcess:
    """subprocess 실행 — 실패 시 stdout/stderr 를 그대로 드러내고 중단(증거 보존)."""
    print(f"[run] {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run(cmd, cwd=str(_ROOT), text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        raise SystemExit(f"[ERROR] 명령 실패(rc={proc.returncode}): {cmd[0]}")
    return proc


def _prev_internal_hash(tmp: Path) -> str | None:
    """직전(=latest) 릴리스 latest.json 의 internal_hash. 없으면 None(부트스트랩)."""
    try:
        _run(["gh", "release", "download", "--repo", RELEASES_REPO,
              "--pattern", "latest.json", "--dir", str(tmp), "--clobber"])
    except SystemExit:
        return None
    f = tmp / "latest.json"
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("internal_hash") or None
    except (ValueError, OSError):
        return None


def main(argv: list[str]) -> int:
    # Windows 콘솔/파일 리다이렉트 기본 인코딩(cp949)은 em-dash(—) 같은 비-cp949 문자를
    # 못 써서 print 가 UnicodeEncodeError 로 죽는다(노트·경로에 한글/기호가 섞일 수 있음).
    # stdout/stderr 를 utf-8 로 고정해 어떤 문자든 안전히 출력(로그도 깨지지 않음).
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="KStudio 릴리스 파이프라인")
    ap.add_argument("--notes", default="", help="릴리스 노트")
    ap.add_argument("--dry-run", action="store_true",
                    help="빌드·산출물 생성까지만(gh 업로드 생략)")
    args = ap.parse_args(argv)

    version = read_version(_INIT)
    print(f"[release] version={version}  repo={RELEASES_REPO}  dry_run={args.dry_run}")

    tmp = _DIST / "_release_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    prev_hash = _prev_internal_hash(tmp)
    print(f"[release] 직전 internal_hash = {prev_hash!r}")

    # 3) PyInstaller onedir
    _run([sys.executable, "-m", "PyInstaller", "KStudio.spec", "--noconfirm"])
    # 4) 결정적 _internal 지문
    new_hash = compute_internal_hash(_DIST_APP / "_internal")
    print(f"[release] 새 internal_hash = {new_hash}")

    # 설치본이 자기 _internal 지문을 알 수 있게 앱 루트(KStudio.exe 옆, _internal 밖)에
    # 동봉 → Plan 1 want_code_patch 가 manifest.internal_hash 와 비교해 의존성 바뀐
    # 릴리스를 건너뛴 사용자에게 불일치 코드패치가 적용되는 걸 막는다.
    (_DIST_APP / "internal_hash.txt").write_text(new_hash, encoding="utf-8")

    # 5) 전체 인스톨러(ISCC 직접) — OutputDir 가 없을 때 ISCC 가 만들지만, 실패 시
    # "산출물 없음" 보다 ISCC 자체 에러가 먼저 드러나도록 미리 만들어 둔다.
    _INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    _run([str(_iscc_exe()), str(_ISS)])
    installer = _INSTALLER_DIR / FULL_ASSET.format(version=version)
    if not installer.is_file():
        raise SystemExit(f"[ERROR] 인스톨러 산출물 없음: {installer}")
    full_sha = sha256_file(installer)
    print(f"[release] 전체 인스톨러={installer.name}  sha256={full_sha}")

    # 6) 의존성 불변일 때만 30MB 코드 패치
    include_code = decide_code_patch(new_hash, prev_hash)
    code_sha = ""
    code_asset = None
    if include_code:
        code_asset = _INSTALLER_DIR / CODE_ASSET
        shutil.copy2(_DIST_APP / CODE_ASSET, code_asset)
        code_sha = sha256_file(code_asset)
        print(f"[release] 의존성 불변 → 코드 패치 포함: {CODE_ASSET} sha256={code_sha}")
    else:
        why = "부트스트랩(직전 없음)" if prev_hash is None else "의존성 변경"
        print(f"[release] 코드 패치 제외({why}) → 전체 인스톨러만")

    # 7) latest.json
    manifest = build_manifest_dict(RELEASES_REPO, version, args.notes,
                                   full_sha, new_hash, code_sha)
    latest = _INSTALLER_DIR / "latest.json"
    latest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[release] latest.json 기록: {latest}")

    assets = [installer, latest]
    if _LICENSES.is_file():
        assets.append(_LICENSES)
    else:
        print(f"[warn] {_LICENSES.name} 없음 — Task 3 collect_licenses.py 먼저 실행 권장.")
    if code_asset is not None:
        assets.append(code_asset)

    # 8) 업로드(또는 dry-run)
    if args.dry_run:
        print("[dry-run] gh 업로드 생략. 산출물:")
        for a in assets:
            print(f"   - {a}")
        return 0

    tag = f"v{version}"
    exists = subprocess.run(
        ["gh", "release", "view", tag, "--repo", RELEASES_REPO],
        cwd=str(_ROOT), capture_output=True, text=True).returncode == 0
    asset_paths = [str(a) for a in assets]
    if exists:
        _run(["gh", "release", "upload", tag, *asset_paths,
              "--repo", RELEASES_REPO, "--clobber"])
        # 기존 릴리스가 prerelease/draft 였더라도 latest 로 승격 — Plan 1 의
        # releases/latest/download/latest.json 가 항상 resolve 되도록 보장.
        _run(["gh", "release", "edit", tag,
              "--repo", RELEASES_REPO, "--latest"])
    else:
        _run(["gh", "release", "create", tag, *asset_paths,
              "--repo", RELEASES_REPO, "--title", tag,
              "--notes", args.notes or tag, "--latest"])
    print(f"[release] 업로드 완료: {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
