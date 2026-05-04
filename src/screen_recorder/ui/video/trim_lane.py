"""트림 레인 위젯 — in/out 핸들 시각화 + 마우스 드래그 입력.

책임 경계:
- 자체 in/out 상태를 들고 있긴 하지만 검증/swap 은 안 함 (그건 PlayerControls 책임).
- 모델/플레이어를 모름. 외부 → set_*, 사용자 입력 → 시그널.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget


_LANE_HEIGHT = 36
_HANDLE_HALF_WIDTH = 4
_HANDLE_HIT_PAD = 8
_PAD_LEFT = 4
_PAD_RIGHT = 4

_BG_COLOR = QColor(40, 44, 52)
_SEL_COLOR = QColor(38, 198, 218, 200)
_HANDLE_FILL = QColor(255, 215, 64)
_HANDLE_BORDER = QColor(0, 0, 0, 220)
_PLAYHEAD_COLOR = QColor(229, 57, 53, 240)   # 빨강 — 시크바 통합 후 재생 헤드 변별성


class TrimLane(QWidget):
    """시크바와 동일 비율의 트림 레인. in/out 두 핸들 + 재생 헤드 표시."""

    in_changed = Signal(int)
    out_changed = Signal(int)
    seek_request = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(_LANE_HEIGHT)
        self.setMouseTracking(True)
        self._duration_ms = 0
        self._position_ms = 0
        self._in_ms: Optional[int] = None
        self._out_ms: Optional[int] = None
        self._dragging: Optional[str] = None
        self._filmstrip: list[QImage] = []

    # ---------- 외부 API ----------
    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, ms)
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, ms)
        self.update()

    def set_in_ms(self, ms: Optional[int]) -> None:
        self._in_ms = ms
        self.update()

    def set_out_ms(self, ms: Optional[int]) -> None:
        self._out_ms = ms
        self.update()

    def in_ms(self) -> Optional[int]:
        return self._in_ms

    def out_ms(self) -> Optional[int]:
        return self._out_ms

    def clear(self) -> None:
        self._in_ms = None
        self._out_ms = None
        self._dragging = None
        self.update()

    def set_filmstrip(self, images: list[QImage]) -> None:
        """N장 썸네일 배경 설정. 빈 리스트 → 검정 배경."""
        self._filmstrip = list(images)
        self.update()

    def has_filmstrip(self) -> bool:
        return bool(self._filmstrip)

    # ---------- 좌표 ↔ ms ----------
    def _lane_left_pad(self) -> int:
        return _PAD_LEFT

    def _lane_right_pad(self) -> int:
        return _PAD_RIGHT

    def _lane_width(self) -> int:
        return max(1, self.width() - self._lane_left_pad() - self._lane_right_pad())

    def _pixel_for_ms(self, ms: int) -> int:
        if self._duration_ms <= 0:
            return self._lane_left_pad()
        ratio = max(0.0, min(1.0, ms / self._duration_ms))
        return self._lane_left_pad() + int(round(ratio * self._lane_width()))

    def _ms_for_pixel(self, x: int) -> int:
        if self._duration_ms <= 0:
            return 0
        rel = x - self._lane_left_pad()
        rel = max(0, min(self._lane_width(), rel))
        return int(round(rel * self._duration_ms / self._lane_width()))

    # ---------- 그리기 ----------
    def paintEvent(self, _event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), _BG_COLOR)
        self._draw_filmstrip(p)

        if self._in_ms is not None and self._out_ms is not None:
            lo, hi = sorted((self._in_ms, self._out_ms))
            x_lo = self._pixel_for_ms(lo)
            x_hi = self._pixel_for_ms(hi)
            p.fillRect(x_lo, 0, max(0, x_hi - x_lo), self.height(), _SEL_COLOR)

        if self._duration_ms > 0:
            xp = self._pixel_for_ms(self._position_ms)
            p.setPen(QPen(_PLAYHEAD_COLOR, 2))
            p.drawLine(xp, 0, xp, self.height())

        if self._in_ms is not None:
            self._draw_handle(p, self._pixel_for_ms(self._in_ms), is_in=True)
        if self._out_ms is not None:
            self._draw_handle(p, self._pixel_for_ms(self._out_ms), is_in=False)

    def _draw_filmstrip(self, p: QPainter) -> None:
        if not self._filmstrip:
            return
        n = len(self._filmstrip)
        lane_w = self._lane_width()
        if lane_w <= 0 or n == 0:
            return
        x0 = self._lane_left_pad()
        h = self.height()
        # 각 썸네일이 차지하는 픽셀 폭 — 부동소수 누적으로 끝까지 lane 채움.
        for i, img in enumerate(self._filmstrip):
            if img.isNull():
                continue
            x_start = x0 + (i * lane_w) // n
            x_end = x0 + ((i + 1) * lane_w) // n
            w = x_end - x_start
            if w <= 0:
                continue
            target = self.rect()
            target.setX(x_start)
            target.setY(0)
            target.setWidth(w)
            target.setHeight(h)
            p.drawImage(target, img)

    def _draw_handle(self, p: QPainter, x: int, *, is_in: bool) -> None:
        rect_x = x - _HANDLE_HALF_WIDTH
        p.fillRect(rect_x, 0, 2 * _HANDLE_HALF_WIDTH, self.height(), _HANDLE_FILL)
        p.setPen(QPen(_HANDLE_BORDER, 2))
        p.drawRect(rect_x, 0, 2 * _HANDLE_HALF_WIDTH, self.height() - 1)
        if is_in:
            p.drawLine(rect_x + 1, 4, rect_x + 1, self.height() - 4)
        else:
            p.drawLine(rect_x + 2 * _HANDLE_HALF_WIDTH - 1, 4,
                       rect_x + 2 * _HANDLE_HALF_WIDTH - 1, self.height() - 4)

    # ---------- 마우스 드래그 ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        x = int(event.position().x())
        new_ms = self._ms_for_pixel(x)
        target = self._handle_at(x)
        if target is None:
            # 핸들 외 빈 공간 클릭 — 시크 (영상 위치 이동, in/out 안 건드림).
            self._dragging = "seek"
            self.seek_request.emit(new_ms)
            return
        self._dragging = target
        if target == "in":
            self._in_ms = new_ms
            self.in_changed.emit(new_ms)
        else:
            self._out_ms = new_ms
            self.out_changed.emit(new_ms)
        self.seek_request.emit(new_ms)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging is None:
            return
        x = int(event.position().x())
        new_ms = self._ms_for_pixel(x)
        if self._dragging == "seek":
            self.seek_request.emit(new_ms)
            return
        if self._dragging == "in":
            self._in_ms = new_ms
            self.in_changed.emit(new_ms)
        else:
            self._out_ms = new_ms
            self.out_changed.emit(new_ms)
        self.seek_request.emit(new_ms)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = None

    def _handle_at(self, x: int) -> Optional[str]:
        """클릭 좌표에서 어느 핸들을 잡았는지. 둘 다 있으면 가까운 쪽."""
        candidates: list[tuple[int, str]] = []
        if self._in_ms is not None:
            candidates.append((self._pixel_for_ms(self._in_ms), "in"))
        if self._out_ms is not None:
            candidates.append((self._pixel_for_ms(self._out_ms), "out"))
        candidates = [(px, t) for px, t in candidates
                      if abs(px - x) <= _HANDLE_HIT_PAD + _HANDLE_HALF_WIDTH]
        if not candidates:
            return None
        candidates.sort(key=lambda t: abs(t[0] - x))
        return candidates[0][1]
