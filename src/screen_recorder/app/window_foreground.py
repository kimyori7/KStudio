"""Windows에서 창을 확실히 최상단(포그라운드)으로 끌어올린다.

왜 필요한가:
    탐색기에서 `.md` 를 더블클릭하면 두 번째 KStudio 프로세스가 떴다가, 이미 실행
    중인 인스턴스로 파일 경로를 넘기고(single_instance) 자기는 종료한다. 그러면
    *기존* 인스턴스(백그라운드 상태)가 창을 앞으로 띄워야 하는데, Windows 는 보안상
    백그라운드 프로세스가 포그라운드를 가로채는 것을 막는다. 그래서 Qt 의
    `raise_()`/`activateWindow()` 만으로는 작업표시줄만 깜빡이고 창이 안 올라오는
    경우가 많다.

표준 우회법(둘을 함께 써야 안정적):
    1) 새로 뜬 프로세스가 종료 전에 `AllowSetForegroundWindow(ASFW_ANY)` 로
       "포그라운드 넘겨도 된다" 권한을 푼다 — single_instance._allow_foreground.
    2) 기존 프로세스가 현재 포그라운드 스레드의 입력 큐에 잠깐 `AttachThreadInput`
       으로 붙어 `SetForegroundWindow` 권한을 확보한 뒤 창을 올린다 — 이 모듈.
    추가로, 활성화 직전 포그라운드 잠금 타임아웃을 0 으로 낮췄다가 원복한다.

설계 원칙:
    - Windows 가 아니면 no-op(False). 다른 OS 에서도 import/호출은 가능해야 함.
    - 어떤 단계가 실패해도 예외를 삼킨다 — 포커스 실패가 앱을 죽이면 안 된다
      (파일을 열어주는 흐름 한가운데서 호출된다).
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# Win32 상수
_SW_RESTORE = 9
_SPI_GETFOREGROUNDLOCKTIMEOUT = 0x2000
_SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
_SPIF_SENDCHANGE = 0x0002


def force_foreground(hwnd: int) -> bool:
    """주어진 창 핸들을 포그라운드로 끌어올린다. 성공 여부를 반환.

    Windows 가 아니거나 hwnd 가 없으면 False. 실패해도 예외를 던지지 않는다.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes  # noqa: PLC0415 — Windows 전용

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 최소화돼 있으면 먼저 복원(복원 안 하면 SetForegroundWindow 가 무시될 수 있음).
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)

        # 포그라운드 잠금 타임아웃을 잠깐 0 으로 — 읽기에 성공했을 때만 변경하고,
        # 무슨 일이 있어도 finally 에서 원복한다. (0 으로 남으면 시스템 전역으로 아무
        # 앱이나 포커스를 가로챌 수 있으므로 절대 그대로 두면 안 된다.)
        prev_timeout = ctypes.c_uint(0)
        got_timeout = bool(
            user32.SystemParametersInfoW(
                _SPI_GETFOREGROUNDLOCKTIMEOUT, 0, ctypes.byref(prev_timeout), 0
            )
        )
        if got_timeout:
            user32.SystemParametersInfoW(
                _SPI_SETFOREGROUNDLOCKTIMEOUT, 0, ctypes.c_void_p(0), _SPIF_SENDCHANGE
            )

        fg_thread = 0
        this_thread = 0
        attached = False
        try:
            # 현재 포그라운드 스레드에 입력 큐를 붙여 SetForegroundWindow 권한 확보.
            fg = user32.GetForegroundWindow()
            fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            this_thread = kernel32.GetCurrentThreadId()
            if fg_thread and fg_thread != this_thread:
                attached = bool(
                    user32.AttachThreadInput(this_thread, fg_thread, True)
                )
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(this_thread, fg_thread, False)
            if got_timeout:
                user32.SystemParametersInfoW(
                    _SPI_SETFOREGROUNDLOCKTIMEOUT,
                    0,
                    ctypes.c_void_p(prev_timeout.value),
                    _SPIF_SENDCHANGE,
                )
        return True
    except Exception as e:  # noqa: BLE001 — 포커스 실패가 앱을 죽이면 안 됨
        logger.debug("force_foreground 실패: %s", e)
        return False
