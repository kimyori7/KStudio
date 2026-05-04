"""LowLevelKeyboardHook 단위 테스트.

실제 Windows hook 등록은 위험하므로 (테스트 환경에서 실제 키 가로채면 다른 테스트
영향) 등록 없이 객체 lifecycle 만 검증. 실제 가로채기 동작은 수동 검증 영역.
"""
from __future__ import annotations
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")


def test_hook_lifecycle_without_install(qtbot):
    """install() 호출 없이 set_targets/uninstall 만 호출해도 안전."""
    from screen_recorder.hotkey.low_level_hook import LowLevelKeyboardHook
    hook = LowLevelKeyboardHook()
    hook.set_targets([(0x000C, ord("S"))])   # Win+Shift+S
    assert hook.is_installed() is False
    hook.uninstall()   # no-op


def test_set_targets_normalizes_int_pairs(qtbot):
    from screen_recorder.hotkey.low_level_hook import LowLevelKeyboardHook
    hook = LowLevelKeyboardHook()
    hook.set_targets([(12, 83), (0, 65)])
    assert (12, 83) in hook._targets
    assert (0, 65) in hook._targets


def test_modifier_constants_match_parser():
    """LL hook 의 modifier 비트가 parser 와 일치 — 같은 (mods, vk) 튜플로 매칭 가능."""
    from screen_recorder.hotkey import low_level_hook as ll
    from screen_recorder.hotkey.parser import parse_hotkey_to_vk
    mods, vk = parse_hotkey_to_vk("Win+Shift+S")
    assert mods == ll.MOD_WIN | ll.MOD_SHIFT
    assert vk == ord("S")


def test_manager_set_intercept_enabled_no_crash(qtbot):
    """HotkeyManager 의 토글 진입점이 install/uninstall 흐름을 안전하게 처리."""
    from screen_recorder.hotkey.manager import HotkeyManager
    mgr = HotkeyManager()
    # 토글 켰다 끄기 — install/uninstall 호출되지만 예외 발생하지 않아야.
    mgr.set_intercept_enabled(True)
    mgr.set_intercept_enabled(False)
    mgr.shutdown()


def test_manager_shutdown_idempotent(qtbot):
    from screen_recorder.hotkey.manager import HotkeyManager
    mgr = HotkeyManager()
    mgr.shutdown()
    mgr.shutdown()   # 두 번째 호출도 안전
