"""audio_devices_qt — QMediaDevices 열거/매칭 헬퍼 (실제 장치 round-trip)."""
import pytest


def test_list_outputs_and_roundtrip(qtbot):
    from screen_recorder.ui.video.audio_devices_qt import (
        list_outputs, find_output, device_id_str,
    )
    outs = list_outputs()
    if not outs:
        pytest.skip("오디오 출력 장치 없는 환경")
    id0, desc0 = outs[0]
    assert id0          # id 문자열 존재
    assert isinstance(desc0, str)
    dev = find_output(id0)
    assert dev is not None
    assert device_id_str(dev) == id0    # id round-trip 일치


def test_find_output_unknown_or_empty_returns_none(qtbot):
    from screen_recorder.ui.video.audio_devices_qt import find_output
    assert find_output("deadbeefdeadbeef") is None
    assert find_output("") is None


def test_default_output_id_is_in_list_or_empty(qtbot):
    from screen_recorder.ui.video.audio_devices_qt import (
        list_outputs, default_output_id,
    )
    outs = list_outputs()
    if not outs:
        pytest.skip("오디오 출력 장치 없는 환경")
    did = default_output_id()
    # 기본 장치 id 는 목록 안에 있어야 한다(또는 빈 문자열).
    assert did == "" or did in [i for i, _ in outs]
