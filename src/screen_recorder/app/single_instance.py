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
- 메시지 형식: 경로를 줄바꿈으로 이어붙인 UTF-8 + 종단 바이트(_EOM). 파일 없이 그냥
  두 번째로 켠 경우엔 `_RAISE_TOKEN` 만 보내 "창만 앞으로" 를 의미.
- 수신 확인(ACK): 서버는 _EOM 까지 받으면 _ACK 1바이트로 응답한다. 파이프 연결·쓰기는
  상대가 크래시 직후 WER 에 얼어붙은 좀비여도 커널 수준에서 성공하므로(2026-07-14
  실사고: 재실행이 좀비에 전달하고 조용히 종료 → '앱이 안 켜짐'), 클라이언트는 ACK
  를 못 받으면 False 를 반환해 스스로 새 주 인스턴스로 기동한다. EOM 없이 끊는
  구형 전송도 서버가 disconnected 시점에 처리한다(하위 호환).
"""
from __future__ import annotations

import logging
import re
import sys
import time
from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 400
_IO_TIMEOUT_MS = 1000
# ACK 대기 상한 — 짧으면 무거운 초기화(WebEngine 콜드 스타트) 중인 정상 인스턴스를
# 좀비로 오판해 창이 두 개 뜬다. 좀비(크래시 정지)일 때 사용자가 이만큼 기다린 뒤
# 새 인스턴스가 뜨는 것이, 조용히 아무것도 안 뜨는 것보다 낫다.
_ACK_TIMEOUT_MS = 5000
_RAISE_TOKEN = "__RAISE__"
_EOM = b"\x04"   # 메시지 종단(End Of Message) — 서버가 '다 받았음'을 아는 기준
_ACK = b"\x06"   # 수신 확인 — 살아 있는(이벤트 루프가 도는) 인스턴스만 보낼 수 있음


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


def try_forward(paths: Sequence[str], name: Optional[str] = None,
                ack_timeout_ms: int = _ACK_TIMEOUT_MS) -> bool:
    """이미 실행 중인 인스턴스에 경로를 전달한다.

    Returns:
        True  — 전달 성공(살아 있는 인스턴스가 ACK). 호출자는 이 프로세스를 종료해야 한다.
        False — 실행 중인 인스턴스 없음 *또는 응답 없음(좀비/정지)*. 호출자가 첫(새 주)
                인스턴스가 된다.

    Windows 에서는 Qt 소켓 대신 Win32 named pipe 를 직접 쓴다 — QLocalSocket 의
    블로킹 waitFor* 는 이벤트 루프가 없는 컨텍스트에서 write 조차 버퍼에 갇힐 수
    있음을 실측(2026-07-14). ctypes 직접 호출은 스레드/루프 상태와 무관하게 결정론적.
    """
    name = name or server_name()
    payload = encode_paths(paths) + _EOM
    if sys.platform == "win32":
        ok = _try_forward_win32(payload, name, ack_timeout_ms)
    else:
        ok = _try_forward_qt(payload, name, ack_timeout_ms)
    if ok:
        logger.info("기존 인스턴스에 %d 개 경로 전달 — 이 프로세스 종료", len(list(paths)))
    return ok


def _try_forward_win32(payload: bytes, name: str, ack_timeout_ms: int) -> bool:
    """Win32 named pipe 직접 전송 — CreateFileW → WriteFile → PeekNamedPipe 폴링(ACK).

    연결·쓰기 성공은 상대의 생존 증거가 아니다(크래시 직후 WER 에 얼어붙은 좀비의
    파이프에도 커널 수준에선 성공). 살아 있는 인스턴스만 보낼 수 있는 ACK 를 못
    받으면 False → 호출자가 새 주 인스턴스로 기동한다(조용한 무반응 실행 방지).
    """
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LPDWORD = ctypes.POINTER(wintypes.DWORD)
    # ⚠ argtypes 를 전부 명시해야 한다 — 기본 변환은 64-bit HANDLE 을 c_int(32-bit)로
    # 잘라 access violation 을 일으킨다(2026-07-14 실측).
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    k32.WaitNamedPipeW.restype = wintypes.BOOL
    k32.WaitNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    k32.WriteFile.restype = wintypes.BOOL
    k32.WriteFile.argtypes = (
        wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD, LPDWORD, wintypes.LPVOID,
    )
    k32.FlushFileBuffers.restype = wintypes.BOOL
    k32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    k32.PeekNamedPipe.restype = wintypes.BOOL
    k32.PeekNamedPipe.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
        LPDWORD, wintypes.LPVOID,
    )
    k32.ReadFile.restype = wintypes.BOOL
    k32.ReadFile.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, LPDWORD, wintypes.LPVOID,
    )
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    INVALID_HANDLE = ctypes.c_void_p(-1).value
    GENERIC_RW = 0x80000000 | 0x40000000
    OPEN_EXISTING = 3
    ERROR_PIPE_BUSY = 231

    pipe_path = rf"\\.\pipe\{name}"
    deadline = time.monotonic() + _CONNECT_TIMEOUT_MS / 1000
    handle = None
    while handle is None:
        h = k32.CreateFileW(pipe_path, GENERIC_RW, 0, None, OPEN_EXISTING, 0, None)
        if h != INVALID_HANDLE:
            handle = h
            break
        if ctypes.get_last_error() != ERROR_PIPE_BUSY:
            return False   # 서버 없음(ERROR_FILE_NOT_FOUND 등) → 내가 첫 인스턴스
        # 파이프 인스턴스 일시 소진 — 짧게 기다렸다 재시도.
        if time.monotonic() >= deadline:
            return False
        k32.WaitNamedPipeW(pipe_path, 50)
    try:
        _allow_foreground()
        written = wintypes.DWORD(0)
        if not k32.WriteFile(handle, payload, len(payload),
                             ctypes.byref(written), None):
            return False
        k32.FlushFileBuffers(handle)
        # ACK 폴링 — PeekNamedPipe 는 논블로킹으로 도착 바이트 수만 본다.
        avail = wintypes.DWORD(0)
        end = time.monotonic() + ack_timeout_ms / 1000
        while time.monotonic() < end:
            if not k32.PeekNamedPipe(handle, None, 0, None,
                                     ctypes.byref(avail), None):
                logger.warning("기존 인스턴스가 파이프를 끊음(종료 중 추정) — 새 인스턴스로 계속")
                return False
            if avail.value > 0:
                buf = ctypes.create_string_buffer(16)
                rd = wintypes.DWORD(0)
                k32.ReadFile(handle, buf, 16, ctypes.byref(rd), None)
                return rd.value > 0
            time.sleep(0.02)
        logger.warning("기존 인스턴스가 응답하지 않음(정지/좀비 추정) — 새 인스턴스로 계속")
        return False
    finally:
        k32.CloseHandle(handle)


def _try_forward_qt(payload: bytes, name: str, ack_timeout_ms: int) -> bool:
    """비-Windows 폴백 — Unix domain socket 은 블로킹 waitFor* 가 신뢰 가능."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False
    _allow_foreground()
    socket.write(payload)
    socket.flush()
    socket.waitForBytesWritten(_IO_TIMEOUT_MS)
    if socket.bytesAvailable() == 0 and not socket.waitForReadyRead(ack_timeout_ms):
        logger.warning("기존 인스턴스가 응답하지 않음(정지/좀비 추정) — 새 인스턴스로 계속")
        socket.abort()
        return False
    socket.readAll()   # ACK 소비
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(_IO_TIMEOUT_MS)
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
        done = {"v": False}      # dispatch 1회 보장
        closed = {"v": False}    # 정리 1회 보장
        self._pending.add(conn)

        def _read() -> None:
            try:
                buf.extend(conn.readAll().data())
                # 종단(_EOM)까지 받으면 즉시 처리 + ACK 응답 — 클라이언트는 이 ACK 로
                # '살아 있는 인스턴스'를 확인한다(좀비 파이프 구별, 2026-07-14).
                if not done["v"] and _EOM in buf:
                    done["v"] = True
                    msg = bytes(buf).split(_EOM, 1)[0]
                    if msg:
                        self._dispatch(decode_paths(msg))
                    conn.write(_ACK)
                    conn.flush()
            except RuntimeError:
                pass   # 앱 종료 등으로 C++ 소켓이 이미 파괴됨 — 무시

        def _finish() -> None:
            if closed["v"]:
                return
            closed["v"] = True
            try:
                if not done["v"]:
                    # EOM 없이 끊는 구형(v1.0.2 이전) 전송 — disconnected 시점에 처리.
                    done["v"] = True
                    buf.extend(conn.readAll().data())
                    # 빈 read 는 읽기 실패 — "창만 앞으로"조차 _RAISE_TOKEN(비어있지
                    # 않음)을 보내므로 buf 가 비면 dispatch 하지 않는다(허위 메시지 방지).
                    if buf:
                        self._dispatch(decode_paths(bytes(buf)))
                # 즉시 deleteLater 하면 ACK 쓰기 완료 콜백(Qt 스레드풀)이 파괴된
                # 소켓을 만져 access violation 이 난다(2026-07-14 실측). close 로
                # I/O 를 멈추고, 파괴는 콜백이 확실히 끝난 뒤로 미룬다. conn 의
                # C++ 부모는 QLocalServer 라 지연 중 서버가 먼저 죽어도 함께 정리된다.
                conn.close()

                def _delete_later_safe() -> None:
                    try:
                        conn.deleteLater()
                    except RuntimeError:
                        pass   # 서버와 함께 이미 파괴됨
                QTimer.singleShot(5000, _delete_later_safe)
            except RuntimeError:
                pass   # 앱 종료 등으로 C++ 소켓이 이미 파괴됨 — 무시
            finally:
                self._pending.discard(conn)

        conn.readyRead.connect(_read)
        conn.disconnected.connect(_finish)
        # 연결 시점에 이미 도착해 있을 수도 있는 데이터.
        if conn.bytesAvailable() > 0:
            _read()
        # 보낸 쪽이 매우 빨리 끊으면 슬롯 진입 시 이미 Unconnected 라 disconnected 가
        # 안 올 수 있다 — 그 경우 직접 마무리(_finish 는 idempotent).
        if conn.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            _finish()
