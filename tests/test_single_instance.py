"""단일 인스턴스(single-instance) IPC 검증.

탐색기에서 .md 더블클릭 시 두 번째 KStudio 가 또 뜨는 대신, 이미 실행 중인
인스턴스로 경로가 전달되는지 확인한다. 실제 2-프로세스 없이도 같은 프로세스 안에서
QLocalServer(서버) + QLocalSocket(try_forward 클라이언트)로 배선을 검증한다.

서버 이름은 테스트마다 PID 를 섞어 고유하게 만들어 동시 실행 충돌을 피한다.
"""
import os
import threading

import pytest

from screen_recorder.app import single_instance as si


def _forward_in_thread(paths, name):
    """try_forward 를 워커 스레드에서 실행 — 메인 스레드는 이벤트 루프로 서버를
    서비스한다(2-프로세스 동시성 모사). 같은 스레드면 클라이언트가 루프를 막아
    서버가 accept/read 를 못 해 데이터가 전달되지 않는다.
    """
    result = {}

    def run():
        result["ok"] = si.try_forward(paths, name=name)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, result


# ---- 순수 함수 (Qt 불필요) ----

def test_server_name_is_user_specific_and_safe():
    name = si.server_name()
    assert name.startswith("KStudio-singleton-")
    # 파이프 이름에 위험한 문자가 없어야 함.
    assert all(c.isalnum() or c in "_.-" for c in name)


def test_encode_decode_roundtrip():
    paths = [r"C:\a\b.md", r"D:\sp ace\문서.markdown"]
    assert si.decode_paths(si.encode_paths(paths)) == paths


def test_empty_paths_encode_to_raise_token_and_decode_empty():
    data = si.encode_paths([])
    assert data == si._RAISE_TOKEN.encode("utf-8")
    assert si.decode_paths(data) == []


def test_decode_blank_is_empty():
    assert si.decode_paths(b"") == []
    assert si.decode_paths(b"   \n  ") == []


# ---- IPC (Qt 이벤트 루프 필요) ----

@pytest.fixture
def uniq_name():
    # PID + 테스트별 고유 이름 — 다른 테스트/세션과 파이프 충돌 방지.
    return f"KStudio-test-{os.getpid()}"


def test_try_forward_returns_false_when_no_server(qapp, uniq_name):
    # 아무도 listen 하지 않는 이름 → 연결 실패 → False(=내가 첫 인스턴스).
    assert si.try_forward([r"C:\x.md"], name=uniq_name + "-none") is False


def test_forward_delivers_paths_to_running_server(qtbot, qapp, uniq_name):
    received = []
    server = si.SingleInstanceServer(name=uniq_name + "-a")
    server.set_handler(lambda paths: received.append(paths))
    assert server.listen() is True

    sent = [r"C:\foo\hello.md", r"C:\bar\문서.md"]
    t, result = _forward_in_thread(sent, server.name)

    qtbot.waitUntil(lambda: len(received) >= 1, timeout=5000)
    # ACK 왕복이 끝날 때까지 메인 스레드가 이벤트 루프를 계속 펌핑해야 한다 —
    # join 으로 먼저 막으면 서버의 ACK flush 가 전달되지 못한다(단일 프로세스 테스트
    # 한정 아티팩트, 실제 2-프로세스에선 서버 루프가 계속 돎).
    qtbot.waitUntil(lambda: "ok" in result, timeout=5000)
    t.join(timeout=5000)
    assert result["ok"] is True
    assert received[0] == sent
    server.close()


def test_forward_empty_means_raise_only(qtbot, qapp, uniq_name):
    received = []
    server = si.SingleInstanceServer(name=uniq_name + "-b")
    server.set_handler(lambda paths: received.append(paths))
    server.listen()

    t, result = _forward_in_thread([], server.name)
    qtbot.waitUntil(lambda: len(received) >= 1, timeout=5000)
    qtbot.waitUntil(lambda: "ok" in result, timeout=5000)   # ACK 왕복까지 펌핑
    t.join(timeout=5000)
    assert result["ok"] is True
    assert received[0] == []  # 빈 목록 = "창만 앞으로"
    server.close()


def test_messages_before_handler_are_queued_then_flushed(qtbot, qapp, uniq_name):
    # 핸들러를 나중에 설정 — 무거운 초기화 도중 들어온 두 번째 실행 시나리오.
    server = si.SingleInstanceServer(name=uniq_name + "-c")
    server.listen()
    t, result = _forward_in_thread([r"C:\queued.md"], server.name)

    # 서버가 연결/메시지를 처리하도록 이벤트 루프를 돌린다(아직 핸들러 없음 → 큐에 보관).
    qtbot.waitUntil(lambda: server.pending_count() >= 1, timeout=5000)
    qtbot.waitUntil(lambda: "ok" in result, timeout=5000)   # ACK 왕복까지 펌핑
    t.join(timeout=5000)
    assert result["ok"] is True

    received = []
    server.set_handler(lambda paths: received.append(paths))
    # set_handler 가 큐를 즉시 flush.
    assert received == [[r"C:\queued.md"]]
    server.close()


# ---- 좀비 인스턴스 감지 (2026-07-14 실사고: 크래시 직후 WER 에 얼어붙은 인스턴스의
# 파이프에 연결·쓰기는 커널 수준에서 성공 → 두 번째 실행이 조용히 종료돼
# 사용자에겐 '앱이 안 켜짐'으로 보임. 살아 있는 인스턴스만 ACK 를 보낼 수 있다) ----

def test_forward_returns_false_when_server_never_acks(qtbot, qapp, uniq_name):
    """파이프는 살아 있지만 처리가 없는(이벤트 루프 정지) 인스턴스 → ACK 타임아웃
    → False 반환으로 호출자가 새 주 인스턴스로 기동해야 한다."""
    from PySide6.QtNetwork import QLocalServer
    name = uniq_name + "-zombie"
    QLocalServer.removeServer(name)
    zombie = QLocalServer()
    assert zombie.listen(name)      # 연결만 받고 아무 응답 없음 — WER 정지 모사
    result = {}

    def run():
        result["ok"] = si.try_forward([r"C:\x.md"], name=name, ack_timeout_ms=300)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    qtbot.waitUntil(lambda: "ok" in result, timeout=5000)
    t.join(timeout=5000)
    assert result["ok"] is False
    zombie.close()


def test_server_still_handles_legacy_sender_without_eom(qtbot, qapp, uniq_name):
    """구형(EOM 없이 write 후 즉시 disconnect) 전송도 계속 처리 — 하위 호환."""
    from PySide6.QtNetwork import QLocalSocket
    received = []
    server = si.SingleInstanceServer(name=uniq_name + "-legacy")
    server.set_handler(lambda paths: received.append(paths))
    assert server.listen()

    def run():
        s = QLocalSocket()
        s.connectToServer(uniq_name + "-legacy")
        s.waitForConnected(1000)
        s.write(b"C:/old.md")
        s.flush()
        s.waitForBytesWritten(1000)
        s.disconnectFromServer()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    qtbot.waitUntil(lambda: len(received) >= 1, timeout=5000)
    t.join(timeout=5000)
    assert received[0] == ["C:/old.md"]
    server.close()
