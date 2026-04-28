"""주석들이 살아있는 무대 — 배경 이미지 + 주석 아이템 목록 관리."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene


class AnnotationScene(QGraphicsScene):
    """배경 이미지 + 주석 아이템. 단일 선택 강제."""

    def __init__(self, background: QImage) -> None:
        super().__init__()
        self._background = QImage(background)
        self._bg_item = QGraphicsPixmapItem(QPixmap.fromImage(self._background))
        self._bg_item.setZValue(-1000)
        self._bg_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.addItem(self._bg_item)
        self.setSceneRect(QRectF(0, 0, self._background.width(), self._background.height()))
        self.selectionChanged.connect(self._enforce_single_selection)
        self._suppress_enforce = False
        self._prev_selected: set = set()
        self._selection_order: list = []

    # --- API ---
    def background_image(self) -> QImage:
        return QImage(self._background)

    def add_annotation(self, item: QGraphicsItem) -> None:
        self.addItem(item)
        # NOTE: 핸들 드래그 → undo push 콜백 주입은 EditTab.undo_stack 레벨에서 처리

    def remove_annotation(self, item: QGraphicsItem) -> None:
        if item.scene() is self:
            self.removeItem(item)

    def annotations(self) -> list[QGraphicsItem]:
        out = []
        for it in self.items():
            if it is self._bg_item:
                continue
            if it.parentItem() is not None:
                continue  # 핸들 제외
            out.append(it)
        return out

    def render_composite(self) -> QImage:
        """원본 배경 + 모든 주석을 합성한 이미지(원본 픽셀 크기)."""
        out = QImage(self._background.size(), QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            # 선택 상태는 저장에 반영되면 안 되므로 임시로 해제
            restored = [(it, it.isSelected()) for it in self.annotations() if it.isSelected()]
            self._suppress_enforce = True
            for it, _ in restored:
                it.setSelected(False)
            self.render(painter, QRectF(0, 0, out.width(), out.height()), self.sceneRect())
            for it, was in restored:
                it.setSelected(was)
            self._suppress_enforce = False
        finally:
            painter.end()
        return out

    def _enforce_single_selection(self) -> None:
        if self._suppress_enforce:
            return
        current = {it for it in self.selectedItems()
                   if it is not self._bg_item and it.parentItem() is None}
        newly = current - self._prev_selected
        # 새로 선택된 아이템을 순서 목록 맨 뒤에 추가
        for it in newly:
            if it in self._selection_order:
                self._selection_order.remove(it)
            self._selection_order.append(it)
        # 선택 해제된 아이템은 목록에서 제거
        self._selection_order = [it for it in self._selection_order if it in current]

        if len(self._selection_order) > 1:
            keep = self._selection_order[-1]
            self._suppress_enforce = True
            for it in list(self._selection_order):
                if it is not keep:
                    it.setSelected(False)
            self._selection_order = [keep]
            self._suppress_enforce = False
            current = {keep}
        self._prev_selected = current
