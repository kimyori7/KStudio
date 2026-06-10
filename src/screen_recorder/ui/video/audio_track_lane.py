"""AudioTrackLane — 비디오 트랙 아래 읽기 전용 파형 레인 + 음소거 토글.

위치 계산은 video_track_lane.segment_h_rects 를 공유 → 썸네일과 가로 정렬 일치.
paint 는 peak 배열에서 직접 (미리 렌더한 이미지 X) → 줌/DPR 안전.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from ...effects.segment import VideoSegment
from .video_track_lane import _HEADER_WIDTH, segment_h_rects

_LANE_HEIGHT = 44
_BG = QColor(24, 24, 24)
_HEADER_BG = QColor(40, 40, 40)
_HEADER_FG = QColor(220, 220, 220)
_WAVE = QColor(90, 200, 250)          # 시안 파형
_WAVE_MUTED = QColor(90, 100, 110)    # 음소거 시 회색
_BASELINE = QColor(70, 70, 70)
_NOAUDIO_FG = QColor(150, 150, 150)


class AudioTrackLane(QWidget):
    """읽기 전용 파형 + 음소거 버튼. set_segments/set_duration_ms/set_peaks/set_muted."""

    mute_toggled = Signal(bool)     # 🔇 클릭 → 새 muted 상태
    seek_request = Signal(int)      # 본문 클릭 → 결합 ms (타임라인 seek)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(_LANE_HEIGHT)
        self._segments: list[VideoSegment] = []
        self._duration_ms = 0
        self._peaks: dict[str, list] = {}   # src → peaks ([] = 소리 없음)
        self._muted = False
        self._mute_btn = QPushButton("🔇", self)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFixedSize(28, 22)
        self._mute_btn.setToolTip("오디오 끄기 — 미리보기·내보내기 모두 무음")
        self._mute_btn.clicked.connect(self._on_mute_clicked)

    # ---------- public ----------
    def set_segments(self, segments: list[VideoSegment]) -> None:
        active = {s.src for s in segments}
        self._peaks = {k: v for k, v in self._peaks.items() if k in active}
        self._segments = list(segments)
        self.update()

    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, int(ms))
        self.update()

    def set_peaks(self, src: str, peaks: list) -> None:
        self._peaks[str(src)] = list(peaks)
        self.update()

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._mute_btn.setChecked(self._muted)
        self.update()

    # ---------- internal ----------
    def _total_duration_ms(self) -> int:
        seg_max = max((s.end_ms for s in self._segments), default=0)
        return max(self._duration_ms, seg_max)

    def _on_mute_clicked(self) -> None:
        self._muted = self._mute_btn.isChecked()
        self.update()
        self.mute_toggled.emit(self._muted)

    def resizeEvent(self, event) -> None:
        self._mute_btn.move((_HEADER_WIDTH - self._mute_btn.width()) // 2,
                            (self.height() - self._mute_btn.height()) // 2)
        super().resizeEvent(event)

    def _x_to_combined_ms(self, x: int) -> int:
        total = self._total_duration_ms()
        body_w = max(1, self.width() - _HEADER_WIDTH)
        rel = max(0, x - _HEADER_WIDTH)
        return int(round(rel * total / body_w))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and event.position().x() >= _HEADER_WIDTH:
            self.seek_request.emit(self._x_to_combined_ms(int(event.position().x())))
            event.accept()
            return
        super().mousePressEvent(event)

    # ---------- paint ----------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        p.fillRect(0, 0, _HEADER_WIDTH, self.height(), _HEADER_BG)
        p.setPen(_HEADER_FG)
        p.drawText(0, 0, _HEADER_WIDTH, self.height() // 2, Qt.AlignCenter, "소리")
        total = self._total_duration_ms()
        hrects = segment_h_rects(self._segments, total, self.width() - _HEADER_WIDTH)
        cy = self.height() // 2
        half = (self.height() - 8) // 2
        wave_color = _WAVE_MUTED if self._muted else _WAVE
        for r, seg in zip(hrects, self._segments):
            rect = QRect(r["x"], 4, r["w"], self.height() - 8)
            peaks = self._peaks.get(seg.src)
            if peaks is None:
                p.setPen(QPen(_BASELINE, 1))
                p.drawLine(rect.left(), cy, rect.right(), cy)
                continue
            if not peaks:
                p.setPen(QPen(_BASELINE, 1))
                p.drawLine(rect.left(), cy, rect.right(), cy)
                p.setPen(_NOAUDIO_FG)
                p.drawText(rect, Qt.AlignCenter, "소리 없음")
                continue
            self._draw_waveform(p, rect, seg, peaks, cy, half, wave_color)

    def _draw_waveform(self, p, rect, seg, peaks, cy, half, color) -> None:
        """segment 의 [src_in, src_out] 구간 peaks 를 채움형 대칭 파형으로."""
        if int(seg.src_duration_ms) <= 0:
            return   # 길이 미확정 segment — 파형 생략 (배경만)
        src_dur = max(1, int(seg.src_duration_ms))
        n = len(peaks)
        i0 = int(seg.src_in_ms / src_dur * n)
        src_out = int(seg.src_out_ms) if seg.src_out_ms > 0 else src_dur
        i1 = max(i0 + 1, int(src_out / src_dur * n))
        i0 = max(0, min(n - 1, i0))
        i1 = max(i0 + 1, min(n, i1))
        seg_peaks = peaks[i0:i1]
        if not seg_peaks:
            return
        p.setPen(QPen(color, 1))
        cols = max(1, rect.width())
        m = len(seg_peaks)
        for px in range(cols):
            idx = min(m - 1, int(px * m / cols))
            h = int(seg_peaks[idx] * half)
            x = rect.left() + px
            p.drawLine(x, cy - h, x, cy + h)
