"""Markdown 코드 에디터 — 줄번호 거터 + 디바운스 변경 알림."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter
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
    # .md/.markdown 파일을 편집기에 드롭 → "새 문서로 열기" 요청(경로). 실제 열기/등록은
    # MarkdownTab→main_window 가 담당. (기본 QPlainTextEdit 는 파일 URL 을 경로 텍스트로
    # 삽입해버리므로 문서 파일 드롭만 가로채 신호로 올린다. 그 외 드롭은 기본 동작 유지.)
    file_open_requested = Signal(object)   # Path
    _MD_SUFFIXES = (".md", ".markdown")
    _DEBOUNCE_MS = 300
    _MIN_PT = 8
    _MAX_PT = 32
    # autoscroll(가운데 버튼 연속 스크롤) 튜닝.
    _AUTOSCROLL_INTERVAL_MS = 16    # ~60fps
    _AUTOSCROLL_DEADZONE = 12       # anchor 근처 px: 스크롤 안 함
    _AUTOSCROLL_DIVISOR = 8         # 클수록 느림 (변위 / divisor = tick 당 스크롤 px)

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

        # 가운데(휠) 버튼 autoscroll 상태 — 미리보기(Chromium)식 연속 스크롤.
        self._autoscrolling = False
        self._autoscroll_anchor = QPoint(0, 0)
        self._autoscroll_moved = False
        self._autoscroll_pos: QPoint | None = None   # 테스트 주입용; None 이면 QCursor 폴링
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(self._AUTOSCROLL_INTERVAL_MS)
        self._autoscroll_timer.timeout.connect(self._autoscroll_tick)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(
            lambda: self.content_changed.emit(self.toPlainText())
        )
        self.textChanged.connect(self._debounce.start)

    # --- 파일 드롭: .md 만 "열기" 신호로 가로챔 (그 외는 기본 텍스트 드롭 동작) ---
    @staticmethod
    def _dropped_markdown(mime) -> "Path | None":
        if not mime.hasUrls():
            return None
        for u in mime.urls():
            if not u.isLocalFile():
                continue
            p = Path(u.toLocalFile())
            if p.is_file() and p.suffix.lower() in MarkdownEditor._MD_SUFFIXES:
                return p
        return None

    def dragEnterEvent(self, e) -> None:  # type: ignore[override]
        if self._dropped_markdown(e.mimeData()) is not None:
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:  # type: ignore[override]
        if self._dropped_markdown(e.mimeData()) is not None:
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:  # type: ignore[override]
        p = self._dropped_markdown(e.mimeData())
        if p is not None:
            self.file_open_requested.emit(p)
            e.acceptProposedAction()
            return
        super().dropEvent(e)

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

    # --- 가운데(휠) 버튼 autoscroll (미리보기 Chromium 식 연속 스크롤) ---
    # 가운데 버튼을 누르면 4방향 커서가 뜨고, 커서를 anchor 에서 멀리 둘수록 그 방향으로
    # *계속* 스크롤된다(마우스를 멈춰도 변위가 있으면 쭉 이어짐). 한 번 더 누르거나
    # (눌러서 끈 경우) 떼면 종료 — 브라우저 autoscroll 과 동일.
    def _start_autoscroll(self, anchor: QPoint) -> None:
        self._autoscrolling = True
        self._autoscroll_anchor = anchor
        self._autoscroll_moved = False
        self.viewport().setCursor(Qt.SizeAllCursor)
        self._autoscroll_timer.start()

    def _stop_autoscroll(self) -> None:
        if not self._autoscrolling:
            return
        self._autoscrolling = False
        self._autoscroll_timer.stop()
        self.viewport().setCursor(Qt.IBeamCursor)

    def _autoscroll_tick(self) -> None:
        pos = self._autoscroll_pos
        if pos is None:
            pos = self.viewport().mapFromGlobal(QCursor.pos())
        dx = pos.x() - self._autoscroll_anchor.x()
        dy = pos.y() - self._autoscroll_anchor.y()
        if abs(dx) > self._AUTOSCROLL_DEADZONE or abs(dy) > self._AUTOSCROLL_DEADZONE:
            self._autoscroll_moved = True
        # viewport-follow: 커서를 둔 방향으로 뷰가 이동 (아래→아래로, 오른쪽→오른쪽).
        if abs(dy) > self._AUTOSCROLL_DEADZONE:
            vsb = self.verticalScrollBar()
            vsb.setValue(vsb.value() + int(dy / self._AUTOSCROLL_DIVISOR))
        if abs(dx) > self._AUTOSCROLL_DEADZONE:
            hsb = self.horizontalScrollBar()
            hsb.setValue(hsb.value() + int(dx / self._AUTOSCROLL_DIVISOR))

    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        if e.button() == Qt.MiddleButton:
            if self._autoscrolling:
                self._stop_autoscroll()          # 토글 OFF (다시 누르면 종료)
            else:
                self._start_autoscroll(e.position().toPoint())
            e.accept()
            return
        if self._autoscrolling:
            self._stop_autoscroll()              # 다른 버튼 클릭 → 종료
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # type: ignore[override]
        # 눌러서 끈(hold-drag) 경우엔 떼면 종료. 제자리 클릭이면 토글 모드로 유지.
        if e.button() == Qt.MiddleButton and self._autoscrolling and self._autoscroll_moved:
            self._stop_autoscroll()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def hideEvent(self, e) -> None:  # type: ignore[override]
        self._stop_autoscroll()                  # 숨겨지면(모드 전환 등) autoscroll 중단
        super().hideEvent(e)

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
