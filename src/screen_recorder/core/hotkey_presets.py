"""단축키 프리셋 — 첫 실행 시 사용자가 고른 묶음을 일괄 적용.

두 차원으로 분리:
- 글로벌 차원 (`GLOBAL_PRESETS`): OS 차원 캡처/녹화 핫키 + 편집기 단축키.
  옵션: `windows-standard`, `kstudio-default`.
- 영상 플레이어 차원 (`PLAYER_PRESETS`): 영상 모드 한정 키 (프레임 step, 스냅샷).
  옵션: `kstudio-default`, `goom-style` (곰플레이어 호환).

두 차원이 직교적이라 사용자가 "윈도우 표준 + 곰플 호환" 같은 자유 조합 가능.
"""
from __future__ import annotations
from typing import Literal

from .settings import AppSettings, EditorShortcuts, HotkeySettings, PlayerHotkeys


GlobalPresetName = Literal["windows-standard", "kstudio-default", "custom"]
PlayerPresetName = Literal["kstudio-default", "goom-style", "custom"]


# ---------- 글로벌 차원 (캡처 / 녹화 / 편집기) ----------
# Qt 의 QKeySequence 는 Windows 키를 "Meta" 로 표기 — "Win" 으로 적으면 파싱 실패.
GLOBAL_PRESETS: dict[str, dict[str, HotkeySettings | EditorShortcuts]] = {
    "windows-standard": {
        "hotkey": HotkeySettings(
            toggle_record="Ctrl+Alt+R",         # 게임 바 충돌 회피
            screenshot_region="Ctrl+Meta+S",    # Win+Shift+S 와 비슷한 패턴
            screenshot_full="Print",
            toggle_record_full="",
            preset_name="windows-standard",
        ),
        "editor": EditorShortcuts(
            tool_select="V", tool_crop="C", tool_arrow="A", tool_rect="R", tool_text="T",
            op_background_removal="Ctrl+Shift+B",
            file_save="Ctrl+S", file_save_as="Ctrl+Shift+S",
            file_export_png="Ctrl+E", file_open="Ctrl+O",
            view_actual_size="Ctrl+0", view_fit="Ctrl+1",
        ),
    },
    "kstudio-default": {
        "hotkey": HotkeySettings(
            toggle_record="Ctrl+Shift+T",      # KStudio 기존 기본 (작성자 개인 취향)
            screenshot_region="Ctrl+Shift+R",
            screenshot_full="",
            toggle_record_full="",
            preset_name="kstudio-default",
        ),
        "editor": EditorShortcuts(
            tool_select="V", tool_crop="C", tool_arrow="A", tool_rect="R", tool_text="T",
            op_background_removal="Ctrl+Shift+B",
            file_save="Ctrl+S", file_save_as="Ctrl+Shift+S",
            file_export_png="Ctrl+E", file_open="Ctrl+O",
            view_actual_size="Ctrl+0", view_fit="Ctrl+1",
        ),
    },
}


# ---------- 영상 플레이어 차원 ----------
# 곰플 호환은 frame_step 을 A/D 로 (곰플 표준), 스냅샷을 Ctrl+G 로 (곰플 연속 캡처 키).
# 팟플 호환은 만들지 않음 — 팟플의 frame step Ctrl+←/Ctrl+→ 는 KStudio 의 시크 단축키
# (skip_large) 와, 캡처 Ctrl+S 는 KStudio file_save 와, 영역캡처 Ctrl+E 는 KStudio
# 영상 편집 모드 토글과 의미 충돌. 정직하게 빼고 사용자가 환경설정에서 직접 조정.
PLAYER_PRESETS: dict[str, PlayerHotkeys] = {
    "kstudio-default": PlayerHotkeys(
        frame_back="D",
        frame_forward="F",
        snapshot="Ctrl+Shift+P",
        preset_name="kstudio-default",
    ),
    "goom-style": PlayerHotkeys(
        frame_back="A",                # 곰플 표준: A = 이전 프레임
        frame_forward="D",             # 곰플 표준: D = 다음 프레임
        snapshot="Ctrl+G",             # 곰플 표준: Ctrl+G = 연속 화면 캡처
        preset_name="goom-style",
    ),
}


def apply_global_preset(settings: AppSettings, name: str) -> None:
    """글로벌 프리셋(캡처/녹화/편집기) 의 모든 필드를 in-place 로 덮어쓰기."""
    preset = GLOBAL_PRESETS.get(name)
    if preset is None:
        return
    src_hotkey = preset["hotkey"]
    src_editor = preset["editor"]
    for f in src_hotkey.__dataclass_fields__:
        setattr(settings.hotkey, f, getattr(src_hotkey, f))
    for f in src_editor.__dataclass_fields__:
        setattr(settings.editor_shortcuts, f, getattr(src_editor, f))


def apply_player_preset(settings: AppSettings, name: str) -> None:
    """영상 플레이어 프리셋의 모든 필드를 in-place 로 덮어쓰기."""
    preset = PLAYER_PRESETS.get(name)
    if preset is None:
        return
    for f in preset.__dataclass_fields__:
        setattr(settings.player_hotkeys, f, getattr(preset, f))


# 하위 호환: 기존 코드에서 import 하던 이름 유지.
PRESETS = GLOBAL_PRESETS


def apply_preset(settings: AppSettings, name: str) -> None:
    """글로벌 프리셋 적용 (하위 호환 진입점)."""
    apply_global_preset(settings, name)


def detect_global_preset(settings: AppSettings) -> str:
    for name, preset in GLOBAL_PRESETS.items():
        h = preset["hotkey"]
        if (settings.hotkey.toggle_record == h.toggle_record
                and settings.hotkey.screenshot_region == h.screenshot_region
                and settings.hotkey.screenshot_full == h.screenshot_full):
            return name
    return "custom"


def detect_player_preset(settings: AppSettings) -> str:
    for name, preset in PLAYER_PRESETS.items():
        if (settings.player_hotkeys.frame_back == preset.frame_back
                and settings.player_hotkeys.frame_forward == preset.frame_forward
                and settings.player_hotkeys.snapshot == preset.snapshot):
            return name
    return "custom"


def detect_preset(settings: AppSettings) -> str:
    """하위 호환 — 글로벌 차원만 본다."""
    return detect_global_preset(settings)


def is_first_run(settings: AppSettings) -> bool:
    """첫 실행 — 두 차원 중 하나라도 비었으면 다이얼로그 노출."""
    return (settings.hotkey.preset_name == ""
            or settings.player_hotkeys.preset_name == "")
