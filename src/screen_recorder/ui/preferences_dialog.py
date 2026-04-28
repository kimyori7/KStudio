"""환경설정 다이얼로그 — 좌측 카테고리 / 우측 패널 (포토샵 스타일)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QDialogButtonBox,
)

from ..core.settings import AppSettings
from .panels.screenshot_panel import ScreenshotPanel
from .panels.video_panel import VideoPanel
from .panels.shortcuts_panel import ShortcutsPanel
from .panels.preferences_panel import PreferencesPanel
from .panels.player_panel import PlayerPanel


_CATEGORIES = [
    ("저장 / 파일명", "screenshot"),
    ("영상·GIF·사운드", "video"),
    ("영상 플레이어", "player"),
    ("단축키", "shortcuts"),
    ("일반", "general"),
]


class PreferencesDialog(QDialog):
    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.setWindowTitle("환경설정")
        self.resize(720, 480)
        self._settings = settings

        outer = QVBoxLayout(self)
        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

        self.category_list = QListWidget()
        self.category_list.setFixedWidth(150)
        for label, key in _CATEGORIES:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.category_list.addItem(item)
        body.addWidget(self.category_list)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, stretch=1)

        self.screenshot_panel = ScreenshotPanel(settings.screenshot, settings.general)
        self.video_panel = VideoPanel(settings.video, settings.gif, settings.sound)
        self.player_panel = PlayerPanel(settings.player)
        self.shortcuts_panel = ShortcutsPanel(settings.hotkey, settings.editor_shortcuts)
        self.preferences_panel = PreferencesPanel(settings.preferences)

        self.stack.addWidget(self.screenshot_panel)
        self.stack.addWidget(self.video_panel)
        self.stack.addWidget(self.player_panel)
        self.stack.addWidget(self.shortcuts_panel)
        self.stack.addWidget(self.preferences_panel)

        self.category_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.category_list.setCurrentRow(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)
