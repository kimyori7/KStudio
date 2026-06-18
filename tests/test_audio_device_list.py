"""audio_device_list — 순수 헬퍼 (Qt 비의존).

- disambiguate_labels: 같은 이름 장치(예: DELL U2724D 2대)에 (2),(3) 붙여 구분.
- resolve_current_id: 저장된 장치 id 가 현재 목록에 있으면 그대로, 없으면 기본 따라가기("").
"""
from screen_recorder.ui.video.audio_device_list import (
    disambiguate_labels, resolve_current_id, FOLLOW_DEFAULT_ID,
)


def test_follow_default_id_is_empty():
    assert FOLLOW_DEFAULT_ID == ""


def test_disambiguate_unique_names_unchanged():
    devs = [("id1", "Realtek Digital Output"), ("id2", "Speakers")]
    assert disambiguate_labels(devs) == [
        ("id1", "Realtek Digital Output"), ("id2", "Speakers"),
    ]


def test_disambiguate_duplicates_get_index_suffix():
    devs = [("a", "DELL U2724D"), ("b", "DELL U2724D"), ("c", "Realtek")]
    assert disambiguate_labels(devs) == [
        ("a", "DELL U2724D"), ("b", "DELL U2724D (2)"), ("c", "Realtek"),
    ]


def test_disambiguate_three_duplicates():
    devs = [("a", "X"), ("b", "X"), ("c", "X")]
    assert disambiguate_labels(devs) == [
        ("a", "X"), ("b", "X (2)"), ("c", "X (3)"),
    ]


def test_resolve_saved_present_returns_saved():
    assert resolve_current_id("id2", ["id1", "id2", "id3"]) == "id2"


def test_resolve_saved_absent_follows_default():
    assert resolve_current_id("idX", ["id1", "id2"]) == FOLLOW_DEFAULT_ID


def test_resolve_empty_is_follow_default():
    assert resolve_current_id("", ["id1", "id2"]) == FOLLOW_DEFAULT_ID
