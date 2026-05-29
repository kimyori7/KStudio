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
    # Ctrl+휠 줌 요청 — +1(확대)/-1(축소). 실제 적용/영속은 MarkdownTab 이 담당
    # (상태 단일 출처). 에디터 자신은 폰트를 직접 바꾸지 않는다.
    zoom_requested = Signal(int)
    _DEBOUNCE_MS = 300
    _MIN_PT = 8
    _MAX_PT = 32

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

        # 가운데(휠) 버튼 hand-pan 상태.
        self._panning = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(
            lambda: self.content_changed.emit(self.toPlainText())
        )
        self.textChanged.connect(self._debounce.start)

    # --- 폰트 크기 ---
    def set_font_point_size(self, pt: int) -> None:
        """편집기 폰트 포인트 크기 설정 (8..32 클램프). 탭폭·거터를 함께 재계산.

        주의: 전역 테마 QSS(`QWidget{font-size:10pt}`)가 setFont() 를 덮어쓴다
        (2026-05-29 진단 — scripts/diagnose_markdown_font.py). 그래서 위젯별
        stylesheet 로 폰트를 지정해야 실제로 적용된다(위젯 규칙이 전역보다 우선).
        """
        pt = max(self._MIN_PT, min(self._MAX_PT, int(pt)))
        self.setStyleSheet(
            f'QPlainTextEdit {{ font-family:"Consolas",monospace; font-size:{pt}pt; }}'
        )
        self.ensurePolished()   # QSS 폰트를 self.font()/fontMetrics() 에 즉시 반영
        # 폰트가 바뀌면 탭 정지폭(공백 4칸)·거터 폭이 달라지므로 재계산.
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self._update_gutter_width()
        self.viewport().update()
        self._gutter.update()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        # Ctrl+휠 = 줌 요청 (스크롤 대신). MarkdownTab 이 받아 폰트 적용 + 영속.
        if event.modifiers() & Qt.ControlModifier:
            steps = 1 if event.angleDelta().y() > 0 else -1
            self.zoom_requested.emit(steps)
            event.accept()
            return
        super().wheelEvent(event)

    # --- 가운데(휠) 버튼 누른 채 끌어서 상하좌우 이동 (PDF/이미지 뷰어식 hand-pan) ---
    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        if e.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_anchor = e.position().toPoint()
            self._pan_h0 = self.horizontalScrollBar().value()
            self._pan_v0 = self.verticalScrollBar().value()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # type: ignore[override]
        if self._panning:
            delta = e.position().toPoint() - self._pan_anchor
            # 손으로 잡아끄는 느낌: 끈 방향과 반대로 스크롤바를 움직여 내용이 따라오게.
            self.horizontalScrollBar().setValue(self._pan_h0 - delta.x())
            self.verticalScrollBar().setValue(self._pan_v0 - delta.y())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # type: ignore[override]
        if self._panning and e.button() == Qt.MiddleButton:
            self._panning = False
            self.viewport().setCursor(Qt.IBeamCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

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
