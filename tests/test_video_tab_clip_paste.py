"""VideoTab — 클립 복사(Ctrl+C) → 다른 영상 탭에 붙여넣기(Ctrl+V).

사용자 흐름 (2026-08-03 요청): 영상 A 를 자르고 그 조각을 선택 → Ctrl+C → 영상 B 탭으로
이동 → Ctrl+V → 조각이 B 의 트랙, 현재 인디케이터 위치에 붙는다.
"""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.ui.video.clip_clipboard import clipboard
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture(autouse=True)
def clean_clipboard():
    """전역 클립보드 — 테스트끼리 새어 나가지 않도록 앞뒤로 비운다."""
    clipboard().clear()
    yield
    clipboard().clear()


def _mp4(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 200_000)
    return p


def _make_tab(qtbot, path: Path, tmp_path: Path, duration_ms: int = 10_000) -> VideoTab:
    tab = VideoTab(
        path=path, source_label=path.stem, duration_ms=duration_ms,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / f"sidecars_{path.stem}",
    )
    qtbot.addWidget(tab)
    tab.set_edit_mode(True)
    tab.show()
    qtbot.waitExposed(tab)
    return tab


def _select_segment(tab: VideoTab, index: int) -> str:
    """트랙의 index 번째 클립을 활성 선택으로 (lane 좌클릭과 같은 상태)."""
    seg = tab.sidecar().video_track[index]
    tab._active_kind = "segment"
    tab._active_id = seg.id
    return seg.id


def test_copy_clip_and_paste_into_another_video_tab(qtbot, tmp_path):
    """A 에서 자른 조각을 Ctrl+C → B 탭에서 Ctrl+V → B 의 트랙에 A 의 파일이 들어온다."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    # A 를 4초 지점에서 자르고 뒤쪽 조각(4000~10000) 을 선택.
    first_id = tab_a.sidecar().video_track[0].id
    assert tab_a._edit_controller.split_segment(first_id, at_local_ms=4000) is True
    _select_segment(tab_a, 1)

    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)
    assert clipboard().kind() == "segment"

    before = len(tab_b.sidecar().video_track)
    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)

    track_b = tab_b.sidecar().video_track
    assert len(track_b) == before + 1
    pasted = [s for s in track_b if s.src == str(a_path)]
    assert len(pasted) == 1, "A 의 파일을 가리키는 클립이 B 의 트랙에 있어야 한다"
    assert pasted[0].duration_ms == 6000       # 4000~10000 조각 길이 보존
    assert pasted[0].src_in_ms == 4000         # 원본에서 잘라낸 구간 그대로


def test_paste_lands_at_playhead_when_slot_is_free(qtbot, tmp_path):
    """인디케이터가 0 이고 그 자리가 비어 있으면 0 에 붙는다 (트랙 끝으로 밀리지 않음)."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    # A: 앞쪽 4초 조각을 복사.
    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    _select_segment(tab_a, 0)
    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)

    # B: 원래 클립을 5초로 밀어 앞 5초를 비우고, 인디케이터를 0 에 둔다.
    b_seg_id = tab_b.sidecar().video_track[0].id
    tab_b._edit_controller.set_segment_start(b_seg_id, 5000)
    tab_b.timeline.set_position_ms(0)

    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)

    pasted = next(s for s in tab_b.sidecar().video_track if s.src == str(a_path))
    assert pasted.start_ms == 0


def test_paste_inserts_at_playhead_and_pushes_following_clips(qtbot, tmp_path):
    """인디케이터 자리가 다른 클립과 겹치면 그 자리에 끼워 넣고 뒤 클립을 민다.

    2026-08-19 변경: 이전에는 들어갈 빈칸을 못 찾으면 트랙 맨 뒤에 붙여, 다른 영상에서
    가져온 클립이 엉뚱한 곳에 놓였다. 이제 놓은 지점이 가리키는 이음매에 넣고 그 뒤
    클립들을 부족분만큼 오른쪽으로 민다.
    """
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    _select_segment(tab_a, 0)
    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)

    # B 의 클립은 0~10000. 인디케이터 2000 은 그 한가운데 — 겹친다.
    tab_b.timeline.set_position_ms(2000)
    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)

    pasted = next(s for s in tab_b.sidecar().video_track if s.src == str(a_path))
    others = [s for s in tab_b.sidecar().video_track if s.id != pasted.id]
    # 인디케이터(2000) 에서 가장 가까운 이음매는 0 — 거기에 들어가고 B 의 클립이 밀린다.
    assert pasted.start_ms == 0
    assert others[0].start_ms == pasted.duration_ms, "기존 클립이 새 클립 길이만큼 밀림"
    # 어느 것도 겹치지 않는다.
    for o in others:
        assert not (pasted.start_ms < o.end_ms and pasted.end_ms > o.start_ms)


def test_clip_carries_contained_effects_with_new_ids(qtbot, tmp_path):
    """클립 안에 완전히 들어 있던 효과도 같이 따라오고, id 는 새로 발급된다."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    # 뒤쪽 조각(4000~10000) 안에 캡션 추가.
    tab_a.lanes_widget().request_add.emit("caption", 5000, 0)
    src_cap = tab_a.sidecar().effects[0]
    assert src_cap.out_ms <= 10_000, "테스트 전제: 캡션이 조각 안에 완전히 들어감"
    offset = src_cap.in_ms - 4000
    duration = src_cap.out_ms - src_cap.in_ms

    _select_segment(tab_a, 1)
    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)

    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)

    pasted_seg = next(s for s in tab_b.sidecar().video_track if s.src == str(a_path))
    caps = [e for e in tab_b.sidecar().effects if e.type == "caption"]
    assert len(caps) == 1
    assert caps[0].id != src_cap.id
    assert caps[0].in_ms == pasted_seg.start_ms + offset
    assert caps[0].out_ms - caps[0].in_ms == duration
    # 원본 탭은 그대로.
    assert len(tab_a.sidecar().effects) == 1


def test_paste_is_one_undo_step(qtbot, tmp_path):
    """클립 + 동반 효과 붙여넣기는 history 1회 — Ctrl+Z 한 번으로 통째로 되돌아간다."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    tab_a.lanes_widget().request_add.emit("caption", 5000, 0)
    _select_segment(tab_a, 1)
    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)

    before_track = len(tab_b.sidecar().video_track)
    before_effects = len(tab_b.sidecar().effects)
    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)
    qtbot.keyClick(tab_b, Qt.Key_Z, Qt.ControlModifier)

    assert len(tab_b.sidecar().video_track) == before_track
    assert len(tab_b.sidecar().effects) == before_effects


def test_paste_twice_makes_two_independent_clips(qtbot, tmp_path):
    """복사 한 번으로 여러 번 붙여넣기 — 클립보드는 비워지지 않고 id 는 매번 새로."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    _select_segment(tab_a, 0)
    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)

    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)

    pasted = [s for s in tab_b.sidecar().video_track if s.src == str(a_path)]
    assert len(pasted) == 2
    assert pasted[0].id != pasted[1].id


def test_edit_mode_off_blocks_paste_with_notice(qtbot, tmp_path):
    """편집 모드가 꺼진 탭에서는 붙여넣지 않는다 — 조용히 무시하지 않고 이유를 알린다."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    _select_segment(tab_a, 0)
    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)

    tab_b.set_edit_mode(False)
    flashes: list[str] = []
    tab_b.player.flash_action = flashes.append
    before = len(tab_b.sidecar().video_track)
    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_V, Qt.ControlModifier)

    assert len(tab_b.sidecar().video_track) == before
    assert any("편집 모드" in f for f in flashes)
    assert clipboard().kind() == "segment", "실패해도 클립보드는 유지"


def test_zero_length_clip_is_not_copied(qtbot, tmp_path, monkeypatch):
    """길이를 알 수 없는 클립은 복사하지 않는다 — 붙여넣으면 되살릴 수 없는 조각이 된다."""
    import screen_recorder.services.media_probe as media_probe
    monkeypatch.setattr(media_probe, "probe_duration_ms", lambda _src: 0)

    a_path = _mp4(tmp_path, "a.mp4")
    tab = _make_tab(qtbot, a_path, tmp_path, duration_ms=0)
    assert tab.sidecar().video_track[0].duration_ms == 0
    _select_segment(tab, 0)

    flashes: list[str] = []
    tab.player.flash_action = flashes.append
    tab.setFocus()
    qtbot.keyClick(tab, Qt.Key_C, Qt.ControlModifier)

    assert clipboard().kind() is None
    assert any("길이" in f for f in flashes)


def test_copy_without_selection_keeps_clipboard(qtbot, tmp_path):
    """선택 없이 Ctrl+C — 이전에 복사해 둔 내용이 날아가지 않는다."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    _select_segment(tab_a, 0)
    tab_a.setFocus()
    qtbot.keyClick(tab_a, Qt.Key_C, Qt.ControlModifier)

    tab_b._active_kind = None
    tab_b._active_id = None
    tab_b.setFocus()
    qtbot.keyClick(tab_b, Qt.Key_C, Qt.ControlModifier)
    assert clipboard().kind() == "segment"


def test_track_menu_copy_and_paste_at_clicked_position(qtbot, tmp_path):
    """우클릭 메뉴 경로 — 복사는 그 클립을 선택으로 만들고, 붙여넣기는 **클릭한 위치**로."""
    a_path, b_path = _mp4(tmp_path, "a.mp4"), _mp4(tmp_path, "b.mp4")
    tab_a = _make_tab(qtbot, a_path, tmp_path)
    tab_b = _make_tab(qtbot, b_path, tmp_path)

    first_id = tab_a.sidecar().video_track[0].id
    tab_a._edit_controller.split_segment(first_id, at_local_ms=4000)
    second_id = tab_a.sidecar().video_track[1].id
    tab_a.timeline.video_track_lane.request_copy.emit(second_id)
    assert tab_a._active_id == second_id, "복사한 클립이 활성 선택이 된다"
    assert clipboard().kind() == "segment"

    # B: 원본 클립을 뒤로 밀어 앞을 비우고, 인디케이터는 엉뚱한 자리에 둔다.
    b_seg_id = tab_b.sidecar().video_track[0].id
    tab_b._edit_controller.set_segment_start(b_seg_id, 20_000)
    tab_b.timeline.set_position_ms(9_000)
    # 메뉴는 클릭 지점(2000) 을 넘긴다 — 인디케이터(9000) 가 아니라 그쪽에 붙어야 한다.
    tab_b.timeline.video_track_lane.request_paste_at.emit(2000)

    pasted = next(s for s in tab_b.sidecar().video_track if s.src == str(a_path))
    assert pasted.start_ms == 2000
