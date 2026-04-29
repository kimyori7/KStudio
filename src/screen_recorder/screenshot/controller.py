"""스크린샷 캡처 흐름 지휘 — 창 숨김, 스냅, 영역 선택, 복원, 시그널 발행."""
from __future__ import annotations
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal, QTimer, QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from ..capture.targets import Rect
from ..ui.overlay.region_selector import RegionSelector
from .capture import (
    crop_to_rect, snapshot_monitor, snapshot_virtual_desktop, virtual_desktop_bounds,
)


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
        self._to_restore: list[tuple[QWidget, bool, bool, bool]] = []  # (widget, was_minimized, was_maximized, was_visible)
        self._active_selector: "RegionSelector | None" = None
        self._monitor_index_for_capture: int = -1  # capture_full 호출 시 set

    # ---------- 공개 진입점 ----------

    def capture_full(self, monitor_index: int = -1) -> None:
        """monitor_index = -1 → 전체 가상 데스크톱, 0/1/.. → 해당 모니터만."""
        self._monitor_index_for_capture = monitor_index
        self._hide_self_and_then(self._handle_full)

    def capture_region(self) -> None:
        self._hide_self_and_then(self._handle_region)

    # ---------- 내부 단계 ----------

    def _hide_self_and_then(self, after_snap: Callable[[QImage], None]) -> None:
        """창을 건드리지 않고 즉시 스냅 → 후처리 진행.

        다양한 hide 시도 (hide / showMinimized / setWindowOpacity 0) 를 거쳐 도달한 결론:
        - WDA_EXCLUDEFROMCAPTURE 가 적용돼 있어 스냅에 메인 창이 포함되지 않는다.
        - RegionSelector 는 WindowStaysOnTopHint 로 가상 데스크톱 전체를 덮고, 자체적으로
          캡처된 스냅 위에 오버레이를 그린다 → 메인 창이 그 뒤에 있어도 사용자 시야 차단.
        - 따라서 메인 창을 hide 할 시각적 이유가 없으며, hide 로 인한 깜박임만 부작용.
        - 빠른 스냅 → 즉시 후처리.
        """
        self._to_restore = []
        QTimer.singleShot(0, lambda: self._do_snap(after_snap))

    def _do_snap(self, after_snap: Callable[[QImage], None]) -> None:
        if after_snap is self._handle_full:
            # 전체 캡처: 선택된 모니터만 (또는 -1 면 전체 가상 데스크톱)
            snap = snapshot_monitor(self._monitor_index_for_capture)
        else:
            # 영역 캡처용 스냅은 항상 가상 데스크톱 전체 (사용자가 영역 선택)
            snap = snapshot_virtual_desktop()
        # full capture 는 즉시 복원, region 은 selector 종료 후 복원 (사용자가 창 가린 상태에서 선택).
        if after_snap is self._handle_region:
            after_snap(snap)
        else:
            self._restore_own_windows()
            after_snap(snap)

    def _restore_own_windows(self) -> None:
        # 더 이상 hide 를 안 하므로 복원할 것도 없음. _to_restore 호환을 위해 비움.
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
        self._active_selector = sel
        sel.set_source_image(snapshot)

        def on_selected(rect: Rect):
            # rect 는 가상 데스크톱 좌표 — snapshot 은 bounds 의 왼쪽-위를 (0,0) 으로 두므로 오프셋 보정
            qrect = QRect(rect.x - bounds.x(), rect.y - bounds.y(), rect.w, rect.h)
            cropped = crop_to_rect(snapshot, qrect)
            self._restore_own_windows()
            if cropped.isNull():
                self.cancelled.emit()
                self._active_selector = None
                return
            self.captured.emit(cropped, "region")
            self._active_selector = None

        def on_cancelled():
            self._restore_own_windows()
            self.cancelled.emit()
            self._active_selector = None

        sel.region_selected.connect(on_selected)
        sel.cancelled.connect(on_cancelled)
        sel.show()
        sel.raise_()
        sel.activateWindow()
