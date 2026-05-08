"""영상 timeline 통합 위젯 — 슬라이더·트림 마커·효과 lane 한 시간축 정렬.

VideoTimeline 은 컨테이너. TimelineSliderLane 은 본 task 에서 정의된 첫 줄.
TrimMarkerLane 은 Task 2, VideoTimeline 컨테이너는 Task 3 에서 정의.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...effects import Sidecar
from .effect_lane import _HEADER_WIDTH
from .effect_lanes_widget import EffectLanesWidget
from .trim_lane import TrimLane


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


class TrimMarkerLane(TrimLane):
    """자르기 in/out 마커 — TrimLane 베이스 + 헤더(56px) 추가.

    `_lane_left_pad` 만 56 으로 override. paintEvent 마지막에 헤더 영역을 덮어
    그리고 라벨(✂ 자르기)을 그린다. mouse 이벤트는 베이스 그대로 사용 (헤더
    영역 클릭은 자동으로 본체 좌표 < pad 가 되므로 seek/mark 영향 없음).
    """

    def _lane_left_pad(self) -> int:
        return _HEADER_WIDTH

    def _lane_right_pad(self) -> int:
        return 0

    def paintEvent(self, event: QPaintEvent) -> None:
        # 베이스가 본체 전체에 그린 뒤(필름스트립 포함), 위에 헤더만 덮어쓴다.
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(0, 0, _HEADER_WIDTH, self.height(), _HEADER_BG)
        p.setPen(_HEADER_TEXT)
        p.drawText(6, 0, _HEADER_WIDTH - 8, self.height(),
                   Qt.AlignVCenter | Qt.AlignLeft, "✂ 자르기")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # 헤더 클릭은 무시 (베이스의 ms_for_pixel 이 음수→0 으로 clamp 돼
        # 헤더 클릭만으로도 in 점 0 이 마크되는 부작용 방지).
        if int(event.position().x()) < _HEADER_WIDTH:
            return
        super().mousePressEvent(event)


class VideoTimeline(QWidget):
    """슬라이더·트림·효과 5종 lane 을 한 시간축으로 묶은 컨테이너.

    OFF: 슬라이더만 보임. ON: 7줄 모두 보임.
    """

    seek_request = Signal(int)              # ms — slider/trim 어디서든 시크
    trim_changed = Signal(int, int)         # (in_ms, out_ms) — drag 후 (swap 적용)
    request_add = Signal(str, int)          # (effect_type, ms)
    effect_selected = Signal(object)        # Effect | None
    effect_changed = Signal(object)         # Effect
    effect_deleted = Signal(str)            # effect_id

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.slider_lane = TimelineSliderLane()
        self.trim_marker_lane = TrimMarkerLane()
        self.effect_lanes = EffectLanesWidget()

        layout.addWidget(self.slider_lane)
        layout.addWidget(self.trim_marker_lane)
        layout.addWidget(self.effect_lanes)

        # ---- 시그널 fan-in ----
        self.slider_lane.seek_request.connect(self.seek_request.emit)
        self.trim_marker_lane.seek_request.connect(self.seek_request.emit)
        self.trim_marker_lane.in_changed.connect(self._on_trim_in_changed)
        self.trim_marker_lane.out_changed.connect(self._on_trim_out_changed)
        self.effect_lanes.request_add.connect(self.request_add.emit)
        self.effect_lanes.effect_selected.connect(self.effect_selected.emit)
        self.effect_lanes.effect_changed.connect(self.effect_changed.emit)
        self.effect_lanes.effect_deleted.connect(self.effect_deleted.emit)

        # 초기엔 OFF — 슬라이더만 보임
        self.trim_marker_lane.hide()
        self.effect_lanes.hide()

    # ---------- 외부 API ----------
    def set_duration_ms(self, ms: int) -> None:
        ms = max(0, int(ms))
        self.slider_lane.set_duration_ms(ms)
        self.trim_marker_lane.set_duration_ms(ms)
        self.effect_lanes.set_duration_ms(ms)

    def set_position_ms(self, ms: int) -> None:
        ms = max(0, int(ms))
        self.slider_lane.set_position_ms(ms)
        self.trim_marker_lane.set_position_ms(ms)
        self.effect_lanes.set_position_ms(ms)

    def set_sidecar(self, sidecar: Sidecar) -> None:
        self.effect_lanes.set_sidecar(sidecar)
        # trim 도 사이드카에서 가져와 표시
        t = sidecar.trim
        in_ms = t.in_ms if t.in_ms > 0 else None
        out_ms = t.out_ms if t.out_ms > 0 else None
        self.trim_marker_lane.set_in_ms(in_ms)
        self.trim_marker_lane.set_out_ms(out_ms)

    def set_trim(self, in_ms: int | None, out_ms: int | None) -> None:
        """외부에서 트림 표시값을 직접 갱신 (사이드카 흐름 외)."""
        self.trim_marker_lane.set_in_ms(in_ms)
        self.trim_marker_lane.set_out_ms(out_ms)

    def set_edit_mode(self, on: bool) -> None:
        self.trim_marker_lane.setVisible(on)
        self.effect_lanes.setVisible(on)

    # ---------- 내부 ----------
    def _on_trim_in_changed(self, ms: int) -> None:
        cur_out = self.trim_marker_lane.out_ms()
        in_ms, out_ms = self._normalized(ms, cur_out)
        self.trim_marker_lane.set_in_ms(in_ms)
        self.trim_marker_lane.set_out_ms(out_ms)
        # 시그널은 int (0 = 마커 없음 — Sidecar.trim 의 0/0 sentinel 과 일관).
        self.trim_changed.emit(
            in_ms if in_ms is not None else 0,
            out_ms if out_ms is not None else 0,
        )

    def _on_trim_out_changed(self, ms: int) -> None:
        cur_in = self.trim_marker_lane.in_ms()
        in_ms, out_ms = self._normalized(cur_in, ms)
        self.trim_marker_lane.set_in_ms(in_ms)
        self.trim_marker_lane.set_out_ms(out_ms)
        self.trim_changed.emit(
            in_ms if in_ms is not None else 0,
            out_ms if out_ms is not None else 0,
        )

    @staticmethod
    def _normalized(in_ms: int | None, out_ms: int | None) -> tuple[int | None, int | None]:
        """둘 다 있으면 swap, 한쪽만 있으면 그대로."""
        if in_ms is not None and out_ms is not None and out_ms < in_ms:
            return out_ms, in_ms
        return in_ms, out_ms
