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
# 필름스트립 — segment 길이 기반 고정 슬롯 (박스 폭 무관). 박스 폭이 바뀌어도 cache 가
# 유효해 미리보기 깜빡임/사라짐 방지. 1초 = 1슬롯, min 1, max 32.
_FILMSTRIP_SLOT_INTERVAL_MS = 1000
_FILMSTRIP_MAX_SLOTS = 32
_FILMSTRIP_MIN_SLOTS = 1
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
    request_insert_at = Signal(int)         # at_combined_ms (트랙상 시작 위치)
    request_insert_files = Signal(list, int)   # (paths: list[str], at_combined_ms) — 드래그-드롭
    segment_moved = Signal(int, int)        # (from_idx, to_idx) — 레거시 (현재 미사용)
    segment_position_changed = Signal(str, int)   # (segment_id, new_start_ms) — Stage 1 자유 이동

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(_BOX_HEIGHT + 8)
        self.setAcceptDrops(True)   # 외부 / 라이브러리 드래그-드롭 활성화
        self._segments: list[VideoSegment] = []
        self._duration_ms: int = 0
        self._selected_id: Optional[str] = None
        # 필름스트립 썸네일 — (segment_id, src_ms) → QImage. 한 segment 안에서 여러
        # 시점의 컷을 보유하면서 박스 폭에 맞춰 타일 디스플레이.
        self._thumbnails: dict[tuple[str, int], QImage] = {}
        self._pending_select: Optional[str] = None
        # 마지막 popup 한 메뉴 — 테스트 검사용 (UI 흐름엔 필수 아님).
        self._last_menu: Optional[QMenu] = None
        # 드롭 indicator x 좌표 — None 이면 안 그림.
        self._drop_indicator_x: Optional[int] = None
        # 자유 이동 드래그 상태.
        self._reorder_drag_id: Optional[str] = None
        self._reorder_press_x: int = 0
        self._reorder_started: bool = False
        self._reorder_orig_start_ms: int = 0
        self._reorder_preview_start_ms: int = 0

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

    def set_thumbnail(self, segment_id: str, src_ms: int, img: QImage) -> None:
        """필름스트립 한 슬롯 썸네일 도착. (segment_id, src_ms) 별 캐시."""
        self._thumbnails[(segment_id, int(src_ms))] = img
        self.update()

    def thumbnail_slots_for(self, seg: VideoSegment, width_px: int = 0) -> list[int]:
        """segment 길이 기반 고정 src ms 슬롯들 (박스 width 무관).

        width_px 인자는 호환을 위해 유지하나 현재는 사용 안 함. dur / 1000ms 단위로
        고정 — 박스 폭이 바뀌어 paint 가 재호출돼도 cache 가 유효해 깜빡임 없음.
        """
        dur = max(1, seg.duration_ms)
        n = max(_FILMSTRIP_MIN_SLOTS,
                min(_FILMSTRIP_MAX_SLOTS,
                    int(round(dur / _FILMSTRIP_SLOT_INTERVAL_MS))))
        slots: list[int] = []
        for i in range(n):
            local_ms = int(round((i + 0.5) * dur / n))
            src_ms = int(seg.src_in_ms) + local_ms
            slots.append(src_ms)
        return slots

    def segments(self) -> list[VideoSegment]:
        return list(self._segments)

    # ---------- internal ----------
    def _total_duration_ms(self) -> int:
        """결합 시간축 총 길이 — segment 들의 max end_ms 와 외부 set_duration_ms 의 큰 값."""
        seg_max = max((s.end_ms for s in self._segments), default=0)
        return max(self._duration_ms, seg_max)

    def _segment_rects(self) -> list[dict]:
        """각 segment 의 화면 좌표 rect 와 id. start_ms 기반 (갭 지원). 헤더 폭 제외."""
        total = self._total_duration_ms()
        if total <= 0 or not self._segments:
            return []
        body_w = max(1, self.width() - _HEADER_WIDTH)
        out: list[dict] = []
        y = (self.height() - _BOX_HEIGHT) // 2
        for seg in self._segments:
            dur = max(0, seg.duration_ms)
            x = _HEADER_WIDTH + int(round(seg.start_ms * body_w / total))
            w = int(round(dur * body_w / total)) - _BOX_GAP
            w = max(1, w)
            out.append({
                "id": seg.id,
                "rect": QRect(x, y, w, _BOX_HEIGHT),
                "duration_ms": dur,
                "start_ms": seg.start_ms,
            })
        return out

    def _x_to_combined_ms(self, x: int) -> int:
        """x 좌표 → 결합 시간축 ms. 헤더 보정 + 음수 clamp."""
        total = self._total_duration_ms()
        body_w = max(1, self.width() - _HEADER_WIDTH)
        rel = max(0, x - _HEADER_WIDTH)
        return int(round(rel * total / body_w))

    # ---------- paint ----------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), _BG_COLOR)
        # 헤더
        p.fillRect(0, 0, _HEADER_WIDTH, self.height(), _HEADER_BG)
        p.setPen(_HEADER_FG)
        p.drawText(0, 0, _HEADER_WIDTH, self.height(),
                   Qt.AlignCenter, "영상")
        # 드래그 중인 박스는 임시 position 으로 표시.
        boxes = self._segment_rects()
        if self._reorder_drag_id is not None and self._reorder_started:
            total = self._total_duration_ms()
            body_w = max(1, self.width() - _HEADER_WIDTH)
            for box in boxes:
                if box["id"] == self._reorder_drag_id:
                    new_x = _HEADER_WIDTH + int(round(
                        self._reorder_preview_start_ms * body_w / total
                    ))
                    r0 = box["rect"]
                    box["rect"] = QRect(new_x, r0.top(), r0.width(), r0.height())
                    box["start_ms"] = self._reorder_preview_start_ms
                    break
        for box in boxes:
            r = box["rect"]
            sid = box["id"]
            seg = next((s for s in self._segments if s.id == sid), None)
            self._draw_filmstrip(p, r, seg)
            # 외곽선 — 선택된 segment 는 굵은 흰색. 드래그 중인 박스도 강조.
            if sid == self._selected_id or sid == self._reorder_drag_id:
                pen = QPen(_SELECTED_BORDER)
                pen.setWidth(3)
            else:
                pen = QPen(_BOX_BORDER)
                pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            self._draw_duration_label(p, r, box["duration_ms"])
        # 드롭 indicator (수직 흰 선) — drag-drop 중에만 그림.
        if self._drop_indicator_x is not None:
            pen = QPen(QColor(255, 255, 255, 230))
            pen.setWidth(3)
            p.setPen(pen)
            ix = self._drop_indicator_x
            p.drawLine(ix, 4, ix, self.height() - 4)

    def _draw_filmstrip(self, p: QPainter, r: QRect, seg: Optional[VideoSegment]) -> None:
        """박스 r 안에 segment 의 여러 시점 썸네일을 가로 타일로 그림.

        타일 수 = max(1, r.width() // ~80)  — 시각적으로 보이는 타일은 박스 폭 따라
        가변. 각 타일에는 segment 의 그 위치(local ms ratio) 에 가장 가까운 캐시
        썸네일을 가져와 표시. 슬롯 자체는 박스 폭 무관(고정 1초당 1개) 이라 사라지지
        않고, 타일은 가까운 슬롯에 매핑되므로 박스가 줄어도 같은 캐시 재활용.
        """
        if seg is None:
            p.fillRect(r, _BOX_FILL)
            return
        slots = self.thumbnail_slots_for(seg)   # src_ms 리스트
        if not slots:
            p.fillRect(r, _BOX_FILL)
            return
        # 표시할 타일 수 — 박스 폭 가변, 슬롯 수 상한.
        approx_tile_w = 80
        n_tiles = max(1, min(len(slots), r.width() // approx_tile_w))
        tile_w_base = r.width() // n_tiles
        dur = max(1, seg.duration_ms)
        for i in range(n_tiles):
            tx = r.left() + i * tile_w_base
            tw = (r.width() - tile_w_base * (n_tiles - 1)) if i == n_tiles - 1 else tile_w_base
            tile = QRect(tx, r.top(), tw, r.height())
            # 이 타일의 중앙 local_ms — 가장 가까운 슬롯 src_ms 찾기.
            tile_local_ms = int(round((i + 0.5) * dur / n_tiles))
            tile_src_ms = int(seg.src_in_ms) + tile_local_ms
            nearest = min(slots, key=lambda s: abs(s - tile_src_ms))
            thumb = self._thumbnails.get((seg.id, int(nearest)))
            if thumb is not None and not thumb.isNull():
                scaled = thumb.scaled(tile.size(), Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation)
                ox = max(0, (scaled.width() - tile.width()) // 2)
                oy = max(0, (scaled.height() - tile.height()) // 2)
                src_rect = QRect(ox, oy, tile.width(), tile.height())
                p.drawImage(tile, scaled, src_rect)
            else:
                p.fillRect(tile, _BOX_FILL)

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
    _DRAG_THRESHOLD_PX = 5

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        for box in self._segment_rects():
            if box["rect"].contains(pos):
                self._pending_select = box["id"]
                self._reorder_drag_id = box["id"]
                self._reorder_press_x = pos.x()
                self._reorder_started = False
                # 드래그 시 박스의 start_ms 기준점을 기록 — 마우스가 (press_x, start_ms)
                # 페어를 유지한 채 좌우로 움직이면 해당 차이만큼 start_ms 도 따라감.
                seg = next((s for s in self._segments if s.id == box["id"]), None)
                self._reorder_orig_start_ms = seg.start_ms if seg else 0
                self._reorder_preview_start_ms = self._reorder_orig_start_ms
                event.accept()
                return
        self._pending_select = None
        self._reorder_drag_id = None
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._reorder_drag_id is None:
            return super().mouseMoveEvent(event)
        x = int(event.position().x())
        if not self._reorder_started:
            if abs(x - self._reorder_press_x) < self._DRAG_THRESHOLD_PX:
                return
            self._reorder_started = True
            self._pending_select = None
        # 픽셀 차이 → ms 차이 변환 후 새 start_ms 계산.
        total = self._total_duration_ms()
        body_w = max(1, self.width() - _HEADER_WIDTH)
        delta_ms = int(round((x - self._reorder_press_x) * total / body_w))
        self._reorder_preview_start_ms = max(0, self._reorder_orig_start_ms + delta_ms)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        sid = self._pending_select
        reorder_id = self._reorder_drag_id
        started = self._reorder_started
        new_start = self._reorder_preview_start_ms
        self._pending_select = None
        self._reorder_drag_id = None
        self._reorder_started = False
        self._drop_indicator_x = None
        self._reorder_preview_start_ms = 0
        self._reorder_orig_start_ms = 0
        if reorder_id is not None and started and event.button() == Qt.LeftButton:
            # 자유 이동: 새 start_ms 로 위치 변경 요청. EditController 가 clamp.
            self.segment_position_changed.emit(reorder_id, int(new_start))
            self.update()
            event.accept()
            return
        if sid is not None and event.button() == Qt.LeftButton:
            self.set_selected_id(sid)
            self.segment_selected.emit(sid)
            self.update()
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
            # 빈 영역 — 클릭한 결합 ms 위치에 삽입 요청.
            insert_at_ms = self._x_to_combined_ms(pos.x())
            insert_action = QAction("➕ 영상 파일 삽입…", menu)
            insert_action.triggered.connect(
                lambda _checked=False, t=insert_at_ms: self.request_insert_at.emit(t)
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
        drop_ms = self._x_to_combined_ms(x)
        self._drop_indicator_x = None
        self.update()
        event.acceptProposedAction()
        self.request_insert_files.emit(paths, drop_ms)
