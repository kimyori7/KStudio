"""AutoEditReviewDialog — 슬라이더 변경 시 카운트 라이브 갱신, '적용' 시 effects 반환."""
from screen_recorder.autoedit.result import AutoEditResult
from screen_recorder.ui.autoedit.review_dialog import AutoEditReviewDialog


def test_dialog_shows_initial_silence_count(qtbot):
    raw = AutoEditResult(source_hash="x", silence_segments=[(0, 1000), (2000, 5000)])
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    # 기본 임계값 800ms — 둘 다 통과.
    assert "2개" in d.silence_count_label().text()


def test_slider_change_updates_count(qtbot):
    raw = AutoEditResult(source_hash="x", silence_segments=[(0, 500), (2000, 5000)])
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    d.silence_slider().setValue(1500)   # ms — 500ms 짜리 컷 제외
    d._flush_filter_now()
    assert "1개" in d.silence_count_label().text()


def test_disable_silence_card_dims_slider(qtbot):
    raw = AutoEditResult(source_hash="x", silence_segments=[(0, 5000)])
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    d.silence_checkbox().setChecked(False)
    d._flush_filter_now()
    assert "0개" in d.silence_count_label().text()
    assert not d.silence_slider().isEnabled()


def test_apply_returns_effects(qtbot):
    raw = AutoEditResult(source_hash="x", silence_segments=[(0, 5000)])
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    effects = d.compute_effects()
    assert len(effects) == 1
    assert effects[0].type == "cut"


def test_caption_card_count(qtbot):
    raw = AutoEditResult(source_hash="x", transcript_segments=[
        {"in_ms": 0, "out_ms": 1000, "text": "hi"},
        {"in_ms": 1000, "out_ms": 2000, "text": "bye"},
    ])
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    assert "2개" in d.caption_count_label().text()
