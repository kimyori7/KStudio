"""SubtitleExportProgressWindow — Job 시그널 → UI 갱신 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from screen_recorder.ui.subtitle_export_progress import SubtitleExportProgressWindow


@pytest.fixture
def win(qtbot):
    w = SubtitleExportProgressWindow(model_size="base")
    qtbot.addWidget(w)
    w.show()
    return w


def test_initial_state(win):
    assert win.progress_bar.value() == 0
    assert not win.open_folder_btn.isEnabled()
    assert win.captions_view.toPlainText() == ""


def test_modal_is_false(win):
    """사용자 명시: 메인 앱 병행 사용 가능 → 비모달."""
    assert not win.isModal()


def test_on_phase_downloading_sets_label(win):
    win.on_phase_changed("downloading")
    assert "다운로드" in win.phase_label.text()


def test_on_phase_transcribing_sets_label(win):
    win.on_phase_changed("transcribing")
    assert "전사" in win.phase_label.text()


def test_on_download_progress_updates_bar_and_label(win):
    win.on_phase_changed("downloading")
    # 50 MB / 100 MB.
    win.on_download_progress(50 * 1024 * 1024, 100 * 1024 * 1024)
    assert win.progress_bar.value() == 50
    detail = win.detail_label.text()
    assert "MB" in detail
    assert "50" in detail   # 50 MB 받음 또는 50%


def test_on_download_progress_zero_total_shows_received_only(win):
    """total=0 (모를 때) — 받은 양만 표시."""
    win.on_phase_changed("downloading")
    win.on_download_progress(10 * 1024 * 1024, 0)
    assert "10" in win.detail_label.text()


def test_on_transcribe_progress_updates_bar(win):
    win.on_phase_changed("transcribing")
    win.on_transcribe_progress(42)
    assert win.progress_bar.value() == 42


def test_on_segment_ready_appends_text(win):
    win.on_segment_ready(0, 2000, "안녕하세요")
    win.on_segment_ready(2000, 4000, "반갑습니다")
    text = win.captions_view.toPlainText()
    assert "안녕하세요" in text
    assert "반갑습니다" in text


def test_on_segment_ready_includes_timecode(win):
    """시작 시간을 mm:ss 형식으로 줄 머리에 표시."""
    win.on_segment_ready(125_000, 130_000, "테스트")   # 2분 5초
    line = win.captions_view.toPlainText()
    assert "02:05" in line
    assert "테스트" in line


def test_on_finished_enables_folder_button(win, tmp_path):
    dst = tmp_path / "out.srt"
    win.on_finished(dst)
    assert win.open_folder_btn.isEnabled()
    assert "완료" in win.phase_label.text()


def test_on_finished_emits_open_folder_signal(win, tmp_path, qtbot):
    dst = tmp_path / "out.srt"
    win.on_finished(dst)
    with qtbot.waitSignal(win.open_folder_requested, timeout=500) as sig:
        win.open_folder_btn.click()
    assert sig.args == [dst]


def test_on_error_shows_red_message(win):
    win.on_error("Whisper 호출 실패")
    assert "실패" in win.phase_label.text()
    assert "Whisper" in win.detail_label.text()


def test_close_does_not_cancel_job(win, qtbot):
    """비모달 닫기 — job 은 백그라운드 계속 (다이얼로그만 숨김).

    실제 cancel API 없음 — 단순히 close() 호출 후 widget 이 닫히는지만 확인.
    """
    assert win.isVisible()
    win.close()
    assert not win.isVisible()
