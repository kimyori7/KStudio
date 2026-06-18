"""PlayerPanel(환경설정) 오디오 출력 장치 드롭다운 — populate/선택/시그널.

장치 선택 UI 는 컨트롤바 → 환경설정 '영상 플레이어' 패널로 이동(2026-06-17).
"""


def test_follow_default_is_first_and_no_signal_on_populate(qtbot):
    from screen_recorder.ui.panels.player_panel import PlayerPanel
    from screen_recorder.core.settings import PlayerSettings

    panel = PlayerPanel(PlayerSettings())
    qtbot.addWidget(panel)
    got: list = []
    panel.audio_device_changed.connect(got.append)

    # 0번 = 시스템 기본 따라가기 (userData "").
    assert panel.audio_device_combo.itemData(0) == ""
    assert "기본" in panel.audio_device_combo.itemText(0)
    # 생성 중 populate 로는 시그널 발화 안 함.
    assert got == []


def test_user_change_writes_settings_and_emits(qtbot):
    from screen_recorder.ui.panels.player_panel import PlayerPanel
    from screen_recorder.core.settings import PlayerSettings

    settings = PlayerSettings()
    panel = PlayerPanel(settings)
    qtbot.addWidget(panel)
    got: list = []
    panel.audio_device_changed.connect(got.append)

    # 가짜 장치를 직접 추가·선택 → 전역 설정 기록 + 시그널 (실제 장치 유무와 무관하게 검증).
    panel.audio_device_combo.addItem("가짜 스피커", "fakeid123")
    idx = panel.audio_device_combo.findData("fakeid123")
    panel.audio_device_combo.setCurrentIndex(idx)
    assert got == ["fakeid123"]
    assert settings.audio_output_device == "fakeid123"

    # 다시 '기본 따라가기'(0번) 선택 → "" 기록.
    panel.audio_device_combo.setCurrentIndex(0)
    assert got[-1] == ""
    assert settings.audio_output_device == ""
