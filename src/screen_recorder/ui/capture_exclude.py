"""Windows SetWindowDisplayAffinity 래퍼 — 창을 화면 캡처에서 제외."""
from __future__ import annotations
import ctypes
import logging
import sys

from PySide6.QtWidgets import QWidget

_WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Windows 10 version 2004 이상

_logged_once = False


def exclude_from_capture(widget: QWidget) -> bool:
    """
    위젯의 네이티브 윈도우 핸들에 WDA_EXCLUDEFROMCAPTURE 를 설정.
    dxcam/DXGI/OBS 등 거의 모든 화면 캡처 API가 이 플래그를 존중해서
    해당 창을 녹화 결과에 포함시키지 않음.

    - 위젯이 이미 show() 되었거나 winId가 유효해야 함. 호출 전에 show() 권장.
    - Windows 10 버전 2004(20H1) 이상에서만 동작. 이전 버전에서는 False 반환.
    - Windows 아닌 플랫폼에서는 False 반환 (기능 자체 비활성화).
    """
    global _logged_once
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        if hwnd == 0:
            return False
        result = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE)
        if not result and not _logged_once:
            # 한 번만 로그에 남김 (같은 에러가 여러 창에서 반복될 수 있음)
            err = ctypes.windll.kernel32.GetLastError()
            logging.getLogger(__name__).warning(
                "SetWindowDisplayAffinity failed (error=%d). "
                "Windows 10 2004+ (20H1) 이상이 필요합니다. "
                "UI가 녹화에 포함될 수 있습니다.",
                err,
            )
            _logged_once = True
        return bool(result)
    except Exception as e:
        if not _logged_once:
            logging.getLogger(__name__).warning("exclude_from_capture 실패: %s", e)
            _logged_once = True
        return False
