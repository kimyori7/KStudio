"""환경설정 — 단축키 탭. 글로벌 + 편집기 단축키 통합."""
from __future__ import annotations
from dataclasses import fields
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ...core.settings import EditorShortcuts, HotkeySettings
from ..widgets import OneShotKeySequenceEdit


_EDITOR_LABELS = {
    "tool_select": "선택 도구",
    "tool_crop": "자르기 도구",
    "tool_arrow": "화살표 도구",
    "tool_rect": "사각형 도구",
    "tool_text": "텍스트 도구",
    "op_background_removal": "배경 제거 (누끼)",
    "file_save": "저장",
    "file_save_as": "다른 이름으로 저장",
    "file_export_png": "PNG 로 내보내기",
    "file_open": "열기",
    "view_actual_size": "실제 크기 (100%)",
    "view_fit": "Fit",
}


class ShortcutsPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, hotkeys: HotkeySettings, editor: EditorShortcuts) -> None:
        super().__init__()
        self._hotkeys = hotkeys
        self._editor = editor
        self._editors: dict[str, OneShotKeySequenceEdit] = {}

        root = QVBoxLayout(self)

        # 글로벌 그룹
        root.addWidget(QLabel("🎬 글로벌"))
        gform = QFormLayout()
        self._add_hotkey_row(gform, "toggle_record", "영역 녹화", hotkeys.toggle_record)
        self._add_hotkey_row(gform, "toggle_record_full", "전체 녹화", hotkeys.toggle_record_full)
        self._add_hotkey_row(gform, "screenshot_region", "영역 스크린샷", hotkeys.screenshot_region)
        self._add_hotkey_row(gform, "screenshot_full", "스크린샷 전체", hotkeys.screenshot_full)
        root.addLayout(gform)

        # 편집기 그룹
        root.addWidget(QLabel("🔧 편집기"))
        eform = QFormLayout()
        for key, label in _EDITOR_LABELS.items():
            self._add_editor_row(eform, key, label, getattr(editor, key))
        root.addLayout(eform)

        # 버튼
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("기본값으로 되돌리기")
        btn_reset.clicked.connect(self.reset_to_defaults)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_reset)
        root.addLayout(btn_row)

    def _add_hotkey_row(self, form, key: str, label: str, initial: str) -> None:
        ed = OneShotKeySequenceEdit()
        ed.setKeySequence(QKeySequence(initial))
        ed.editingFinished.connect(
            lambda k=key, e=ed: self._on_hotkey_changed(k, e.keySequence())
        )
        self._editors[f"hk:{key}"] = ed
        form.addRow(label + ":", ed)

    def _add_editor_row(self, form, key: str, label: str, initial: str) -> None:
        ed = OneShotKeySequenceEdit()
        ed.setKeySequence(QKeySequence(initial))
        ed.editingFinished.connect(
            lambda k=key, e=ed: self._on_editor_changed(k, e.keySequence())
        )
        self._editors[key] = ed
        form.addRow(label + ":", ed)

    def _on_hotkey_changed(self, key: str, seq: QKeySequence) -> None:
        text = seq.toString(QKeySequence.PortableText)
        setattr(self._hotkeys, key, text)
        self.settings_changed.emit()

    def _on_editor_changed(self, key: str, seq: QKeySequence) -> None:
        text = seq.toString(QKeySequence.PortableText)
        setattr(self._editor, key, text)
        self.settings_changed.emit()

    # --- API (테스트 + 외부) ---
    def captured_settings_keys(self) -> list[str]:
        return [f.name for f in fields(EditorShortcuts)]

    def set_shortcut_for(self, key: str, text: str) -> None:
        if key in self._editors:
            self._editors[key].setKeySequence(QKeySequence(text))
        if hasattr(self._editor, key):
            setattr(self._editor, key, text)
            self.settings_changed.emit()

    def reset_to_defaults(self) -> None:
        defaults = EditorShortcuts()
        for f in fields(EditorShortcuts):
            v = getattr(defaults, f.name)
            setattr(self._editor, f.name, v)
            if f.name in self._editors:
                self._editors[f.name].blockSignals(True)
                self._editors[f.name].setKeySequence(QKeySequence(v))
                self._editors[f.name].blockSignals(False)
        self.settings_changed.emit()

    def check_conflict(self, key: str, candidate: str) -> Optional[str]:
        for f in fields(EditorShortcuts):
            if f.name == key:
                continue
            if getattr(self._editor, f.name) == candidate:
                return f.name
        return None
