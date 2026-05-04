"""환경설정 — 단축키 탭. 글로벌 + 편집기 단축키 통합."""
from __future__ import annotations
from dataclasses import fields
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ...core.settings import AppSettings, EditorShortcuts, HotkeySettings
from ...core.hotkey_presets import detect_global_preset, detect_player_preset
from ..widgets import OneShotKeySequenceEdit


_PRESET_LABEL = {
    "custom": "사용자 지정",
    "windows-standard": "윈도우 표준",
    "kstudio-default": "KStudio 기본",
    "goom-style": "곰플레이어 호환",
}


_EDITOR_LABELS = {
    "tool_select": "선택 도구",
    "tool_crop": "자르기 도구",
    "tool_arrow": "화살표 도구",
    "tool_rect": "사각형 도구",
    "tool_text": "텍스트 도구",
    "op_background_removal": "배경 제거 (누끼)",
    "op_image_scale": "이미지 크기 변경",
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
    # "프리셋 선택…" 버튼 클릭 — main_window 가 다이얼로그 노출하도록.
    preset_dialog_requested = Signal()
    # OS 시스템 단축키 가로채기 토글 변경 — main_window 가 hotkey 매니저에 적용.
    intercept_system_keys_changed = Signal(bool)

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

        # 프리셋 — 현재 적용된 프리셋 표시 + "프리셋 선택…" 버튼이 다이얼로그 호출.
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("프리셋:"))
        self.preset_label = QLabel(self._format_preset_label())
        self.preset_label.setStyleSheet("color: #C0C4CC;")
        preset_row.addWidget(self.preset_label)
        preset_row.addStretch(1)
        self.preset_btn = QPushButton("프리셋 선택…")
        self.preset_btn.clicked.connect(self.preset_dialog_requested.emit)
        if self._settings is None:
            self.preset_btn.setEnabled(False)
        preset_row.addWidget(self.preset_btn)
        root.addLayout(preset_row)

        # 글로벌 그룹
        root.addWidget(QLabel("🎬 글로벌"))
        gform = QFormLayout()
        self._add_hotkey_row(gform, "toggle_record", "영역 녹화", hotkeys.toggle_record)
        self._add_hotkey_row(gform, "toggle_record_full", "전체 녹화", hotkeys.toggle_record_full)
        self._add_hotkey_row(gform, "screenshot_region", "영역 스크린샷", hotkeys.screenshot_region)
        self._add_hotkey_row(gform, "screenshot_full", "스크린샷 전체", hotkeys.screenshot_full)
        root.addLayout(gform)

        # OS 시스템 단축키 가로채기 토글 — Win+Shift+S 같은 OS 가 가로채는 키도
        # KStudio 가 먼저 잡으려면 low-level keyboard hook 활성화 필요.
        self.intercept_check = QCheckBox(
            "Win+Shift+S 같은 OS 시스템 단축키도 KStudio 가 가로채기 (실험)"
        )
        self.intercept_check.setToolTip(
            "켜면 OS Snipping Tool 같은 시스템 단축키를 KStudio 가 먼저 잡습니다.\n"
            "단점: OS Snipping Tool 사용 불가 + 일부 게임 anti-cheat 와 마찰 가능."
        )
        self.intercept_check.setChecked(bool(hotkeys.intercept_system_keys))
        self.intercept_check.toggled.connect(self._on_intercept_toggled)
        root.addWidget(self.intercept_check)

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

    def _on_intercept_toggled(self, enabled: bool) -> None:
        self._hotkeys.intercept_system_keys = enabled
        self.intercept_system_keys_changed.emit(enabled)
        self.settings_changed.emit()

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
        """사용자가 개별 키 한 줄을 수정하면 글로벌 프리셋이 'custom' 으로 전환."""
        if self._hotkeys.preset_name != "custom":
            self._hotkeys.preset_name = "custom"
            self.preset_label.setText(self._format_preset_label())

    def _format_preset_label(self) -> str:
        """현재 적용된 글로벌 + 영상 프리셋을 한 줄로 표시.

        preset_name 필드가 'custom' 으로 명시 마킹돼 있으면 그걸 우선 — 사용자가 개별
        키를 수정한 흐름을 detect 로직(키 값 비교) 이 못 잡는 경우 보존.
        """
        if self._hotkeys.preset_name == "custom":
            g = "custom"
        else:
            g = detect_global_preset(self._settings) if self._settings else "custom"
        if self._settings is not None:
            if self._settings.player_hotkeys.preset_name == "custom":
                p = "custom"
            else:
                p = detect_player_preset(self._settings)
        else:
            p = "custom"
        g_lbl = _PRESET_LABEL.get(g, g)
        p_lbl = _PRESET_LABEL.get(p, p)
        return f"{g_lbl} (글로벌) · {p_lbl} (영상)"

    def refresh_after_preset_applied(self) -> None:
        """main_window 가 프리셋 적용 후 호출 — 모든 위젯과 라벨 갱신."""
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
        self.preset_label.setText(self._format_preset_label())

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
