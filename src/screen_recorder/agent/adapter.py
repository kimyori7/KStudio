"""VideoSessionAdapter Protocol — 도구가 활성 영상 탭 상태 읽기 위한 인터페이스.

구현체:
- 프로덕션: `MainWindow._MainWindowVideoSession` 가 tab_area.current_video_tab() 위임.
- 테스트:   Fake 어댑터 (sidecar/duration/position 만 가진 stub).

도구 자체는 PySide6 의존 없음 — 어댑터 통해서만 UI 측 상태 접근.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

from ..effects.sidecar import Sidecar


class VideoSessionAdapter(Protocol):
    def has_active_video(self) -> bool: ...
    def source_path(self) -> Optional[str]: ...
    def duration_ms(self) -> int: ...
    def position_ms(self) -> int: ...
    def sidecar(self) -> Optional[Sidecar]: ...


def list_video_tabs_safe(adapter: Any) -> list[dict]:
    """adapter.list_video_tabs() 호출 — 메서드 없거나 실패 시 [] 반환.

    Protocol 에는 안 넣음 — 기존 fake adapter 호환 + 미구현 어댑터도 안전.
    """
    fn = getattr(adapter, "list_video_tabs", None)
    if not callable(fn):
        return []
    try:
        return list(fn())
    except Exception:
        return []


def source_duration_ms_safe(adapter: Any) -> int:
    """adapter.source_duration_ms() 호출 — 메서드 없으면 0 반환.

    Protocol 에 추가하지 않고 optional 메서드로 다룸. fake adapter 호환 보존.
    원본(file) 길이와 combined(cuts 후) 길이 구분이 필요한 곳에서 사용.
    """
    fn = getattr(adapter, "source_duration_ms", None)
    if not callable(fn):
        return 0
    try:
        return int(fn() or 0)
    except Exception:
        return 0
