"""VideoTrackLane — 필름스트립 (segment 별 썸네일 박스) + 좌클릭 선택.

Stage A: 표시 + 선택만. 자르기/드래그/삭제/드롭은 Stage B.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QContextMenuEvent, QDragEnterEvent, QDragMoveEvent,
    QDropEvent, QImage, QMouseEvent, QPainter, QPen,
)
from PySide6.QtWidgets import QMenu, QWidget

from ...effects.segment import VideoSegment


_HEADER_WIDTH = 56     # effect lane 들과 일관 — 좌측에 라벨 자리.
_BOX_HEIGHT = 50
_BOX_GAP = 2
_BG_COLOR = QColor(30, 30, 30)
_BOX_FILL = QColor(60, 80, 110)
_BOX_BORDER = QColor(120, 140, 170)
_SELECTED_BORDER = QColor(255, 255, 255)
_HEADER_BG = QColor(40, 40, 40)
_HEADER_FG = QColor(220, 220, 220)
_DURATION_FG = QColor(230, 230, 230)
_DURATION_BG = QColor(0, 0, 0, 140)


class VideoTrackLane(QWidget):
    """비디오 트랙 lane — segment 들을 가로로 이어붙인 필름스트립.

    Stage A 능력:
    - segment 마다 썸네일 박스 그림 (없으면 회색 placeholder)
    - 좌클릭으로 선택 → segment_selected 시그널
    - set_selected_id / set_duration_ms / set_segments / set_thumbnail public API
    """

    segment_selected = Signal(str)      # segment id
    # Stage B: 우클릭 메뉴 시그널들.
    request_split = Signal(str, int)        # (segment_id, at_local_ms)
    request_delete = Signal(str)            # segment_id
    request_insert_at = Signal(int)         # at_idx (segment 사이 또는 끝)
    request_insert_files = Signal(list, int)   # (paths: list[str], at_idx) — 드래그-드롭

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(_BOX_HEIGHT + 8)
        self.setAcceptDrops(True)   # 외부 / 라이브러리 드래그-드롭 활성화
        self._segments: list[VideoSegment] = []
        self._duration_ms: int = 0
        self._selected_id: Optional[str] = None
        self._thumbnails: dict[str, QImage] = {}
        self._pending_select: Optional[str] = None
        # 마지막 popup 한 메뉴 — 테스트 검사용 (UI 흐름엔 필수 아님).
        self._last_menu: Optional[QMenu] = None
        # 드롭 indicator x 좌표 — None 이면 안 그림.
        self._drop_indicator_x: Optional[int] = None

    # ---------- public API ----------
    def set_segments(self, segments: list[VideoSegment]) -> None:
        self._segments = list(segments)
        self.update()

    def set_duration_ms(self, ms: int) -> None:
        """결합 시간축 총 길이. 0 이면 segment 들의 duration 합 사용."""
        self._duration_ms = max(0, int(ms))
        self.update()

    def set_selected_id(self, sid: Optional[str]) -> None:
        self._selected_id = sid
        self.update()

    def set_thumbnail(self, segment_id: str, img: QImage) -> None:
        """ThumbnailExtractor 추출 완료 후 호출."""
        self._thumbnails[segment_id] = img
        self.update()

    def segments(self) -> list[VideoSegment]:
        return list(self._segments)

    # ---------- internal ----------
    def _total_duration_ms(self) -> int:
        if self._duration_ms > 0:
            return self._duration_ms
        return sum(max(0, s.duration_ms) for s in self._segments)

    def _segment_rects(self) -> list[dict]:
        """각 segment 의 화면 좌표 rect 와 id. 좌→우 순서. 헤더 폭 제외."""
        total = self._total_duration_ms()
        if total <= 0 or not self._segments:
            return []
        body_w = max(1, self.width() - _HEADER_WIDTH)
        out: list[dict] = []
        cursor_ms = 0
        y = (self.height() - _BOX_HEIGHT) // 2
        for seg in self._segments:
            dur = max(0, seg.duration_ms)
            x = _HEADER_WIDTH + int(round(cursor_ms * body_w / total))
            w = int(round(dur * body_w / total)) - _BOX_GAP
            w = max(1, w)
            out.append({
                "id": seg.id,
                "rect": QRect(x, y, w, _BOX_HEIGHT),
                "duration_ms": dur,
            })
            cursor_ms += dur
        return out

    # ---------- paint ----------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), _BG_COLOR)
        # 헤더
        p.fillRect(0, 0, _HEADER_WIDTH, self.height(), _HEADER_BG)
        p.setPen(_HEADER_FG)
        p.drawText(0, 0, _HEADER_WIDTH, self.height(),
                   Qt.AlignCenter, "영상")
        for box in self._segment_rects():
            r = box["rect"]
            sid = box["id"]
            thumb = self._thumbnails.get(sid)
            if thumb is not None and not thumb.isNull():
                # KeepAspectRatioByExpanding 으로 확대 + 중앙 crop.
                scaled = thumb.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation)
                ox = max(0, (scaled.width() - r.width()) // 2)
                oy = max(0, (scaled.height() - r.height()) // 2)
                src = QRect(ox, oy, r.width(), r.height())
                p.drawImage(r, scaled, src)
            else:
                p.fillRect(r, _BOX_FILL)
            # 외곽선 — 선택된 segment 는 굵은 흰색.
            if sid == self._selected_id:
                pen = QPen(_SELECTED_BORDER)
                pen.setWidth(3)
            else:
                pen = QPen(_BOX_BORDER)
                pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            # duration 라벨 (좌하단).
            self._draw_duration_label(p, r, box["duration_ms"])
        # 드롭 indicator (수직 흰 선) — drag-drop 중에만 그림.
        if self._drop_indicator_x is not None:
            pen = QPen(QColor(255, 255, 255, 230))
            pen.setWidth(3)
            p.setPen(pen)
            ix = self._drop_indicator_x
            p.drawLine(ix, 4, ix, self.height() - 4)

    def _draw_duration_label(self, p: QPainter, r: QRect, dur_ms: int) -> None:
        secs = dur_ms / 1000.0
        text = f"{secs:.1f}s"
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad = 3
        # 좌하단.
        bx = r.left() + 2
        by = r.bottom() - th - 2
        p.fillRect(bx, by, tw + pad * 2, th + pad, _DURATION_BG)
        p.setPen(_DURATION_FG)
        p.drawText(bx + pad, by, tw + pad, th + pad,
                   Qt.AlignVCenter | Qt.AlignLeft, text)

    # ---------- mouse ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        for box in self._segment_rects():
            if box["rect"].contains(pos):
                self._pending_select = box["id"]
                event.accept()
                return
        self._pending_select = None
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        sid = self._pending_select
        if sid is not None and event.button() == Qt.LeftButton:
            self._pending_select = None
            self.set_selected_id(sid)
            self.segment_selected.emit(sid)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------- context menu (Stage B) ----------
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        pos = event.pos()
        boxes = self._segment_rects()
        # segment 위에서 우클릭인지 확인.
        hit = next((b for b in boxes if b["rect"].contains(pos)), None)
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose, True)
        if hit is not None:
            sid = hit["id"]
            seg = next((s for s in self._segments if s.id == sid), None)
            if seg is None:
                return
            # 클릭 x 좌표 → segment-local ms 변환.
            local_ms = self._x_to_segment_local_ms(pos.x(), hit["rect"], seg)
            split_action = QAction("✂ 여기서 자르기", menu)
            split_action.triggered.connect(
                lambda _checked=False, s=sid, m=local_ms: self.request_split.emit(s, m)
            )
            menu.addAction(split_action)
            menu.addSeparator()
            del_action = QAction("🗑 삭제", menu)
            del_action.triggered.connect(
                lambda _checked=False, s=sid: self.request_delete.emit(s)
            )
            menu.addAction(del_action)
        else:
            # 빈 영역 — 클릭 위치에서 가장 가까운 segment 사이의 idx 계산.
            insert_idx = self._x_to_insert_index(pos.x(), boxes)
            insert_action = QAction("➕ 영상 파일 삽입…", menu)
            insert_action.triggered.connect(
                lambda _checked=False, i=insert_idx: self.request_insert_at.emit(i)
            )
            menu.addAction(insert_action)
        self._last_menu = menu
        menu.popup(event.globalPos())

    def _x_to_segment_local_ms(self, x: int, rect: QRect, seg: VideoSegment) -> int:
        """클릭 x → segment 안 local ms (0 ~ duration_ms)."""
        if rect.width() <= 0:
            return 0
        rel = max(0, min(rect.width(), x - rect.left()))
        return int(round(rel * seg.duration_ms / rect.width()))

    def _x_to_insert_index(self, x: int, boxes: list[dict]) -> int:
        """클릭 x 좌표 → 어느 idx 위치에 삽입할지. boxes 의 사이/끝."""
        for i, b in enumerate(boxes):
            r = b["rect"]
            if x < r.left():
                return i
            if r.contains(x, r.center().y()):
                return i + 1
        return len(boxes)

    # ---------- drag-drop (Stage B Task B5) ----------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        event.acceptProposedAction()
        x = int(event.position().x())
        boxes = self._segment_rects()
        # drop indicator 위치 — insert 인덱스 기준 사각형 사이.
        idx = self._x_to_insert_index(x, boxes)
        if idx <= 0:
            ind_x = boxes[0]["rect"].left() if boxes else _HEADER_WIDTH
        elif idx >= len(boxes):
            ind_x = (boxes[-1]["rect"].right() + 1) if boxes else _HEADER_WIDTH
        else:
            ind_x = boxes[idx]["rect"].left()
        self._drop_indicator_x = ind_x
        self.update()

    def dragLeaveEvent(self, event) -> None:
        self._drop_indicator_x = None
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            event.ignore()
            return
        x = int(event.position().x())
        boxes = self._segment_rects()
        idx = self._x_to_insert_index(x, boxes)
        self._drop_indicator_x = None
        self.update()
        event.acceptProposedAction()
        self.request_insert_files.emit(paths, idx)
