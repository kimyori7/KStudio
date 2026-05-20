"""GpuInstallDialog — 초기 상태 + 로그 append + finished_ok/error 시그널.

QProcess 자체는 실제 pip 호출 없이 직접 슬롯 호출로 시뮬레이션 — 단위 테스트는 UI
+ 시그널 동작만 검증.
"""
from __future__ import annotations

import pytest

from PySide6.QtCore import QProcess

from screen_recorder.ui.gpu_install_dialog import GpuInstallDialog


@pytest.fixture
def dlg(qtbot):
    d = GpuInstallDialog()
    qtbot.addWidget(d)
    d.show()
    return d


def test_initial_state(dlg):
    """대기 중 — 시작 버튼 활성, 로그 비어 있음."""
    assert dlg.install_btn.isEnabled()
    assert "대기" in dlg.status_label.text()
    assert dlg.log_view.toPlainText() == ""
    assert dlg._process is None


def test_modal_is_false(dlg):
    """다른 작업 병행 가능 — 비모달."""
    assert not dlg.isModal()


def test_append_log_appends_text_to_view(dlg):
    dlg._append_log("hello\n")
    dlg._append_log("world\n")
    assert "hello" in dlg.log_view.toPlainText()
    assert "world" in dlg.log_view.toPlainText()


def test_on_finished_success_emits_finished_ok(dlg, qtbot):
    """exit code 0 → finished_ok emit + 상태 라벨 초록."""
    with qtbot.waitSignal(dlg.finished_ok, timeout=500):
        dlg._on_finished(0, QProcess.ExitStatus.NormalExit)
    assert "완료" in dlg.status_label.text()
    assert "#16a34a" in dlg.status_label.styleSheet()


def test_on_finished_failure_emits_finished_error(dlg, qtbot):
    with qtbot.waitSignal(dlg.finished_error, timeout=500) as sig:
        dlg._on_finished(1, QProcess.ExitStatus.NormalExit)
    assert "실패" in dlg.status_label.text()
    assert "#dc2626" in dlg.status_label.styleSheet()
    assert "1" in sig.args[0]   # 종료 코드 포함


def test_finished_signals_emitted_only_once(dlg, qtbot):
    """on_finished 두 번 호출돼도 시그널은 한 번만 — 중복 모달 방지."""
    received = []
    dlg.finished_ok.connect(lambda: received.append("ok"))
    dlg._on_finished(0, QProcess.ExitStatus.NormalExit)
    dlg._on_finished(0, QProcess.ExitStatus.NormalExit)
    assert received == ["ok"]


def test_on_error_emits_finished_error(dlg, qtbot):
    """프로세스 시작 실패 (FailedToStart 등) → finished_error."""
    with qtbot.waitSignal(dlg.finished_error, timeout=500):
        dlg._on_error(QProcess.ProcessError.FailedToStart)
    assert "오류" in dlg.status_label.text()


def test_install_clicked_disables_button(dlg, monkeypatch):
    """설치 시작 시 버튼 비활성 + QProcess 생성 — 실제 실행 없이 검증."""
    # QProcess.start 모킹 — 실제 pip 호출 방지.
    started_calls = []
    orig_start = QProcess.start

    def _stub_start(self, program, arguments):
        started_calls.append((program, list(arguments)))
        # 실제 시작하지 않음.

    monkeypatch.setattr(QProcess, "start", _stub_start)
    dlg._on_install_clicked()
    assert not dlg.install_btn.isEnabled()
    assert dlg._process is not None
    assert "설치 중" in dlg.status_label.text()
    assert len(started_calls) == 1
    program, args = started_calls[0]
    assert program.endswith("python.exe") or "python" in program.lower()
    # python -u -m pip install ... — 첫 4개 정확히.
    assert args[:4] == ["-u", "-m", "pip", "install"]
    assert "--no-input" in args
    assert "--upgrade" in args
    assert "nvidia-cublas-cu12" in args
    assert "nvidia-cudnn-cu12" in args


def test_install_log_shows_command_and_waiting_message(dlg, monkeypatch):
    """설치 시작 시 명령어와 '응답 대기 중' 안내가 즉시 로그에 — 사용자가 멈춘 줄 알지 않도록."""
    monkeypatch.setattr(QProcess, "start", lambda self, p, a: None)
    dlg._on_install_clicked()
    text = dlg.log_view.toPlainText()
    assert "$" in text                 # 명령어 prefix
    assert "pip" in text
    assert "대기" in text               # "응답 대기 중…" 안내


def test_started_signal_appends_marker(dlg):
    """started 시그널 핸들러가 '프로세스 시작됨' 마커 추가 — 사용자에게 가시 피드백."""
    dlg._on_started()
    assert "시작" in dlg.log_view.toPlainText()
