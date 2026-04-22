"""좌측 메뉴 사이드바."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem


SIDEBAR_ITEMS = [
    ("general",     "📺 일반"),
    ("video",       "🎬 영상"),
    ("gif",         "🎞 GIF"),
    ("sound",       "🔊 사운드"),
    ("hotkey",      "⌨ 단축키"),
    ("preferences", "⚙ 환경설정"),
]


class Sidebar(QListWidget):
    panel_selected = Signal(str)

    def __init__(self):
        super().__init__()
        for key, label in SIDEBAR_ITEMS:
            item = QListWidgetItem(label)
            item.setData(0x0100, key)
            self.addItem(item)
        self.setCurrentRow(0)
        self.currentItemChanged.connect(self._on_changed)

    def _on_changed(self, current, _previous):
        if current is not None:
            self.panel_selected.emit(current.data(0x0100))
