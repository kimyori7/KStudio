"""환경설정 — 단축키 탭. 글로벌 + 편집기 단축키 통합."""
from __future__ import annotations
from dataclasses import fields
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ...core.settings import AppSettings, EditorShortcuts, HotkeySettings
from ...core.hotkey_presets import apply_preset, detect_preset
from ..widgets import OneShotKeySequenceEdit


_PRESET_LABELS = [
    ("custom", "사용자 지정"),
    ("windows-standard", "윈도우 표준"),
    ("goom-pot", "곰/팟 스타일"),
]


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
    # 패널 안의 어떤 OneShotKeySequenceEdit 라도 capture 가 시작/끝나면 발화 —
    # main_window 가 글로벌 Win32 핫키를 일시 unregister 하기 위함.
    hotkey_editing_started = Signal()
    hotkey_editing_finished = Signal()

    def __init__(self, hotkeys: HotkeySettings, editor: EditorShortcuts,
                 settings: AppSettings | None = None) -> None:
        super().__init__()
        self._hotkeys = hotkeys
        self._editor = editor
        # 프리셋 드롭다운이 두 dataclass 모두 일괄 갱신해야 하므로 settings 필요.
        # 하위 호환: settings 미전달 시 드롭다운 비활성.
        self._settings = settings
        self._editors: dict[str, OneShotKeySequenceEdit] = {}

        root = QVBoxLayout(self)

        # 프리셋 드롭다운 (상단)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("프리셋:"))
        self.preset_combo = QComboBox()
        for key, label in _PRESET_LABELS:
            self.preset_combo.addItem(label, key)
        self._sync_preset_combo()
        self.preset_combo.activated.connect(self._on_preset_chosen)
        if self._settings is None:
            self.preset_combo.setEnabled(False)
        preset_row.addWidget(self.preset_combo)
        preset_row.addStretch(1)
        root.addLayout(preset_row)

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
        ed.editing_started.connect(self.hotkey_editing_started.emit)
        ed.editing_finished_signal.connect(self.hotkey_editing_finished.emit)
        self._editors[f"hk:{key}"] = ed
        form.addRow(label + ":", ed)

    def _add_editor_row(self, form, key: str, label: str, initial: str) -> None:
        ed = OneShotKeySequenceEdit()
        ed.setKeySequence(QKeySequence(initial))
        ed.editingFinished.connect(
            lambda k=key, e=ed: self._on_editor_changed(k, e.keySequence())
        )
        ed.editing_started.connect(self.hotkey_editing_started.emit)
        ed.editing_finished_signal.connect(self.hotkey_editing_finished.emit)
        self._editors[key] = ed
        form.addRow(label + ":", ed)

    def _on_hotkey_changed(self, key: str, seq: QKeySequence) -> None:
        text = seq.toString(QKeySequence.PortableText)
        setattr(self._hotkeys, key, text)
        self._mark_custom()
        self.settings_changed.emit()

    def _on_editor_changed(self, key: str, seq: QKeySequence) -> None:
        text = seq.toString(QKeySequence.PortableText)
        setattr(self._editor, key, text)
        self._mark_custom()
        self.settings_changed.emit()

    def _mark_custom(self) -> None:
        """사용자가 개별 키 한 줄을 수정하면 프리셋이 'custom' 으로 전환."""
        if self._hotkeys.preset_name != "custom":
            self._hotkeys.preset_name = "custom"
            self._sync_preset_combo()

    def _sync_preset_combo(self) -> None:
        current = self._hotkeys.preset_name or "custom"
        for i in range(self.preset_combo.count()):
            if self.preset_combo.itemData(i) == current:
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(i)
                self.preset_combo.blockSignals(False)
                return

    def _on_preset_chosen(self, idx: int) -> None:
        if self._settings is None:
            return
        key = self.preset_combo.itemData(idx)
        if key == "custom" or key is None:
            return
        ans = QMessageBox.question(
            self, "프리셋 적용",
            "프리셋을 적용하면 현재 단축키가 모두 덮어쓰입니다.\n계속하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            self._sync_preset_combo()
            return
        apply_preset(self._settings, key)
        # 모든 위젯에 새 값 반영.
        for f_key in self.captured_settings_keys():
            v = getattr(self._editor, f_key)
            if f_key in self._editors:
                self._editors[f_key].blockSignals(True)
                self._editors[f_key].setKeySequence(QKeySequence(v))
                self._editors[f_key].blockSignals(False)
        for hk_field in ("toggle_record", "toggle_record_full",
                          "screenshot_region", "screenshot_full"):
            if f"hk:{hk_field}" in self._editors:
                ed = self._editors[f"hk:{hk_field}"]
                ed.blockSignals(True)
                ed.setKeySequence(QKeySequence(getattr(self._hotkeys, hk_field)))
                ed.blockSignals(False)
        self.settings_changed.emit()

    # --- API (테스트 + 외부) ---
    def captured_settings_keys(self) -> list[str]:
        return [f.name for f in fields(EditorShortcuts)]

    def set_shortcut_for(self, key: str, text: str) -> None:
        if key in self._editors:
            self._editors[key].setKeySequence(QKeySequence(text))
        if hasattr(self._editor, key):
            setattr(self._editor, key, text)
            self._mark_custom()
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
