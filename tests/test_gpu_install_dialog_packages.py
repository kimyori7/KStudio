"""GpuInstallDialog packages 파라미터 — PyTorch 설치 재사용 위함."""
from __future__ import annotations

import pytest

from screen_recorder.ui.gpu_install_dialog import GpuInstallDialog


def test_default_packages_are_nvidia(qtbot):
    """파라미터 없으면 기존 NVIDIA 패키지 동작 — 회귀 보호."""
    from screen_recorder.agent.transcript import NVIDIA_PIP_PACKAGES
    dlg = GpuInstallDialog()
    qtbot.addWidget(dlg)
    assert dlg._packages == list(NVIDIA_PIP_PACKAGES)


def test_custom_packages_for_pytorch(qtbot):
    """packages 인자로 PyTorch list 전달 가능."""
    PYTORCH_PACKAGES = (
        "torch", "transformers", "accelerate", "bitsandbytes",
        "qwen-omni-utils[decord]", "soundfile",
    )
    dlg = GpuInstallDialog(packages=PYTORCH_PACKAGES, title="PyTorch 설치")
    qtbot.addWidget(dlg)
    assert dlg._packages == list(PYTORCH_PACKAGES)
    assert "PyTorch" in dlg.windowTitle()


def test_custom_info_text(qtbot):
    """info_text 인자로 안내 메시지 커스터마이즈."""
    dlg = GpuInstallDialog(
        packages=("torch",),
        info_text="PyTorch 단독 설치 안내 (테스트)",
    )
    qtbot.addWidget(dlg)
    assert "PyTorch 단독" in dlg.info_label.text()
