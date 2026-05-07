"""영상 탭의 편집 상태 보유자 — Sidecar + History + autosave + 편집 모드."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ...effects import (
    History, Sidecar, SidecarStore, Trim, compute_video_hash,
)


_AUTOSAVE_DEBOUNCE_MS = 500


class EditController(QObject):
    """한 영상 탭의 편집 상태.

    - Sidecar 로드/저장
    - History (undo/redo)
    - autosave (사이드카 변경 후 디바운스 저장)
    - 편집 모드 ON/OFF 상태

    UI 위젯은 보유하지 않는다 — VideoTab 이 시그널을 받아 lanes/인스펙터에 전달.
    """

    sidecar_replaced = Signal(object)        # Sidecar — 외부 변경 (undo/redo, 효과 추가) 후
    edit_mode_toggled = Signal(bool)         # ON/OFF
    autosave_failed = Signal(str)            # 에러 메시지

    def __init__(self, video_path: Path, sidecar_dir: Path) -> None:
        super().__init__()
        self._video_path = Path(video_path)
        self._store = SidecarStore(sidecar_dir)
        self._edit_mode_on = False

        loaded = self._store.load_for(self._video_path)
        if loaded is None:
            loaded = Sidecar(
                source_path=str(self._video_path),
                source_hash=compute_video_hash(self._video_path),
                trim=Trim(in_ms=0, out_ms=0),
            )
        self._sidecar: Sidecar = loaded
        self._history = History(initial=loaded)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(_AUTOSAVE_DEBOUNCE_MS)
        self._autosave_timer.timeout.connect(self._do_autosave)

    # ---------- public ----------
    def sidecar(self) -> Sidecar:
        return self._sidecar

    def is_edit_mode_on(self) -> bool:
        return self._edit_mode_on

    def set_edit_mode(self, on: bool) -> None:
        if self._edit_mode_on == on:
            return
        self._edit_mode_on = on
        self.edit_mode_toggled.emit(on)

    def update_sidecar(self, new_sidecar: Sidecar) -> None:
        """효과 추가/삭제/수정 후 호출. History push + autosave 트리거."""
        self._history.push(new_sidecar)
        self._sidecar = self._history.current()
        self.sidecar_replaced.emit(self._sidecar)
        self._autosave_timer.start()

    def undo(self) -> bool:
        if not self._history.can_undo():
            return False
        self._sidecar = self._history.undo()
        self.sidecar_replaced.emit(self._sidecar)
        self._autosave_timer.start()
        return True

    def redo(self) -> bool:
        if not self._history.can_redo():
            return False
        self._sidecar = self._history.redo()
        self.sidecar_replaced.emit(self._sidecar)
        self._autosave_timer.start()
        return True

    # ---------- internal ----------
    def _do_autosave(self) -> None:
        try:
            self._store.save_for(self._video_path, self._sidecar)
        except OSError as e:
            self.autosave_failed.emit(str(e))
