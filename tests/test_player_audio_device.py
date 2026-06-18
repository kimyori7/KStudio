"""PlayerWidget 오디오 출력 장치 적용 — 실제 장치로 검증."""
import pytest


def test_set_audio_output_device_applies_to_both_outputs(qtbot):
    from screen_recorder.ui.video.player_widget import PlayerWidget
    from screen_recorder.ui.video.audio_devices_qt import list_outputs, device_id_str

    pw = PlayerWidget()
    qtbot.addWidget(pw)
    outs = list_outputs()
    if not outs:
        pytest.skip("오디오 출력 장치 없는 환경")

    target_id, _ = outs[-1]
    pw.set_audio_output_device(target_id)
    assert pw.audio_output_device_id() == target_id
    assert device_id_str(pw._audio.device()) == target_id
    assert device_id_str(pw._insert_audio.device()) == target_id


def test_empty_id_follows_default(qtbot):
    from screen_recorder.ui.video.player_widget import PlayerWidget
    from screen_recorder.ui.video.audio_devices_qt import default_output_id, device_id_str

    pw = PlayerWidget()
    qtbot.addWidget(pw)
    if not default_output_id():
        pytest.skip("기본 오디오 장치 없는 환경")
    pw.set_audio_output_device("")
    assert pw.audio_output_device_id() == ""
    # 기본 따라가기 → _audio 가 시스템 기본 장치로.
    assert device_id_str(pw._audio.device()) == default_output_id()


def test_unknown_id_falls_back_but_keeps_pref(qtbot):
    from screen_recorder.ui.video.player_widget import PlayerWidget

    pw = PlayerWidget()
    qtbot.addWidget(pw)
    pw.set_audio_output_device("deadbeefdeadbeef")
    # 저장 pref 는 유지(나중에 장치 복귀 시 재매칭), device 는 기본으로 폴백(null 아님).
    assert pw.audio_output_device_id() == "deadbeefdeadbeef"
    assert not pw._audio.device().isNull()
