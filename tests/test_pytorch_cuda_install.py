"""PyTorch CUDA 자동 감지 + cu130 wheel 설치 흐름.

이전 사용자 시나리오: PyTorch installer 가 CPU wheel 만 설치 → Qwen 로드 시
GPU 미사용 → 매우 느림. 사용자가 직접 `--index-url cu130` 으로 재설치 필요.

이 패치 의도:
1. nvidia-smi 가 있으면 → NVIDIA GPU 감지 → cu130 wheel 자동 선택.
2. GpuInstallDialog 가 index_url 받아 `--index-url` + `--force-reinstall` 추가.
3. 이미 CUDA torch 설치되어 있으면 → installer 자체를 skip + chain.

회귀 보호:
- index_url=None 면 기존 동작 100% 유지 (cuBLAS 케이스).
- GPU 미감지 시 default 인덱스 (CPU wheel) — 사용자 명시 노트 + 진행.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from screen_recorder.ui.gpu_install_dialog import GpuInstallDialog


# ============================================================
# GpuInstallDialog — index_url 파라미터
# ============================================================
def test_index_url_appears_in_pip_args(qtbot, monkeypatch):
    """index_url 전달 시 pip 명령에 --index-url + --force-reinstall 포함.

    실제 QProcess 인스턴스의 start 메서드만 가로채 — 시그널/enum 전부 진짜.
    """
    dlg = GpuInstallDialog(
        packages=("torch", "torchvision"),
        index_url="https://download.pytorch.org/whl/cu130",
    )
    qtbot.addWidget(dlg)

    captured: dict = {}

    from PySide6.QtCore import QProcess

    def _fake_start(self, program, args):
        captured["program"] = program
        captured["args"] = args
        # 실제 pip 실행 안 됨 — finished 시그널도 안 옴 (테스트는 args 만 확인).

    monkeypatch.setattr(QProcess, "start", _fake_start, raising=False)

    dlg._on_install_clicked()

    assert "args" in captured, "QProcess.start 가 호출되지 않음"
    assert "--index-url" in captured["args"], (
        f"--index-url 가 pip args 에 없음: {captured['args']}"
    )
    idx = captured["args"].index("--index-url")
    assert captured["args"][idx + 1] == "https://download.pytorch.org/whl/cu130"
    assert "--force-reinstall" in captured["args"], (
        "CPU→CUDA 전환 위해 --force-reinstall 필요"
    )
    assert "torch" in captured["args"]
    assert "torchvision" in captured["args"]


def test_no_index_url_keeps_original_behavior(qtbot, monkeypatch):
    """index_url 없으면 --index-url / --force-reinstall 모두 없음 — cuBLAS 케이스 회귀 보호."""
    dlg = GpuInstallDialog(packages=("nvidia-cublas-cu12",))
    qtbot.addWidget(dlg)

    captured: dict = {}

    from PySide6.QtCore import QProcess

    def _fake_start(self, program, args):
        captured["args"] = args

    monkeypatch.setattr(QProcess, "start", _fake_start, raising=False)
    dlg._on_install_clicked()

    assert "args" in captured
    assert "--index-url" not in captured["args"]
    assert "--force-reinstall" not in captured["args"]


# ============================================================
# nvidia-smi GPU 감지
# ============================================================
def test_detect_nvidia_gpu_present(monkeypatch):
    """nvidia-smi 가 GPU 정보 출력 → True."""
    from screen_recorder.ui.agent.chat_panel import _detect_nvidia_gpu

    def _fake_run(*_a, **_kw):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "NVIDIA GeForce RTX 5060 Ti\n"
        return result

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert _detect_nvidia_gpu() is True


def test_detect_nvidia_gpu_missing(monkeypatch):
    """nvidia-smi 가 없음 (FileNotFoundError) → False."""
    from screen_recorder.ui.agent.chat_panel import _detect_nvidia_gpu

    def _fake_run(*_a, **_kw):
        raise FileNotFoundError("nvidia-smi not found")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert _detect_nvidia_gpu() is False


def test_detect_nvidia_gpu_non_zero_exit(monkeypatch):
    """nvidia-smi 실행됐지만 driver 문제로 exit≠0 → False."""
    from screen_recorder.ui.agent.chat_panel import _detect_nvidia_gpu

    def _fake_run(*_a, **_kw):
        result = MagicMock()
        result.returncode = 9
        result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert _detect_nvidia_gpu() is False


def test_pytorch_index_url_for_nvidia_returns_cu130(monkeypatch):
    """NVIDIA GPU 감지 + torch CUDA 미설치 → cu130 wheel URL."""
    from screen_recorder.ui.agent import chat_panel as cp

    monkeypatch.setattr(cp, "_detect_nvidia_gpu", lambda: True)
    monkeypatch.setattr(cp, "_is_torch_cuda_available", lambda: False)

    url = cp._pytorch_index_url_for_install()
    assert url == "https://download.pytorch.org/whl/cu130"


def test_pytorch_index_url_no_gpu_returns_none(monkeypatch):
    """GPU 없음 → None (default 인덱스 = CPU wheel)."""
    from screen_recorder.ui.agent import chat_panel as cp

    monkeypatch.setattr(cp, "_detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(cp, "_is_torch_cuda_available", lambda: False)

    assert cp._pytorch_index_url_for_install() is None


def test_pytorch_index_url_when_cuda_already_works_returns_none(monkeypatch):
    """이미 CUDA torch 설치되어 있으면 → None (재설치 skip 시그널)."""
    from screen_recorder.ui.agent import chat_panel as cp

    monkeypatch.setattr(cp, "_detect_nvidia_gpu", lambda: True)
    monkeypatch.setattr(cp, "_is_torch_cuda_available", lambda: True)

    # 이미 CUDA OK 면 installer 자체를 안 띄울 거고, url 만 묻는다면 None.
    assert cp._pytorch_index_url_for_install() is None
