"""UpdateDialog 통합 카드 — 순수 함수 + 상태 전환 + 시그널."""
from screen_recorder.app.updater.manifest import Manifest
from screen_recorder.ui.tokens import VIDEO_PALETTE
from screen_recorder.ui.update_dialog import UpdateDialog, format_bytes, notes_html

_M = Manifest(version="1.1.0", notes="- 새 기능 A\n- 버그 수정 B",
              full_url="https://x/S.exe", full_sha256="a" * 64)


def _dlg(qtbot) -> UpdateDialog:
    dlg = UpdateDialog("1.0.4", _M, palette=VIDEO_PALETTE)
    qtbot.addWidget(dlg)
    return dlg


def test_format_bytes_units():
    assert format_bytes(512) == "512 B"
    assert format_bytes(10 * 1024) == "10 KB"
    assert format_bytes(25_600_000) == "24.4 MB"        # 24.4140625 MB
    assert format_bytes(2 * 1024 ** 3) == "2.00 GB"


def test_notes_html_bullets():
    html = notes_html("- 기능 A\n- 기능 B", VIDEO_PALETTE)
    assert "기능 A" in html and "<li" in html


def test_notes_html_empty_fallback():
    assert "패치 내역" in notes_html("", VIDEO_PALETTE)


def test_notes_html_escapes():
    assert "<script>" not in notes_html("- <script>x</script>", VIDEO_PALETTE)


def test_prompt_state_components(qtbot):
    dlg = _dlg(qtbot)
    assert "v1.0.4" in dlg._chip.text() and "v1.1.0" in dlg._chip.text()
    assert dlg._footer.currentIndex() == 0          # PROMPT


def test_update_now_signal_and_transition(qtbot):
    dlg = _dlg(qtbot)
    with qtbot.waitSignal(dlg.update_now):
        dlg._now_btn.click()
    assert dlg._footer.currentIndex() == 1          # DOWNLOADING 전환


def test_skip_signal(qtbot):
    dlg = _dlg(qtbot)
    with qtbot.waitSignal(dlg.skipped):
        dlg._skip_btn.click()


def test_set_progress_percent_and_label(qtbot):
    dlg = _dlg(qtbot)
    dlg.start_download()
    dlg.set_progress(50 * 1024 * 1024, 100 * 1024 * 1024)
    assert dlg._bar.value() == 50
    assert "/" in dlg._size_label.text()          # "50.0 MB / 100.0 MB"


def test_set_progress_busy_when_total_zero(qtbot):
    dlg = _dlg(qtbot)
    dlg.start_download()
    dlg.set_progress(1234, 0)                     # total 모름 → busy
    assert dlg._bar.maximum() == 0


def test_cancel_sets_flag_and_disables(qtbot):
    dlg = _dlg(qtbot)
    dlg.start_download()
    dlg._cancel_btn.click()
    assert dlg.was_canceled() is True
    assert not dlg._cancel_btn.isEnabled()


def test_reject_during_download_counts_as_cancel(qtbot):
    dlg = _dlg(qtbot)
    dlg.start_download()
    dlg.reject()                                  # Esc/X 경로
    assert dlg.was_canceled() is True


def test_reject_on_prompt_is_not_cancel(qtbot):
    dlg = _dlg(qtbot)
    dlg.reject()                                  # "나중에" — 취소 아님
    assert dlg.was_canceled() is False


def test_error_state(qtbot):
    dlg = _dlg(qtbot)
    dlg.start_download()
    dlg.show_error()
    assert dlg._footer.currentIndex() == 2        # ERROR
    assert "실패" in dlg._title.text()
