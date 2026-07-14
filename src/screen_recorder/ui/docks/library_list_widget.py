"""라이브러리 목록 위젯 — 드래그아웃(파일 URL) + 내부 드래그 재정렬 + ✕ 히트테스트.

외부 파일 → 라이브러리 '추가' 드롭은 부모 LibraryPanel 이 처리한다(viewport 드롭
비활성). 이 위젯은 (1) 항목을 밖으로 끌 때의 mime 구성/드래그 시작, (2) 삭제된
항목 ✕ 클릭, (3) 내부 재정렬의 행 이동·드롭 위치 계산·삽입 표시선만 담당.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRect, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import QListWidget

_ROLE_MISSING = Qt.UserRole + 3   # 외부에서 파일이 삭제됨 → 취소선 + ✕ 표시 (Phase 60)
_MISSING_COLOR = "#d08770"        # 취소선/dim/✕ 색
_X_BTN_SIZE = 16
_X_BTN_RIGHT_PAD = 6

# 내부 재정렬 드래그 식별 marker — 경로 없는 항목(미저장 캡처)도 재정렬은 가능해야
# 하므로 URL 과 별개로 항상 싣는다. 외부 타깃(비교 뷰 등)은 URL 만 읽으므로 무해.
INTERNAL_MIME = "application/x-kstudio-library-entry"

_DROP_LINE_COLOR = "#3b82f6"      # 삽입 표시선 (드롭 hint 라벨과 같은 파란색 계열)


def _x_button_rect(row_rect: "QRect") -> "QRect":
    """삭제된 항목 오른쪽 끝의 ✕ 클릭/그리기 영역 (행 rect 기준). delegate 와 히트테스트가 공유."""
    top = row_rect.top() + (row_rect.height() - _X_BTN_SIZE) // 2
    return QRect(row_rect.right() - _X_BTN_SIZE - _X_BTN_RIGHT_PAD, top,
                 _X_BTN_SIZE, _X_BTN_SIZE)


class LibraryListWidget(QListWidget):
    """라이브러리 항목 목록. 드래그 시작만 담당하고 드롭 수락은 부모 패널이 한다."""

    order_changed = Signal()   # 내부 드래그로 행 순서가 바뀜 → 패널이 모델에 반영

    def __init__(self, path_for_item, on_x_clicked=None) -> None:
        super().__init__()
        self._path_for_item = path_for_item
        self._on_x_clicked = on_x_clicked   # 삭제된 항목 ✕ 클릭 → entry_id 콜백
        self._drop_line_y: "int | None" = None   # 내부 재정렬 삽입 표시선 y (viewport 좌표)
        self.setDragEnabled(True)

    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        # 삭제된(취소선) 항목의 오른쪽 ✕ 클릭이면 제거 콜백 후 소비 — 선택/열기/드래그로
        # 새지 않게 한다(히트테스트가 결정적이라 editorEvent 경로보다 안전).
        item = self.itemAt(e.position().toPoint())
        if item is not None and item.data(_ROLE_MISSING):
            if _x_button_rect(self.visualItemRect(item)).contains(e.position().toPoint()):
                eid = item.data(Qt.UserRole)
                if eid is not None and self._on_x_clicked is not None:
                    self._on_x_clicked(int(eid))
                e.accept()
                return
        super().mousePressEvent(e)

    # ---------- 드래그아웃 mime ----------
    def mime_for_item(self, item) -> "QMimeData | None":
        """외부 타깃(비교 뷰 등)용 파일 URL mime. 경로 없으면 None (기존 계약)."""
        p = self._path_for_item(item) if item is not None else None
        if p is None:
            return None
        m = QMimeData()
        m.setUrls([QUrl.fromLocalFile(str(p))])
        return m

    def drag_mime_for_item(self, item) -> QMimeData:
        """드래그 시작 mime — 내부 재정렬 marker 는 항상, 파일 URL 은 경로 있을 때만."""
        m = QMimeData()
        m.setData(INTERNAL_MIME, b"1")
        p = self._path_for_item(item) if item is not None else None
        if p is not None:
            m.setUrls([QUrl.fromLocalFile(str(p))])
        return m

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        item = self.currentItem()
        if item is None:
            return
        drag = QDrag(self)
        drag.setMimeData(self.drag_mime_for_item(item))
        # 외부 타깃(비교 뷰)은 Copy, 라이브러리 내부 재정렬은 Move 로 수락된다.
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)

    # ---------- 내부 재정렬 ----------
    def drop_row_for_pos(self, pos: QPoint) -> int:
        """viewport 좌표 → 삽입 행 index (0..count).

        항목의 세로 중앙보다 위면 그 행 앞, 아래면 다음 행. 항목 밖 빈 공간이면
        마지막 보이는 항목 아래(맨 끝) 또는 맨 위."""
        item = self.itemAt(pos)
        if item is None:
            last = self._last_visible_row()
            if last is None:
                return 0
            r = self.visualItemRect(self.item(last))
            return last + 1 if pos.y() > r.bottom() else 0
        r = self.visualItemRect(item)
        row = self.row(item)
        return row if pos.y() < r.center().y() else row + 1

    def _last_visible_row(self) -> "int | None":
        for i in range(self.count() - 1, -1, -1):
            if not self.item(i).isHidden():
                return i
        return None

    def move_row_to(self, src_row: int, insert_row: int) -> bool:
        """src_row 항목을 insert_row(이동 전 index 기준) 위치로. 변화 없으면 False.

        takeItem/insertItem 은 같은 QListWidgetItem 인스턴스를 유지하므로 패널의
        _items_by_id 매핑이 깨지지 않는다 (Qt 내장 InternalMove 는 항목을 직렬화 후
        재생성해 매핑·커스텀 role 이 깨질 수 있어 쓰지 않는다)."""
        if src_row < 0 or src_row >= self.count():
            return False
        if insert_row in (src_row, src_row + 1):
            return False   # 제자리 (자기 위/아래)
        was_current = self.currentRow() == src_row
        self.blockSignals(True)
        try:
            item = self.takeItem(src_row)
            dst = insert_row - 1 if insert_row > src_row else insert_row
            self.insertItem(dst, item)
            if was_current:
                self.setCurrentItem(item)
        finally:
            self.blockSignals(False)
        self.set_drop_line_y(None)
        self.viewport().update()
        self.order_changed.emit()
        return True

    def perform_internal_move(self, pos: QPoint) -> bool:
        """드롭 좌표(viewport)로 현재(드래그된) 항목 이동 — 패널 dropEvent 가 호출."""
        return self.move_row_to(self.currentRow(), self.drop_row_for_pos(pos))

    # ---------- 삽입 표시선 ----------
    def drop_line_y_for_pos(self, pos: QPoint) -> "int | None":
        """드롭 시 삽입될 경계선의 y (viewport 좌표). 그릴 수 없으면 None."""
        row = self.drop_row_for_pos(pos)
        # 삽입 행 이후 첫 '보이는' 항목의 윗변. 없으면 마지막 보이는 항목의 아랫변.
        for i in range(row, self.count()):
            it = self.item(i)
            if not it.isHidden():
                return self.visualItemRect(it).top()
        last = self._last_visible_row()
        if last is None:
            return None
        return self.visualItemRect(self.item(last)).bottom()

    def set_drop_line_y(self, y: "int | None") -> None:
        if y != self._drop_line_y:
            self._drop_line_y = y
            self.viewport().update()

    def paintEvent(self, e) -> None:  # type: ignore[override]
        super().paintEvent(e)
        if self._drop_line_y is None:
            return
        painter = QPainter(self.viewport())
        pen = QPen(QColor(_DROP_LINE_COLOR))
        pen.setWidth(2)
        painter.setPen(pen)
        y = self._drop_line_y
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()
