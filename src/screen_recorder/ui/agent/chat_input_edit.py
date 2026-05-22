"""Chat 입력창 위젯 — chat_panel.py 에서 분리 (Task 7).

bubble 이 아닌 입력 컨트롤이므로 bubbles/ 패키지 밖 (agent/ 직속) 에 배치.
동작 변경 없음.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QBuffer, QIODevice, Signal
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import QPlainTextEdit, QWidget

# chat_panel.py 와 같은 logger — getLogger 는 idempotent (동일 인스턴스 반환).
_chat_log = logging.getLogger("kstudio.chat")


class ChatInputEdit(QPlainTextEdit):
    """Chat용 멀티라인 입력 — Enter=보내기, Shift+Enter=줄바꿈.

    QLineEdit 와 달리 긴 텍스트 입력 시 줄바꿈으로 전체 내용이 보임. 높이는
    내용에 따라 1~5 줄 사이로 자동 조절.

    한글 IME 처리: Qt 의 QPlainTextEdit 는 document 가 비어있을 때 placeholder 를
    그림. 한글 IME 조합 중 (예: 'ㄱ' 만 입력) 에는 글자가 document 가 아닌 IME preedit
    영역에 있어서 document 는 비어있는 상태 → placeholder 가 입력 글자와 겹쳐 보임.
    `inputMethodEvent` 를 가로채 preedit 가 있으면 placeholder 를 임시로 "" 로 바꿈.
    """

    submit_requested = Signal()
    # Ctrl+V 등으로 클립보드 이미지 붙여넣음 — PNG bytes 한 장. ChatPanel 이 받아 pending 첨부.
    image_pasted = Signal(bytes)

    _MIN_LINES = 1
    _MAX_LINES = 5

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _sz: self._adjust_height()
        )
        # IME 조합 중 placeholder 숨기기 위한 원본 저장.
        self._original_placeholder: str = ""
        # 문서가 비워질 때 (backspace 등) placeholder 복원.
        self.textChanged.connect(self._restore_placeholder_if_empty)
        self._adjust_height()

    def setPlaceholderText(self, text: str) -> None:
        """공개 API 오버라이드 — 외부에서 placeholder 변경 시 *원본* 도 기억."""
        self._original_placeholder = text or ""
        super().setPlaceholderText(text)

    def inputMethodEvent(self, event) -> None:
        """한글 IME 조합 이벤트 — preedit 가 있는 동안 placeholder 숨김.

        - preedit 비어있지 않음 (예: 'ㄱ' 조합 중): placeholder = "".
        - preedit 비어있고 document 도 비어있음 (조합 취소 / 외부 reset): placeholder 복원.
        - preedit 비어있고 document 비어있지 않음 (commit 직후): Qt 가 자동으로 placeholder
          숨기므로 우리는 손대지 않음.
        """
        super().inputMethodEvent(event)
        preedit = event.preeditString() if event is not None else ""
        if preedit:
            super().setPlaceholderText("")
        elif not self.toPlainText():
            super().setPlaceholderText(self._original_placeholder)

    def _restore_placeholder_if_empty(self) -> None:
        """document 가 비워지면 (backspace 등) placeholder 다시 보이게."""
        if not self.toPlainText():
            super().setPlaceholderText(self._original_placeholder)

    def insertFromMimeData(self, source) -> None:
        """Ctrl+V — 이미지면 첨부, 텍스트면 일반 paste. **텍스트 우선**.

        Qt 의 markdown QLabel 등은 클립보드에 텍스트 + HTML 을 같이 올림. 일부 환경에선
        이미지 미리보기도 함께 들어가는데, 우리가 이미지 우선이면 사용자가 채팅 본문을
        복사해 paste 할 때 image-only paste 로 잘못 잡힘 (사용자 보고 2026-05-13).
        텍스트가 있으면 텍스트, 없을 때만 이미지 → 첨부.
        """
        try:
            formats = list(source.formats()) if source else []
            _chat_log.info(
                "Ctrl+V formats=%s has_text=%s has_image=%s text_len=%d",
                formats,
                bool(source and source.hasText()),
                bool(source and source.hasImage()),
                len(source.text()) if source and source.hasText() else 0,
            )
        except Exception:
            pass
        if source is None:
            super().insertFromMimeData(source)
            return
        # 텍스트가 있으면 무조건 텍스트 paste — 채팅 본문 복사 시나리오 보호.
        if source.hasText() and source.text().strip():
            super().insertFromMimeData(source)
            return
        # 이미지-only paste (스크린샷 클립보드 등) → 첨부로 emit.
        if source.hasImage():
            qimg = QImage(source.imageData())
            if not qimg.isNull():
                buf = QBuffer()
                buf.open(QIODevice.WriteOnly)
                if qimg.save(buf, "PNG"):
                    _chat_log.info("Ctrl+V: image attached (%d bytes)", len(buf.data()))
                    self.image_pasted.emit(bytes(buf.data()))
                    return
        super().insertFromMimeData(source)

    def _adjust_height(self) -> None:
        fm_h = self.fontMetrics().lineSpacing()
        margins = self.contentsMargins()
        frame = int(self.frameWidth()) * 2
        lines = max(self._MIN_LINES, min(self._MAX_LINES, self.document().blockCount()))
        h = fm_h * lines + margins.top() + margins.bottom() + frame + 6
        self.setFixedHeight(h)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)   # 줄바꿈.
            else:
                self.submit_requested.emit()
                return
        else:
            super().keyPressEvent(event)
