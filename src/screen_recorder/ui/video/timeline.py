"""영상 timeline 통합 위젯 — 슬라이더·트림 마커·효과 lane 한 시간축 정렬.

VideoTimeline 은 컨테이너. TimelineSliderLane 은 본 task 에서 정의된 첫 줄.
TrimMarkerLane 은 Task 2, VideoTimeline 컨테이너는 Task 3 에서 정의.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from .effect_lane import _HEADER_WIDTH


_LANE_HEIGHT = 24
_BG_COLOR = QColor(40, 44, 52)
_HEADER_BG = QColor(30, 33, 39)
_HEADER_TEXT = QColor(180, 190, 200)
_TRACK_COLOR = QColor(70, 76, 86)
_PLAYHEAD_COLOR = QColor(229, 57, 53, 240)


class TimelineSliderLane(QWidget):
    """재생 슬라이더 한 줄 — 헤더(56) + 본체. ms↔x 는 EffectLane 과 동일 공식.

    custom-paint 으로 만드는 이유: QSlider 는 고유 padding/groove 가 있어
    EffectLane 본체 (x=56 시작) 와 픽셀 정렬이 안 맞는다. 같은 _ms_to_x 공식을
    쓰면 모든 lane 이 정확히 정렬된다.
    """

    seek_request = Signal(int)   # ms

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(_LANE_HEIGHT)
        self.setMouseTracking(True)
        self._duration_ms = 0
        self._position_ms = 0
        self._dragging = False

    # ---------- 외부 API ----------
    def header_width(self) -> int:
        return _HEADER_WIDTH

    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, int(ms))
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self.update()

    def duration_ms(self) -> int:
        return self._duration_ms

    def position_ms(self) -> int:
        return self._position_ms

    # ---------- 좌표 변환 (EffectLane 과 동일 공식) ----------
    def _body_width(self) -> int:
        return max(1, self.width() - _HEADER_WIDTH)

    def _pixel_for_ms(self, ms: int) -> int:
        if self._duration_ms <= 0:
            return _HEADER_WIDTH
        ratio = max(0.0, min(1.0, ms / self._duration_ms))
        return _HEADER_WIDTH + int(round(ratio * self._body_width()))

    def _ms_for_pixel(self, x: int) -> int:
        if self._duration_ms <= 0:
            return 0
        rel = max(0, min(self._body_width(), x - _HEADER_WIDTH))
        return int(round(rel * self._duration_ms / self._body_width()))

    # ---------- 그리기 ----------
    def paintEvent(self, _event: QPaintEvent) -> None:
        p = QPainter(self)
        # 헤더
        p.fillRect(0, 0, _HEADER_WIDTH, self.height(), _HEADER_BG)
        p.setPen(_HEADER_TEXT)
        p.drawText(6, 0, _HEADER_WIDTH - 8, self.height(),
                   Qt.AlignVCenter | Qt.AlignLeft, "▶ 재생")
        # 본체 배경
        p.fillRect(_HEADER_WIDTH, 0, self.width() - _HEADER_WIDTH, self.height(), _BG_COLOR)
        # 트랙 (가로 가운데 얇은 막대)
        track_y = self.height() // 2 - 2
        p.fillRect(_HEADER_WIDTH, track_y, self._body_width(), 4, _TRACK_COLOR)
        # 재생 헤드
        if self._duration_ms > 0:
            xp = self._pixel_for_ms(self._position_ms)
            p.setPen(QPen(_PLAYHEAD_COLOR, 2))
            p.drawLine(xp, 0, xp, self.height())

    # ---------- 마우스 ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        x = int(event.position().x())
        if x < _HEADER_WIDTH:
            return   # 헤더 영역은 시크 안 함
        self._dragging = True
        self.seek_request.emit(self._ms_for_pixel(x))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        x = int(event.position().x())
        self.seek_request.emit(self._ms_for_pixel(x))

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._dragging = False
