"""단축키 프리셋 — 첫 실행 시 사용자가 고른 묶음을 일괄 적용.

`HotkeySettings` (글로벌 캡처/녹화 핫키) + `EditorShortcuts` (편집기 단축키) 를
한 번에 덮어쓴다. 영상 트림 단축키([ ] / Ctrl+E) 는 두 프리셋 모두 동일.
"""
from __future__ import annotations
from typing import Literal

from .settings import AppSettings, EditorShortcuts, HotkeySettings


PresetName = Literal["windows-standard", "goom-pot", "custom"]


# 두 프리셋의 차이는 글로벌 캡처/녹화 단축키 + 영상 프레임 step 만.
# 도구 단축키(V/R/A/T/C) 는 두 프리셋 동일 (편집기 표준).
PRESETS: dict[str, dict[str, HotkeySettings | EditorShortcuts]] = {
    "windows-standard": {
        "hotkey": HotkeySettings(
            toggle_record="Ctrl+Alt+R",        # 게임 바 충돌 회피
            screenshot_region="Ctrl+Win+S",    # OS Snipping Tool 와 충돌 회피
            screenshot_full="Print",
            toggle_record_full="",
            preset_name="windows-standard",
        ),
        "editor": EditorShortcuts(
            tool_select="V",
            tool_crop="C",
            tool_arrow="A",
            tool_rect="R",
            tool_text="T",
            op_background_removal="Ctrl+Shift+B",
            file_save="Ctrl+S",
            file_save_as="Ctrl+Shift+S",
            file_export_png="Ctrl+E",
            file_open="Ctrl+O",
            view_actual_size="Ctrl+0",
            view_fit="Ctrl+1",
        ),
    },
    "goom-pot": {
        "hotkey": HotkeySettings(
            toggle_record="Ctrl+Shift+T",      # 곰/팟 표준
            screenshot_region="Ctrl+Shift+R",
            screenshot_full="",
            toggle_record_full="",
            preset_name="goom-pot",
        ),
        "editor": EditorShortcuts(
            tool_select="V",
            tool_crop="C",
            tool_arrow="A",
            tool_rect="R",
            tool_text="T",
            op_background_removal="Ctrl+Shift+B",
            file_save="Ctrl+S",
            file_save_as="Ctrl+Shift+S",
            file_export_png="Ctrl+E",
            file_open="Ctrl+O",
            view_actual_size="Ctrl+0",
            view_fit="Ctrl+1",
        ),
    },
}


def apply_preset(settings: AppSettings, name: str) -> None:
    """해당 프리셋의 모든 단축키를 settings 에 일괄 덮어쓰기.

    알 수 없는 이름이면 무시 (ValueError 안 던짐 — UI 가 드롭다운 변경 시 빠르게 반영).
    인스턴스를 새로 만들지 않고 *필드만 덮어써서* 기존 reference (예: ShortcutsPanel
    이 들고 있는 hotkey/editor) 가 끊어지지 않도록 한다.
    """
    preset = PRESETS.get(name)
    if preset is None:
        return
    src_hotkey = preset["hotkey"]
    src_editor = preset["editor"]
    for f in src_hotkey.__dataclass_fields__:
        setattr(settings.hotkey, f, getattr(src_hotkey, f))
    for f in src_editor.__dataclass_fields__:
        setattr(settings.editor_shortcuts, f, getattr(src_editor, f))


def detect_preset(settings: AppSettings) -> str:
    """현재 settings 가 어떤 프리셋과 일치하는지. 일치 안 하면 'custom'."""
    for name, preset in PRESETS.items():
        if (settings.hotkey.toggle_record == preset["hotkey"].toggle_record
                and settings.hotkey.screenshot_region == preset["hotkey"].screenshot_region
                and settings.hotkey.screenshot_full == preset["hotkey"].screenshot_full):
            return name
    return "custom"


def is_first_run(settings: AppSettings) -> bool:
    """첫 실행 — preset_name 이 비어있을 때만. 이후엔 사용자 명시 변경(custom 포함)."""
    return settings.hotkey.preset_name == ""
