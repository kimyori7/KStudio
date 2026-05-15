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


def test_scene_card_count(qtbot):
    raw = AutoEditResult(source_hash="x", scene_changes=[(5000, 35.0)])
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    d.scene_checkbox().setChecked(True)
    d._flush_filter_now()
    assert "1개" in d.scene_count_label().text()


def test_bpm_card_off_by_default(qtbot):
    raw = AutoEditResult(source_hash="x")
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    assert not d.bpm_checkbox().isChecked()


def test_model_combo_lists_all_whisper_sizes(qtbot):
    """자막 카드의 모델 콤보 — 5개 사이즈 다 보임."""
    raw = AutoEditResult(source_hash="x")
    d = AutoEditReviewDialog(raw)
    qtbot.addWidget(d)
    sizes = [d.model_combo().itemData(i) for i in range(d.model_combo().count())]
    assert sizes == ["tiny", "base", "small", "medium", "large-v3"]


def test_model_combo_default_matches_current(qtbot):
    """current_whisper_model 인자로 콤보 기본 선택 결정."""
    raw = AutoEditResult(source_hash="x")
    d = AutoEditReviewDialog(raw, current_whisper_model="medium")
    qtbot.addWidget(d)
    assert d.model_combo().currentData() == "medium"


def test_reanalyze_button_disabled_when_model_unchanged(qtbot):
    """현재 모델 그대로면 의미 없는 재분석 방지 — 버튼 비활성."""
    raw = AutoEditResult(source_hash="x")
    d = AutoEditReviewDialog(raw, current_whisper_model="large-v3")
    qtbot.addWidget(d)
    assert not d.reanalyze_button().isEnabled()


def test_reanalyze_button_enabled_after_model_change(qtbot):
    """모델 변경하면 재분석 활성."""
    raw = AutoEditResult(source_hash="x")
    d = AutoEditReviewDialog(raw, current_whisper_model="large-v3")
    qtbot.addWidget(d)
    for i in range(d.model_combo().count()):
        if d.model_combo().itemData(i) == "base":
            d.model_combo().setCurrentIndex(i)
            break
    assert d.reanalyze_button().isEnabled()


def test_reanalyze_click_emits_signal_with_new_model(qtbot):
    """재분석 클릭 → reanalyze_requested(new_model) emit + 다이얼로그 reject."""
    raw = AutoEditResult(source_hash="x")
    d = AutoEditReviewDialog(raw, current_whisper_model="large-v3")
    qtbot.addWidget(d)
    for i in range(d.model_combo().count()):
        if d.model_combo().itemData(i) == "medium":
            d.model_combo().setCurrentIndex(i)
            break
    with qtbot.waitSignal(d.reanalyze_requested, timeout=1000) as blocker:
        d.reanalyze_button().click()
    assert blocker.args == ["medium"]
