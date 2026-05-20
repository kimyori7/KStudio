"""영상 timeline 통합 위젯 — 슬라이더·트림 마커·효과 lane 한 시간축 정렬.

VideoTimeline 은 컨테이너. TimelineSliderLane 은 본 task 에서 정의된 첫 줄.
TrimMarkerLane 은 Task 2, VideoTimeline 컨테이너는 Task 3 에서 정의.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ...effects import Sidecar
from .effect_lane import _HEADER_WIDTH
from .effect_lanes_widget import EffectLanesWidget
from .trim_lane import TrimLane
from .video_track_lane import VideoTrackLane


_LANE_HEIGHT = 24
_BG_COLOR = QColor(40, 44, 52)
_HEADER_BG = QColor(30, 33, 39)
_HEADER_TEXT = QColor(180, 190, 200)
_TRACK_COLOR = QColor(70, 76, 86)
_PLAYHEAD_COLOR = QColor(229, 57, 53, 240)


class _PlayheadOverlay(QWidget):
    """전체 timeline 을 가로지르는 수직 playhead 가이드 라인.

    자식 lane 들 위에 그려야 해서 별도 transparent overlay. 헤더 영역 (왼쪽
    56px) 은 라벨 자리라 그리지 않음. 슬라이더 lane 도 자체 빨간선을 그리지만
    두께·색이 같아 자연스럽게 합쳐짐. 사용자 의도: "재생 빨간 세로 줄을 밑에
    편집 기능의 기준점이 되게 길게 이어지게."
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._position_ms = 0
        self._duration_ms = 0

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self.update()

    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, int(ms))
        self.update()

    def position_x(self) -> int:
        """현재 playhead 의 x 좌표 (overlay 의 좌표계). duration 0 이면 헤더 끝."""
        if self._duration_ms <= 0:
            return _HEADER_WIDTH
        body_w = max(1, self.width() - _HEADER_WIDTH)
        ratio = max(0.0, min(1.0, self._position_ms / self._duration_ms))
        return _HEADER_WIDTH + int(round(ratio * body_w))

    def paintEvent(self, _event: QPaintEvent) -> None:
        if self._duration_ms <= 0:
            return
        x = self.position_x()
        p = QPainter(self)
        p.setPen(QPen(_PLAYHEAD_COLOR, 2))
        p.drawLine(x, 0, x, self.height())


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
                   Qt.AlignVCenter | Qt.AlignLeft, "✂ 자르기 (양끝)")

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
    request_add = Signal(str, int, int)     # (effect_type, ms, track_idx)
    # 2026-05-20: (effect_type, track_idx, new_enabled) — row 별 활성/비활성 토글.
    request_toggle_row_enabled = Signal(str, int, bool)
    effect_selected = Signal(object)        # Effect | None
    effect_changed = Signal(object)         # Effect
    effect_deleted = Signal(str)            # effect_id

    # 가로 줌 — 1.0 = fit-to-window, > 1 = 확대 (가로 스크롤 발생). Ctrl+휠 로 조정.
    _ZOOM_MIN = 1.0
    _ZOOM_MAX = 20.0
    _ZOOM_STEP = 1.25   # 휠 한 칸당 배수

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 두 영역 분리:
        # - sticky_top: 슬라이더(재생) + 영상 트랙. 항상 위에 고정 (vertical scroll 영향 없음).
        # - bottom_scroll: 효과 lane 들. 라인 수가 많으면 vertical scroll, 타임라인이
        #   세로로 커지면 lane 들은 fixed-height 유지하고 하단에 빈 공간 자람.
        # 두 영역 모두 같은 가로 줌 폭을 가지므로 horizontal scroll 은 동기화한다.

        # ---- sticky_top — 슬라이더 + 영상 트랙 (vertical 스크롤 외) ----
        self._top_inner = QWidget()
        top_layout = QVBoxLayout(self._top_inner)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.slider_lane = TimelineSliderLane()
        self.trim_marker_lane = TrimMarkerLane()
        self.trim_marker_lane.setParent(self)
        self.trim_marker_lane.hide()
        self.video_track_lane = VideoTrackLane()

        top_layout.addWidget(self.slider_lane)
        top_layout.addWidget(self.video_track_lane)

        self._top_scroll = QScrollArea()
        self._top_scroll.setWidgetResizable(True)
        self._top_scroll.setFrameShape(QScrollArea.NoFrame)
        self._top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._top_scroll.setWidget(self._top_inner)
        # sticky 영역은 자기 자체의 sizeHint 에 맞춰 고정 — top_inner 의 자식이 모두
        # fixed/Minimum 높이라 sizeHint 가 잘 잡힘.
        self._top_scroll.setSizePolicy(self._top_scroll.sizePolicy().horizontalPolicy(),
                                       self._top_scroll.sizePolicy().verticalPolicy())
        self._top_scroll.setFixedHeight(0)   # showEvent 에서 sizeHint 로 갱신.

        # ---- bottom_inner — 효과 lane 들 (vertical+horizontal scroll) ----
        self._bottom_inner = QWidget()
        bottom_layout = QVBoxLayout(self._bottom_inner)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        self.effect_lanes = EffectLanesWidget()
        bottom_layout.addWidget(self.effect_lanes)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # lane 이 많아 세로 overflow 가 가능 — AsNeeded 로 변경 (이전 AlwaysOff).
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setWidget(self._bottom_inner)

        outer.addWidget(self._top_scroll)
        outer.addWidget(self._scroll, stretch=1)

        # 두 scroll area 의 가로 스크롤 동기화 — bottom 이 권위 있는 source.
        # bottom 가 가로 스크롤 가능 (overflow), top 은 스크롤바 숨김 상태로 같은 값 추종.
        self._scroll.horizontalScrollBar().valueChanged.connect(
            self._sync_top_h_scroll
        )

        self._zoom_factor: float = 1.0

        # ---- Playhead 수직 가이드 (전체 lane 관통) ----
        # top + bottom 둘 다 같은 시간축이지만 영역이 분리됐으므로 overlay 도 분리.
        # bottom 의 inner 자식으로 만들면 가로 스크롤·세로 스크롤 모두 자동 추종.
        self.playhead_overlay = _PlayheadOverlay(self._bottom_inner)
        self.playhead_overlay.raise_()
        self._bottom_inner.installEventFilter(self)
        # top 용 overlay — slider 가 자체 playhead 를 그리므로 추가 그리기 불필요. 그러나
        # video_track_lane 위에는 빨간 세로선이 있어야 시각 기준점. 별도 overlay 인스턴스.
        self.playhead_top_overlay = _PlayheadOverlay(self._top_inner)
        self.playhead_top_overlay.raise_()
        self._top_inner.installEventFilter(self)

        # ---- 시그널 fan-in ----
        self.slider_lane.seek_request.connect(self.seek_request.emit)
        self.trim_marker_lane.seek_request.connect(self.seek_request.emit)
        self.trim_marker_lane.in_changed.connect(self._on_trim_in_changed)
        self.trim_marker_lane.out_changed.connect(self._on_trim_out_changed)
        self.effect_lanes.request_add.connect(self.request_add.emit)
        self.effect_lanes.request_toggle_row_enabled.connect(
            self.request_toggle_row_enabled.emit
        )
        self.effect_lanes.effect_selected.connect(self.effect_selected.emit)
        self.effect_lanes.effect_changed.connect(self.effect_changed.emit)
        self.effect_lanes.effect_deleted.connect(self.effect_deleted.emit)

        # 초기엔 OFF — 슬라이더만 보임
        self.trim_marker_lane.hide()
        self.video_track_lane.hide()
        self.effect_lanes.hide()

    # ---------- 외부 API ----------
    def set_duration_ms(self, ms: int) -> None:
        ms = max(0, int(ms))
        self.slider_lane.set_duration_ms(ms)
        self.trim_marker_lane.set_duration_ms(ms)
        self.video_track_lane.set_duration_ms(ms)
        self.effect_lanes.set_duration_ms(ms)
        self.playhead_overlay.set_duration_ms(ms)
        self.playhead_top_overlay.set_duration_ms(ms)

    def set_position_ms(self, ms: int) -> None:
        ms = max(0, int(ms))
        self.slider_lane.set_position_ms(ms)
        self.trim_marker_lane.set_position_ms(ms)
        self.effect_lanes.set_position_ms(ms)
        self.playhead_overlay.set_position_ms(ms)
        self.playhead_top_overlay.set_position_ms(ms)

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Resize:
            if watched is self._bottom_inner:
                self.playhead_overlay.setGeometry(self._bottom_inner.rect())
                self.playhead_overlay.raise_()
            elif watched is self._top_inner:
                self.playhead_top_overlay.setGeometry(self._top_inner.rect())
                self.playhead_top_overlay.raise_()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_zoom_width()
        self._sync_top_height()
        self.playhead_overlay.setGeometry(self._bottom_inner.rect())
        self.playhead_overlay.raise_()
        self.playhead_top_overlay.setGeometry(self._top_inner.rect())
        self.playhead_top_overlay.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_zoom_width()
        self._sync_top_height()
        self.playhead_overlay.setGeometry(self._bottom_inner.rect())
        self.playhead_overlay.raise_()
        self.playhead_top_overlay.setGeometry(self._top_inner.rect())
        self.playhead_top_overlay.raise_()

    def _sync_top_height(self) -> None:
        """sticky_top 영역의 높이를 자식 sizeHint 합으로 — splitter 가 늘어나도 stretch 안 됨."""
        h = self._top_inner.sizeHint().height()
        if h <= 0:
            h = self.slider_lane.height() + self.video_track_lane.height()
        self._top_scroll.setFixedHeight(max(1, h))

    def _sync_top_h_scroll(self, value: int) -> None:
        """bottom 의 가로 스크롤 값을 top 도 동일하게 이동 — 같은 시간축 정렬."""
        # top scroll 의 viewport 가 콘텐츠보다 작아질 수 있으므로 max clamp.
        bar = self._top_scroll.horizontalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), int(value))))

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl + 휠 = 가로 줌 in/out. Ctrl 없으면 부모로 전달 (스크롤 등)."""
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() / 120.0   # 한 칸 = 120
            if steps == 0:
                event.ignore()
                return
            # 줌 중심 — 마우스 커서의 콘텐츠 비례 위치 보존.
            viewport = self._scroll.viewport()
            mouse_x_in_viewport = event.position().x()
            scroll_x = self._scroll.horizontalScrollBar().value()
            content_x = scroll_x + int(mouse_x_in_viewport)
            old_inner_w = max(1, self._bottom_inner.width())
            ratio = content_x / old_inner_w
            # 새 줌.
            factor = self._zoom_factor * (self._ZOOM_STEP ** steps)
            factor = max(self._ZOOM_MIN, min(self._ZOOM_MAX, factor))
            if abs(factor - self._zoom_factor) < 1e-3:
                event.accept()
                return
            self._zoom_factor = factor
            self._apply_zoom_width()
            # 줌 후 콘텐츠 너비 재계산 → 마우스 위치가 같은 비율을 가리키도록 스크롤.
            new_inner_w = max(1, self._bottom_inner.width())
            new_content_x = ratio * new_inner_w
            new_scroll = int(new_content_x - mouse_x_in_viewport)
            self._scroll.horizontalScrollBar().setValue(new_scroll)
            event.accept()
            return
        super().wheelEvent(event)

    def set_zoom_factor(self, factor: float) -> None:
        """API — 외부에서 줌 배율 지정. Ctrl+휠 와 동일."""
        self._zoom_factor = max(self._ZOOM_MIN, min(self._ZOOM_MAX, float(factor)))
        self._apply_zoom_width()

    def zoom_factor(self) -> float:
        return self._zoom_factor

    def _apply_zoom_width(self) -> None:
        """두 inner 의 minimum width 를 viewport_w × zoom_factor 로 — viewport 보다 크면 가로 스크롤.

        bottom 이 권위 source. top 은 같은 너비를 따라가야 시간축이 정렬.
        """
        if not hasattr(self, "_scroll"):
            return
        vp_w = self._scroll.viewport().width()
        target = int(vp_w * self._zoom_factor)
        if target <= 0:
            return
        if self._zoom_factor <= 1.0 + 1e-3:
            self._bottom_inner.setMinimumWidth(0)
            self._top_inner.setMinimumWidth(0)
        else:
            self._bottom_inner.setMinimumWidth(target)
            self._top_inner.setMinimumWidth(target)
        self.playhead_overlay.setGeometry(self._bottom_inner.rect())
        self.playhead_overlay.raise_()
        self.playhead_top_overlay.setGeometry(self._top_inner.rect())
        self.playhead_top_overlay.raise_()

    def set_sidecar(self, sidecar: Sidecar) -> None:
        self.effect_lanes.set_sidecar(sidecar)
        # video_track 표시 갱신.
        self.video_track_lane.set_segments(sidecar.video_track)
        # trim 도 사이드카에서 가져와 표시 (Stage D 에서 제거 예정).
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
        # 편집 모드 OFF — VideoTimeline 통째로 숨김. splitter 가 player 에 전체 공간 양보 →
        # 일반 영상 플레이어처럼 보임. 사용자 의도: "편집 모드 끄면 일반 플레이어처럼
        # 보이게 바도 내려가게."
        # trim_marker_lane 은 Stage D 에서 layout 에서 제외됨 (segment 트랙으로 흡수).
        # parent 없는 widget 이라 setVisible(True) 하면 별도 top-level 창으로 떠 버리는 회귀.
        # → 토글 대상에서 빼고 영구히 숨김 유지.
        self.video_track_lane.setVisible(on)
        self.effect_lanes.setVisible(on)
        # 편집 OFF 시 top_scroll(슬라이더+영상바) + bottom_scroll(효과 lanes) 모두 hide.
        # ON 시 top_scroll 만 노출 (effect_lanes 자체는 ON 분기에서 다시 visible).
        self._top_scroll.setVisible(on)
        self._scroll.setVisible(on)
        # sticky_top 영역에 video_track 이 추가/제거되므로 높이 갱신.
        self._sync_top_height()

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
