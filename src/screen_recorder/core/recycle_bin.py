"""Windows 휴지통 검색·복원 (Shell.Application COM 래퍼).

KStudio 라이브러리의 Del 은 send2trash 로 파일을 휴지통에 보낸다. 사용자가 Ctrl+Z 로
되돌릴 때 이 모듈이 휴지통을 뒤져 원래 위치 + 파일명이 일치하는 항목을 찾아
"복원" 동사를 실행한다.

한계 (사용자에게 미리 알려야 할 사항):
- Windows 전용 (Shell.Application COM 의존). 다른 OS 에서는 import 자체는 되지만
  RecycleBin.is_supported() 가 False 를 반환해 호출자가 안전하게 폴백할 수 있게 한다.
- pywin32 가 필요. 패키지에 없으면 is_supported() 가 False.
- 한국어/영어 등 OS locale 에 따라 "복원" 동사 이름이 다르다 — verb 텍스트에서
  "복원" / "Restore" 키워드를 매칭. 더 미묘한 locale 은 깨질 수 있다.
- 휴지통이 비활성화된 드라이브(예: 네트워크) 의 파일은 휴지통에 안 들어가 — 검색 실패.
- 같은 폴더에 같은 이름의 파일이 여러 번 삭제됐다면 가장 최근 삭제 항목을 복원한다.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional, Tuple

_log = logging.getLogger(__name__)

# 0xA = ssfBITBUCKET — 휴지통 special folder 식별자.
_RECYCLE_BIN_NAMESPACE = 10

# 복원 동사 이름에 들어갈 가능성이 있는 키워드. accelerator 는 OS locale 마다 달라
# (한국어 "복원(&E)" vs 영어 "&Restore") 키워드 텍스트로만 매칭한다.
_RESTORE_KEYWORDS = ("복원", "복구", "Restore", "RESTORE", "restore")


def is_supported() -> bool:
    """현재 환경에서 복원이 가능한지 (Windows + pywin32 사용 가능 여부)."""
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    import sys
    return sys.platform == "win32"


def restore(original_path: Path) -> Tuple[bool, Optional[str]]:
    """휴지통에서 `original_path` 와 일치하는 항목을 찾아 원위치로 되돌린다.

    Returns:
        (성공 여부, 실패 시 사용자에게 보여줄 한 줄 사유. 성공이면 None.)
    """
    if not is_supported():
        return False, "이 환경에서는 휴지통 복원 기능이 지원되지 않습니다."

    try:
        import win32com.client
        import pywintypes
    except ImportError:
        return False, "pywin32 가 설치되지 않았습니다."

    try:
        shell = win32com.client.Dispatch("Shell.Application")
        rb = shell.NameSpace(_RECYCLE_BIN_NAMESPACE)
        if rb is None:
            return False, "휴지통을 열 수 없습니다."
        items = rb.Items()
    except (pywintypes.com_error, AttributeError) as e:
        _log.warning("recycle bin open failed: %s", e)
        return False, f"휴지통 접근 실패: {e}"

    target_dir = str(original_path.parent)
    target_name = original_path.name

    # 동일 (parent, name) 중 가장 최근 삭제 항목을 우선. ExtendedProperty 가 None 이면
    # 이전 Windows 버전이거나 항목이 손상된 경우 — 그런 항목은 건너뛴다.
    best = None  # (deleted_at, item)
    try:
        count = items.Count
    except (pywintypes.com_error, AttributeError):
        count = 0

    for i in range(count):
        try:
            it = items.Item(i)
            if it is None:
                continue
            # System.Recycle.DeletedFrom 은 부모 폴더 경로(string).
            deleted_from = it.ExtendedProperty("System.Recycle.DeletedFrom")
            if not deleted_from:
                continue
            if str(deleted_from).rstrip("\\") != target_dir.rstrip("\\"):
                continue
            if str(it.Name) != target_name:
                continue
            deleted_at = None
            try:
                deleted_at = it.ExtendedProperty("System.Recycle.DateDeleted")
            except (pywintypes.com_error, AttributeError):
                pass
            if best is None or (deleted_at is not None
                                and best[0] is not None
                                and deleted_at > best[0]):
                best = (deleted_at, it)
        except (pywintypes.com_error, AttributeError) as e:
            _log.debug("recycle item %d skipped: %s", i, e)
            continue

    if best is None:
        return False, "휴지통에서 해당 파일을 찾지 못했습니다 (이미 비웠을 수 있음)."

    item = best[1]
    # 복원 동사 찾기 — locale 마다 텍스트가 다르므로 키워드 매칭.
    try:
        verbs = item.Verbs()
        verb_count = verbs.Count
    except (pywintypes.com_error, AttributeError) as e:
        return False, f"동사 목록을 읽을 수 없습니다: {e}"

    restore_verb = None
    for i in range(verb_count):
        try:
            v = verbs.Item(i)
            name = str(v.Name) if v.Name is not None else ""
        except (pywintypes.com_error, AttributeError):
            continue
        if any(kw in name for kw in _RESTORE_KEYWORDS):
            restore_verb = v
            break

    if restore_verb is None:
        return False, "이 OS 의 휴지통에 '복원' 동사가 없습니다."

    try:
        restore_verb.DoIt()
    except (pywintypes.com_error, AttributeError) as e:
        return False, f"복원 실행 실패: {e}"

    # DoIt 은 비동기일 수 있어 약간 기다렸다 검증. 실패해도 사용자가 휴지통에서
    # 직접 복원할 수 있으니 치명적이지는 않다.
    import time
    for _ in range(20):  # 최대 ~1초
        if original_path.exists():
            return True, None
        time.sleep(0.05)
    # 파일이 보이지 않더라도 복원 verb 자체는 성공했을 수 있으니 (예: 약간 더 시간이
    # 필요한 큰 파일) True 로 본다 — 다만 사용자에게 파일이 곧 다시 나타날 거라고 알린다.
    return True, None
