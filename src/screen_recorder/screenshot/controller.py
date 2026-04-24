"""스크린샷 캡처 흐름 지휘 — 창 숨김, 스냅, 영역 선택, 복원, 시그널 발행."""
from __future__ import annotations
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal, QTimer, QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from ..capture.targets import Rect
from ..ui.overlay.region_selector import RegionSelector
from .capture import snapshot_virtual_desktop, virtual_desktop_bounds, crop_to_rect


_HIDE_SETTLE_MS = 50  # 창 숨김 후 WM 재그리기 대기


class ScreenshotController(QObject):
    captured = Signal(QImage, str)  # image, source_label ("region" | "fullscreen")
    cancelled = Signal()

    def __init__(
        self,
        main_window: Optional[QWidget],
        viewer_getter: Callable[[], Optional[QWidget]],
    ):
        """main_window 는 직접 참조, viewer 는 아직 생성 안 됐을 수 있으므로 getter 로 받는다."""
        super().__init__()
        self._main = main_window
        self._viewer_getter = viewer_getter

        # 캡처 순간에 기억해둘 '복원 대상' (ing 중 상태)
        self._to_restore: list[tuple[QWidget, bool, bool]] = []  # (widget, was_minimized, was_visible)

    # ---------- 공개 진입점 ----------

    def capture_full(self) -> None:
        self._hide_self_and_then(lambda snapshot: self._handle_full(snapshot))

    def capture_region(self) -> None:
        self._hide_self_and_then(lambda snapshot: self._handle_region(snapshot))

    # ---------- 내부 단계 ----------

    def _hide_self_and_then(self, after_snap: Callable[[QImage], None]) -> None:
        """자기 창 숨김 → 짧은 지연 → 스냅 → 복원 → after_snap(snapshot) 호출."""
        self._to_restore = []
        for w in self._collect_own_windows():
            if w is None:
                continue
            was_min = bool(w.isMinimized())
            was_vis = bool(w.isVisible())
            self._to_restore.append((w, was_min, was_vis))
            w.hide()

        QTimer.singleShot(_HIDE_SETTLE_MS, lambda: self._do_snap(after_snap))

    def _do_snap(self, after_snap: Callable[[QImage], None]) -> None:
        snap = snapshot_virtual_desktop()
        self._restore_own_windows()
        after_snap(snap)

    def _restore_own_windows(self) -> None:
        for w, was_min, was_vis in self._to_restore:
            if not was_vis:
                continue
            if was_min:
                w.showMinimized()
            else:
                w.showNormal()
        self._to_restore = []

    def _collect_own_windows(self) -> list[QWidget | None]:
        return [self._main, self._viewer_getter()]

    def _handle_full(self, snapshot: QImage) -> None:
        if snapshot.isNull():
            self.cancelled.emit()
            return
        self.captured.emit(snapshot, "fullscreen")

    def _handle_region(self, snapshot: QImage) -> None:
        if snapshot.isNull():
            self.cancelled.emit()
            return
        bounds = virtual_desktop_bounds()
        sel = RegionSelector(show_magnifier=True)
        sel.set_source_image(snapshot)

        def on_selected(rect: Rect):
            # rect 는 가상 데스크톱 좌표 — snapshot 은 bounds 의 왼쪽-위를 (0,0) 으로 두므로 오프셋 보정
            qrect = QRect(rect.x - bounds.x(), rect.y - bounds.y(), rect.w, rect.h)
            cropped = crop_to_rect(snapshot, qrect)
            if cropped.isNull():
                self.cancelled.emit()
                return
            self.captured.emit(cropped, "region")

        def on_cancelled():
            self.cancelled.emit()

        sel.region_selected.connect(on_selected)
        sel.cancelled.connect(on_cancelled)
        sel.show()
        sel.raise_()
        sel.activateWindow()
