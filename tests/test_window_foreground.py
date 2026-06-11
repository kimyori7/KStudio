"""window_foreground.force_foreground 의 안전 계약 검증.

이 함수의 핵심 동작(창을 실제로 최상단으로 끌어올리기)은 Windows OS 고유 동작이라
자동 테스트로 검증할 수 없다 — 사용자 실측이 유일한 확인 방법이다. 여기서는 그
대신 **안전 계약**만 검증한다:

1. Windows 가 아니면 아무 OS 호출도 하지 않고 False 를 반환한다(no-op).
2. 잘못된 창 핸들(hwnd=0)이 와도 예외를 던지지 않는다 — 포커스 실패가 앱을
   죽이면 안 되기 때문(파일을 넘겨받아 여는 흐름 한가운데서 호출되므로).
"""
import sys

from screen_recorder.app.window_foreground import force_foreground


def test_force_foreground_is_noop_off_windows(monkeypatch):
    """win32 가 아니면 OS 호출 없이 즉시 False."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert force_foreground(12345) is False


def test_force_foreground_never_raises_on_bad_hwnd():
    """잘못된 핸들(0)에도 예외를 삼키고 bool 을 반환한다(앱을 죽이지 않음)."""
    result = force_foreground(0)
    assert isinstance(result, bool)
