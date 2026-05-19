from PySide6.QtCore import Qt
from screen_recorder.ui.autoedit.progress_dialog import AutoEditProgressDialog


def test_progress_dialog_updates_label_and_bar(qtbot):
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    d.update_progress("자막 (2/4)", 0.5)
    assert "자막" in d.label().text()
    assert d.bar().value() == 50


def test_cancel_emits_signal(qtbot):
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.cancelled, timeout=1000):
        d.cancel_button().click()


def test_initial_bar_is_indeterminate(qtbot):
    """첫 실행 모델 다운로드 등으로 progress emit 지연 시, '응답 없음' 처럼 보이지 않도록.

    첫 update_progress 호출 시 determinate(0/100) 으로 전환.
    """
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    # 초기 — indeterminate (0/0).
    assert d.bar().maximum() == 0
    # 첫 progress emit → determinate.
    d.update_progress("무음컷 (1/4)", 0.1)
    assert d.bar().maximum() == 100
    assert d.bar().value() == 10


def test_initial_label_mentions_first_run_download(qtbot):
    """다이얼로그 표시 직후 사용자가 보는 라벨에 첫 실행 시 다운로드 안내."""
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    assert "Whisper" in d.label().text() or "다운로드" in d.label().text()


def test_set_phase_label_download(qtbot):
    """다운로드 phase 라벨에 모델명 + 다운로드 안내."""
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    d.set_phase_label("large-v3", is_download=True)
    assert "large-v3" in d.label().text()
    assert "다운로드" in d.label().text()


def test_set_phase_label_analyze(qtbot):
    """분석 phase 라벨에 모델명만 (다운로드 표시 없음)."""
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    d.set_phase_label("base", is_download=False)
    assert "base" in d.label().text()
    assert "분석" in d.label().text()
