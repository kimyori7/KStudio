"""ModelDownloadWindow — 비모달 별창 단위 테스트."""
from __future__ import annotations

import pytest
from screen_recorder.ui.model_download_window import ModelDownloadWindow


def test_creates_with_repo_id_and_size(qtbot):
    win = ModelDownloadWindow(
        repo_id="Qwen/Qwen2.5-Omni-7B",
        display_name="Qwen2.5-Omni 7B",
        estimated_size_gb=8.0,
    )
    qtbot.addWidget(win)
    assert "Qwen" in win.windowTitle()


def test_phase_label_updates(qtbot):
    win = ModelDownloadWindow(
        repo_id="Qwen/Qwen2.5-Omni-7B",
        display_name="Qwen",
        estimated_size_gb=1.0,
    )
    qtbot.addWidget(win)
    win.set_phase("downloading")
    assert "다운로드" in win.phase_label.text() or "downloading" in win.phase_label.text().lower()
    win.set_phase("loading")
    assert "로드" in win.phase_label.text() or "로딩" in win.phase_label.text()
    win.set_phase("done")
    assert "완료" in win.phase_label.text()


def test_progress_update_displays_percent(qtbot):
    win = ModelDownloadWindow(
        repo_id="x",
        display_name="x",
        estimated_size_gb=1.0,
    )
    qtbot.addWidget(win)
    win.update_progress(received_bytes=512 * 1024 * 1024, total_bytes=1024 * 1024 * 1024)
    # 50% 표시.
    assert "50" in win.progress_label.text() or win.progress_bar.value() == 50


def test_close_emits_hidden_not_destroy(qtbot):
    """닫기 = 숨김만 — 백그라운드 다운로드 계속."""
    win = ModelDownloadWindow(
        repo_id="x", display_name="x", estimated_size_gb=1.0,
    )
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.close()
    assert not win.isVisible()
    win.show()
    qtbot.waitExposed(win)
    assert win.isVisible()
