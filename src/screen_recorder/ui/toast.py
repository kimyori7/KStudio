"""간단한 토스트 — 부모 창 하단 중앙에 잠깐 뜨는 알림."""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget


class Toast(QLabel):
    """
    show_toast(parent, message, duration_ms) 로 띄움.
    parent 창 하단 중앙에 자동 배치되고, 지정 시간 후 자동 닫힘.
    """

    _DEFAULT_STYLE = (
        "QLabel { "
        "background-color: rgba(40, 40, 40, 230); "
        "color: white; "
        "border-radius: 6px; "
        "padding: 8px 16px; "
        "font-size: 11pt; "
        "}"
    )

    def __init__(self, parent: QWidget, text: str):
        super().__init__(text, parent)
        self.setStyleSheet(self._DEFAULT_STYLE)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.adjustSize()
        self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        pw = parent.width()
        ph = parent.height()
        x = (pw - self.width()) // 2
        y = ph - self.height() - 40
        self.move(max(0, x), max(0, y))


_active_toast: Toast | None = None


def show_toast(parent: QWidget, text: str, duration_ms: int = 1000) -> None:
    """parent의 하단 중앙에 text를 duration_ms 동안 표시. 이전 토스트가 살아있으면 교체."""
    global _active_toast
    if _active_toast is not None:
        try:
            _active_toast.close()
        except Exception:
            pass
        _active_toast = None

    t = Toast(parent, text)
    t.show()
    t.raise_()
    _active_toast = t

    def _close():
        global _active_toast
        try:
            t.close()
        finally:
            if _active_toast is t:
                _active_toast = None

    QTimer.singleShot(duration_ms, _close)
