"""Markdown 코드 에디터 — 줄번호 거터 + 디바운스 변경 알림."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class _LineNumberArea(QWidget):
    def __init__(self, editor: "MarkdownEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class MarkdownEditor(QPlainTextEdit):
    # 디바운스된 본문 변경 알림 (미리보기 갱신용).
    content_changed = Signal(str)
    _DEBOUNCE_MS = 300

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))

        self._gutter = _LineNumberArea(self)
        self.blockCountChanged.connect(lambda _: self._update_gutter_width())
        self.updateRequest.connect(self._on_update_request)
        self._update_gutter_width()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(
            lambda: self.content_changed.emit(self.toPlainText())
        )
        self.textChanged.connect(self._debounce.start)

    # --- 거터 ---
    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor("#2b2b2b"))
        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        painter.setPen(QColor("#858585"))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0, int(top), self._gutter.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight, str(block_num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_num += 1
