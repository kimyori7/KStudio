"""UI 스레드 마샬링 헬퍼 — HTTP 워커 스레드에서 Qt UI 스레드로 호출 디스패치.

KStudio 의 거의 모든 상태(QImage, 탭, 라이브러리 등) 는 UI 스레드에서만 안전하게
접근할 수 있다. HTTP 핸들러는 워커 스레드에서 도착하므로 직접 main_window 메서드를
부르면 race condition / 크래시 위험.

`UIDispatcher` 는 워커 스레드에서 호출 가능한 `call(fn, *args, timeout=...)` API 를
제공한다. 내부적으로 Qt Signal 을 emit → QueuedConnection 슬롯이 UI 스레드에서
실행 → threading.Event 로 워커 스레드를 깨움.
"""
from __future__ import annotations
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot


class UIDispatcher(QObject):
    """HTTP 워커 → UI 스레드 호출 마샬러.

    `call(fn, *args)` 는 `fn` 을 UI 스레드에서 실행하고 반환값을 워커 스레드에
    돌려준다. timeout 초 안에 끝나지 않으면 `TimeoutError`. fn 안에서 발생한 예외는
    워커 스레드에서 다시 raise 된다.

    UIDispatcher 인스턴스는 **반드시 UI 스레드에서 생성** 해야 한다 — Signal 의
    수신자(self) 가 어느 스레드에 있느냐로 슬롯 실행 스레드가 결정되기 때문.
    """

    _trigger = Signal(object)   # holder dict

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._trigger.connect(self._run, Qt.QueuedConnection)

    @Slot(object)
    def _run(self, holder: dict) -> None:
        try:
            holder["value"] = holder["fn"](*holder["args"])
        except Exception as e:   # noqa: BLE001 — 호출자에 그대로 전달
            holder["error"] = e
        finally:
            holder["done"].set()

    def call(self, fn: Callable[..., Any], *args, timeout: float = 10.0) -> Any:
        """워커 스레드에서 호출 → fn 을 UI 스레드에서 실행 → 결과 반환."""
        holder = {
            "fn": fn,
            "args": args,
            "value": None,
            "error": None,
            "done": threading.Event(),
        }
        self._trigger.emit(holder)
        if not holder["done"].wait(timeout=timeout):
            raise TimeoutError(
                f"UI thread call timed out after {timeout}s: {fn.__name__}"
            )
        if holder["error"] is not None:
            raise holder["error"]
        return holder["value"]
