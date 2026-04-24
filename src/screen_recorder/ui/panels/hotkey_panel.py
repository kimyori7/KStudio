"""단축키 설정 패널 — 편집 중 글로벌 훅 임시 해제."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget, QFormLayout, QKeySequenceEdit, QLabel, QVBoxLayout

from ...core.settings import HotkeySettings


class _FocusTrackingKeySequenceEdit(QKeySequenceEdit):
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
    editing_started = Signal()
    editing_finished = Signal()

    _HINT_IDLE = "클릭 후 원하는 키 조합을 누르세요 (예: Ctrl+Shift+T)."
    _HINT_CAPTURE = "🔴 지정 중... 누를 키를 입력하세요. (지정 중에는 단축키가 발동하지 않음)"

    def __init__(self, settings: HotkeySettings):
        super().__init__()
        self.settings = settings
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.editor_record = self._make_editor(settings.toggle_record)
        form.addRow("녹화 시작/정지:", self.editor_record)

        self.editor_region = self._make_editor(settings.screenshot_region)
        form.addRow("스크린샷 영역 찍기:", self.editor_region)

        self.editor_full = self._make_editor(settings.screenshot_full)
        form.addRow("스크린샷 전체 찍기:", self.editor_full)

        self.hint = QLabel(self._HINT_IDLE)
        self.hint.setStyleSheet("color: #666;")
        self.hint.setWordWrap(True)
        form.addRow(self.hint)

        self.editor_record.keySequenceChanged.connect(lambda _: self._sync())
        self.editor_region.keySequenceChanged.connect(lambda _: self._sync())
        self.editor_full.keySequenceChanged.connect(lambda _: self._sync())

        for ed in (self.editor_record, self.editor_region, self.editor_full):
            ed.editingFinished.connect(self._sync)
            ed.focus_gained.connect(self._on_focus_in)
            ed.focus_lost.connect(self._on_focus_out)

    def _make_editor(self, initial: str) -> _FocusTrackingKeySequenceEdit:
        ed = _FocusTrackingKeySequenceEdit()
        ed.setKeySequence(QKeySequence(initial))
        ed.setMaximumSequenceLength(1)
        return ed

    def _on_focus_in(self):
        self.hint.setText(self._HINT_CAPTURE)
        self.hint.setStyleSheet("color: #E53935; font-weight: bold;")
        self.editing_started.emit()

    def _on_focus_out(self):
        self.hint.setText(self._HINT_IDLE)
        self.hint.setStyleSheet("color: #666;")
        self._sync()
        self.editing_finished.emit()

    def _sync(self):
        seq_record = self.editor_record.keySequence().toString(QKeySequence.PortableText)
        seq_region = self.editor_region.keySequence().toString(QKeySequence.PortableText)
        seq_full = self.editor_full.keySequence().toString(QKeySequence.PortableText)

        changed = False
        if seq_record and seq_record != self.settings.toggle_record:
            self.settings.toggle_record = seq_record
            changed = True
        # region / full 은 "" 입력 (미할당) 도 허용
        if seq_region != self.settings.screenshot_region:
            self.settings.screenshot_region = seq_region
            changed = True
        if seq_full != self.settings.screenshot_full:
            self.settings.screenshot_full = seq_full
            changed = True
        if changed:
            self.settings_changed.emit()
