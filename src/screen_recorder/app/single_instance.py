"""단일 인스턴스 — 두 번째 실행을 첫 인스턴스로 전달하고 조용히 종료.

탐색기에서 .md / .kstudio 를 더블클릭할 때마다 새 KStudio 창이 또 뜨는 것을 막는다.
이미 실행 중인 인스턴스가 있으면 그 인스턴스에 파일 경로를 보내(라이브러리 추가 + 탭
표시 + 창 앞으로) 처리하게 하고, 새로 뜬 프로세스는 MainWindow 를 만들기 전에 종료한다.

프로세스 간 통신은 Qt `QLocalServer`/`QLocalSocket`(Windows named pipe / Unix domain
socket). 별도 의존성 없이 PySide6 만으로 동작한다.

설계:
- 파이프 이름은 **사용자별**(`server_name()`) — 다중 사용자 PC 에서 충돌 방지.
- 첫 인스턴스: `SingleInstanceServer().listen()` 로 파이프를 선점. 무거운 초기화(torch,
  WebEngine) 전에 listen 해 두면, 초기화 도중 들어온 두 번째 실행도 OS 백로그에 쌓였다가
  이벤트 루프가 돌 때 처리된다. 핸들러가 아직 없으면 큐에 보관 후 `set_handler` 에서 flush.
- 두 번째 인스턴스: `try_forward()` 가 연결되면 경로를 보내고 True 반환(=종료해야 함).
  연결 실패면(=실행 중 인스턴스 없음) False → 자기가 첫 인스턴스가 된다.
- 메시지 형식: 경로를 줄바꿈으로 이어붙인 UTF-8. 파일 없이 그냥 두 번째로 켠 경우엔
  `_RAISE_TOKEN` 만 보내 "창만 앞으로" 를 의미.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 400
_IO_TIMEOUT_MS = 1000
_RAISE_TOKEN = "__RAISE__"


def server_name() -> str:
    """사용자별 고유 파이프 이름. 다중 사용자 PC 에서 충돌하지 않도록 username 을 섞는다."""
    user = "default"
    try:
        import getpass  # noqa: PLC0415

        user = getpass.getuser() or "default"
    except Exception:  # noqa: BLE001 — username 조회 실패해도 이름은 만들어져야 함
        user = "default"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", user)
    return f"KStudio-singleton-{safe}"


def encode_paths(paths: Sequence[str]) -> bytes:
    """경로 목록 → 전송 바이트. 빈 목록이면 RAISE 토큰(창만 앞으로)."""
    if not paths:
        return _RAISE_TOKEN.encode("utf-8")
    return "\n".join(paths).encode("utf-8")


def decode_paths(data: bytes) -> List[str]:
    """수신 바이트 → 경로 목록. RAISE 토큰이거나 비면 빈 목록."""
    text = bytes(data).decode("utf-8", errors="replace").strip()
    if not text or text == _RAISE_TOKEN:
        return []
    return [line for line in text.split("\n") if line]


def _allow_foreground() -> None:
    """(Windows) 기존 인스턴스가 포커스를 가져올 수 있도록 허용 — 베스트 에포트.

    두 번째 프로세스는 막 실행돼 포그라운드 권한이 있으므로, 종료 전에 ASFW_ANY 로
    아무 프로세스나 포그라운드를 가져갈 수 있게 풀어 준다. 안 하면 기존 창의
    activateWindow() 가 작업표시줄 깜빡임만 일으키고 앞으로 안 올 수 있다.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # noqa: PLC0415

        ASFW_ANY = -1
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:  # noqa: BLE001
        pass


def try_forward(paths: Sequence[str], name: Optional[str] = None) -> bool:
    """이미 실행 중인 인스턴스에 경로를 전달한다.

    Returns:
        True  — 전달 성공(이미 실행 중). 호출자는 이 프로세스를 종료해야 한다.
        False — 실행 중인 인스턴스 없음. 호출자가 첫 인스턴스가 된다.
    """
    name = name or server_name()
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False
    _allow_foreground()
    socket.write(encode_paths(paths))
    socket.flush()
    socket.waitForBytesWritten(_IO_TIMEOUT_MS)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(_IO_TIMEOUT_MS)
    logger.info("기존 인스턴스에 %d 개 경로 전달 — 이 프로세스 종료", len(list(paths)))
    return True


class SingleInstanceServer(QObject):
    """첫 인스턴스가 여는 서버. 두 번째 인스턴스의 메시지를 핸들러로 전달한다.

    핸들러가 아직 설정되지 않았을 때 들어온 메시지는 큐에 보관했다가 `set_handler`
    호출 시 순서대로 flush 한다(무거운 초기화 도중 들어온 두 번째 실행 대응).
    """

    def __init__(self, name: Optional[str] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._name = name or server_name()
        self._handler: Optional[Callable[[List[str]], None]] = None
        self._queue: List[List[str]] = []
        self._pending: set = set()  # 처리 중인 연결 보관(GC 방지)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    @property
    def name(self) -> str:
        return self._name

    def pending_count(self) -> int:
        """핸들러 설정 전 큐에 쌓인 메시지 수(테스트/관찰용)."""
        return len(self._queue)

    def listen(self) -> bool:
        """파이프를 선점. 죽은 인스턴스가 남긴 파이프는 먼저 제거한다."""
        QLocalServer.removeServer(self._name)
        ok = self._server.listen(self._name)
        if not ok:
            logger.warning("single-instance 서버 listen 실패: %s", self._server.errorString())
        return ok

    def set_handler(self, handler: Callable[[List[str]], None]) -> None:
        """메시지 핸들러 설정 + 그동안 큐에 쌓인 메시지 flush."""
        self._handler = handler
        pending, self._queue = self._queue, []
        for paths in pending:
            handler(paths)

    def close(self) -> None:
        self._server.close()

    def _dispatch(self, paths: List[str]) -> None:
        if self._handler is None:
            self._queue.append(paths)
        else:
            self._handler(paths)

    def _on_new_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        # Windows named pipe 에서 슬롯 안에서 waitForReadyRead 로 동기 read 하면 데이터를
        # 못 받는 경우가 있다. 정석대로 이벤트 루프로 돌아가 readyRead/disconnected 시그널
        # 로 읽는다. 보낸 쪽은 write 후 곧 disconnect 하므로, 누적분을 disconnected 에서
        # 마지막으로 비운 뒤 dispatch 한다.
        buf = bytearray()
        done = {"v": False}
        self._pending.add(conn)

        def _read() -> None:
            buf.extend(conn.readAll().data())

        def _finish() -> None:
            if done["v"]:
                return
            done["v"] = True
            buf.extend(conn.readAll().data())
            # 빈 read 는 읽기 실패 — "창만 앞으로"조차 _RAISE_TOKEN(비어있지 않음)을
            # 보내므로 buf 가 비면 dispatch 하지 않는다(허위 빈 메시지 방지).
            if buf:
                self._dispatch(decode_paths(bytes(buf)))
            self._pending.discard(conn)
            conn.deleteLater()

        conn.readyRead.connect(_read)
        conn.disconnected.connect(_finish)
        # 연결 시점에 이미 도착해 있을 수도 있는 데이터.
        if conn.bytesAvailable() > 0:
            _read()
        # 보낸 쪽이 매우 빨리 끊으면 슬롯 진입 시 이미 Unconnected 라 disconnected 가
        # 안 올 수 있다 — 그 경우 직접 마무리(_finish 는 idempotent).
        if conn.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            _finish()
