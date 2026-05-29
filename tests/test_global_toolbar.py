from screen_recorder.core.state import RecorderState
from screen_recorder.ui.global_toolbar import GlobalToolbar
from screen_recorder.ui.mode_controller import AppMode


def test_default_buttons_in_idle(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    # 영상 모드 + IDLE: record 만 표시
    tb.set_mode(AppMode.VIDEO)
    assert not tb.record_btn.isHidden()
    assert tb.pause_btn.isHidden()
    assert tb.stop_btn.isHidden()


def test_image_mode_hides_recording_controls(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.IMAGE)
    # 이미지 모드: 녹화 컨트롤 숨김, 캡처 + 저장/복사 표시
    assert tb.record_btn.isHidden()
    assert tb.pause_btn.isHidden()
    assert tb.stop_btn.isHidden()
    assert not tb.capture_region_btn.isHidden()
    assert not tb.capture_full_btn.isHidden()
    assert not tb.save_btn.isHidden()
    assert not tb.copy_btn.isHidden()


def test_video_mode_hides_capture_and_actions(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.VIDEO)
    # 영상 모드: 캡처/저장/복사 숨김
    assert tb.capture_region_btn.isHidden()
    assert tb.capture_full_btn.isHidden()
    assert tb.save_btn.isHidden()
    assert tb.copy_btn.isHidden()


def test_mode_toggle_emits(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.mode_clicked, timeout=200) as blocker:
        tb.image_btn.click()
    assert blocker.args == [AppMode.IMAGE]
    with qtbot.waitSignal(tb.mode_clicked, timeout=200) as blocker:
        tb.video_btn.click()
    assert blocker.args == [AppMode.VIDEO]


def test_set_mode_updates_active_button(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.VIDEO)
    assert tb.video_btn.isChecked()
    assert not tb.image_btn.isChecked()


def test_video_mode_hides_save_copy(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.VIDEO)
    assert tb.save_btn.isHidden()
    assert tb.copy_btn.isHidden()


def test_recording_state_changes_button_visibility(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    # 영상 모드에서만 녹화 컨트롤이 의미 있음
    tb.set_mode(AppMode.VIDEO)
    tb.set_recording_state(RecorderState.RECORDING)
    assert not tb.pause_btn.isHidden()
    assert not tb.stop_btn.isHidden()
    assert tb.record_btn.isHidden()


def test_target_changed_signal(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.target_changed, timeout=200) as blocker:
        tb._target_btns["region"].click()
    assert blocker.args[0] == "region"


def test_format_changed_signal(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.mode_value_changed, timeout=200) as blocker:
        tb._format_btns["gif"].click()
    assert blocker.args[0] == "gif"


def test_keep_visible_toggle_emits_signal(qtbot):
    """'내 화면에 보이기' 체크박스 토글 → keep_visible_during_capture_changed."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    assert tb.keep_visible_chk.isChecked() is False
    with qtbot.waitSignal(tb.keep_visible_during_capture_changed, timeout=200) as blocker:
        tb.keep_visible_chk.setChecked(True)
    assert blocker.args == [True]


def test_keep_visible_toggle_off_emits_false(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.keep_visible_chk.setChecked(True)
    with qtbot.waitSignal(tb.keep_visible_during_capture_changed, timeout=200) as blocker:
        tb.keep_visible_chk.setChecked(False)
    assert blocker.args == [False]


def test_set_target_updates_button_state(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_target("window")
    assert tb._target_btns["window"].isChecked()
    assert tb.current_target() == "window"


def test_global_toolbar_has_remove_bg_action_no_button(qtbot):
    """배경 제거 버튼은 ToolPalette 로 옮겨졌고 GlobalToolbar 에는 QAction 만 남아있다."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    assert tb.find_action("remove_bg") is not None
    assert not hasattr(tb, "remove_bg_btn")


# ============================================================
# 다운로드 진행률 라벨 — 설정 버튼 왼쪽에 표시 (2026-05-22)
# 사용자가 ModelDownloadWindow 닫아도 진행률 잃지 않게.
# ============================================================
def test_download_progress_label_hidden_by_default(qtbot):
    """평소 (다운로드 없음) 에는 라벨 숨김 — 툴바 공간 안 잡아먹음."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    assert hasattr(tb, "download_progress_label")
    assert tb.download_progress_label.isHidden()


def test_set_download_progress_shows_label_with_percent_and_size(qtbot):
    """set_download_progress(received, total, name) → 라벨에 '% (X.XG/Y.YG)' 표시 + visible."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    GB = 1024 * 1024 * 1024
    tb.set_download_progress(
        received_bytes=int(4.3 * GB),
        total_bytes=int(15 * GB),
        model_name="Qwen2.5 7B Instruct",
    )
    assert not tb.download_progress_label.isHidden()
    text = tb.download_progress_label.text()
    # 퍼센트 + GB 표기 포함.
    assert "28%" in text or "29%" in text   # 4.3/15 = 28.67%
    assert "4.3" in text
    assert "15.0" in text
    assert "G" in text or "GB" in text
    # 툴팁에 모델 이름 — 라벨 텍스트가 짧으므로 어떤 모델인지 안내.
    assert "Qwen2.5 7B Instruct" in tb.download_progress_label.toolTip()


def test_set_download_progress_handles_unknown_total(qtbot):
    """total=0 (예상 크기 모름) 일 때 — 받은 양만 표시, percent 생략."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    MB = 1024 * 1024
    tb.set_download_progress(
        received_bytes=500 * MB,
        total_bytes=0,
        model_name="Unknown",
    )
    assert not tb.download_progress_label.isHidden()
    text = tb.download_progress_label.text()
    # 받은 양은 표시되어야.
    assert "500" in text   # 500 MB
    # percent 안 나옴 (분모 0 보호).
    assert "%" not in text


def test_clear_download_progress_hides_label(qtbot):
    """clear_download_progress() → 라벨 다시 숨김 (다운로드 완료/에러 시)."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_download_progress(
        received_bytes=1, total_bytes=100, model_name="x",
    )
    assert not tb.download_progress_label.isHidden()
    tb.clear_download_progress()
    assert tb.download_progress_label.isHidden()


def test_download_progress_label_left_of_preferences_btn(qtbot):
    """라벨이 설정 버튼 왼쪽에 — layout 순서 보장."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    layout = tb.layout()
    # 두 위젯의 layout index 비교.
    label_idx = None
    btn_idx = None
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is tb.download_progress_label:
            label_idx = i
        elif w is tb.preferences_btn:
            btn_idx = i
    assert label_idx is not None, "download_progress_label 이 layout 에 없음"
    assert btn_idx is not None, "preferences_btn 이 layout 에 없음"
    assert label_idx < btn_idx, (
        f"라벨이 설정 버튼 오른쪽 (label={label_idx} btn={btn_idx})"
    )


def test_document_mode_button_emits(qtbot):
    from screen_recorder.ui.mode_controller import AppMode
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    received = []
    tb.mode_clicked.connect(received.append)
    tb.document_btn.click()
    assert received == [AppMode.DOCUMENT]


def test_document_mode_hides_recording_and_capture(qtbot):
    from screen_recorder.ui.mode_controller import AppMode
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.show()
    tb.set_mode(AppMode.DOCUMENT)
    assert not tb.record_btn.isVisible()
    assert not tb.capture_region_btn.isVisible()
