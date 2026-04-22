"""단축키 설정 패널."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget, QFormLayout, QPushButton, QKeySequenceEdit

from ...core.settings import HotkeySettings


class HotkeyPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: HotkeySettings):
        super().__init__()
        self.settings = settings
        form = QFormLayout(self)

        self.editor = QKeySequenceEdit()
        self.editor.setKeySequence(QKeySequence(settings.toggle_record))
        self.editor.editingFinished.connect(self._sync)
        form.addRow("녹화 시작/정지:", self.editor)

    def _sync(self):
        seq = self.editor.keySequence().toString(QKeySequence.PortableText)
        if seq:
            self.settings.toggle_record = seq
            self.settings_changed.emit()
