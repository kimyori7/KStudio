"""단축키 설정 패널 — 포커스 진입 시 '지정 중...' 안내 + 글로벌 훅 임시 해제."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget, QFormLayout, QKeySequenceEdit, QLabel, QVBoxLayout

from ...core.settings import HotkeySettings


class _FocusTrackingKeySequenceEdit(QKeySequenceEdit):
    """포커스 진입/해제 시그널을 노출하는 QKeySequenceEdit."""
    focus_gained = Signal()
    focus_lost = Signal()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_gained.emit()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_lost.emit()


class HotkeyPanel(QWidget):
    settings_changed = Signal()
    editing_started = Signal()   # 단축키 캡처 시작 → 글로벌 훅 임시 해제
    editing_finished = Signal()  # 단축키 캡처 종료 → 훅 재등록

    _HINT_IDLE = "클릭 후 원하는 키 조합을 누르세요 (예: F9, Ctrl+Shift+R)."
    _HINT_CAPTURE = "🔴 지정 중... 누를 키를 입력하세요. (지정 중에는 녹화가 발동하지 않음)"

    def __init__(self, settings: HotkeySettings):
        super().__init__()
        self.settings = settings
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.editor = _FocusTrackingKeySequenceEdit()
        self.editor.setKeySequence(QKeySequence(settings.toggle_record))
        self.editor.setMaximumSequenceLength(1)
        form.addRow("녹화 시작/정지:", self.editor)

        self.hint = QLabel(self._HINT_IDLE)
        self.hint.setStyleSheet("color: #666;")
        self.hint.setWordWrap(True)
        form.addRow(self.hint)

        self.editor.keySequenceChanged.connect(self._on_sequence_changed)
        self.editor.editingFinished.connect(self._sync)
        self.editor.focus_gained.connect(self._on_focus_in)
        self.editor.focus_lost.connect(self._on_focus_out)

    def _on_focus_in(self):
        self.hint.setText(self._HINT_CAPTURE)
        self.hint.setStyleSheet("color: #E53935; font-weight: bold;")
        self.editing_started.emit()

    def _on_focus_out(self):
        self.hint.setText(self._HINT_IDLE)
        self.hint.setStyleSheet("color: #666;")
        self._sync()
        self.editing_finished.emit()

    def _on_sequence_changed(self, _seq):
        self._sync()

    def _sync(self):
        seq = self.editor.keySequence().toString(QKeySequence.PortableText)
        if seq:
            self.settings.toggle_record = seq
            self.settings_changed.emit()
