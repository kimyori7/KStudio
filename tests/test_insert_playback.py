"""InsertPlaybackController — 결합 시간축 위에서 메인/보조 player 동기화.

Qt 영상 재생 자체는 mock 으로 추상화 — controller 의 결정만 단위 테스트.
"""
from unittest.mock import MagicMock

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.ui.video.insert_playback import InsertPlaybackController


def _make_controller(main_duration_ms=10000):
    main = MagicMock()
    main.duration_ms.return_value = main_duration_ms
    main.position_ms.return_value = 0
    insert = MagicMock()
    insert.insert_position_ms.return_value = 0
    return InsertPlaybackController(main_player=main, insert_host=insert), main, insert


def _sidecar_with_cut(in_ms, out_ms, src="b.mp4", src_in=0, src_out=0, src_dur=0):
    return Sidecar(effects=[CutEffect(
        in_ms=in_ms, out_ms=out_ms,
        src=src, src_in_ms=src_in, src_out_ms=src_out, src_duration_ms=src_dur,
    )])


def test_sets_combined_duration_when_sidecar_changes():
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(3000, 6000, src_in=0, src_out=4000, src_dur=4000)
    ctrl.set_sidecar(sc, main_duration_ms=10000)
    assert ctrl.combined_duration_ms() == 11000   # 10000 - 3000(잘림) + 4000(insert) = 11000


def test_no_cuts_combined_equals_main():
    ctrl, _, _ = _make_controller(10000)
    ctrl.set_sidecar(Sidecar(), main_duration_ms=10000)
    assert ctrl.combined_duration_ms() == 10000


def test_seek_combined_in_main_segment_routes_to_main():
    ctrl, main, insert = _make_controller(10000)
    ctrl.set_sidecar(_sidecar_with_cut(3000, 6000, src_in=0, src_out=4000, src_dur=4000), 10000)
    ctrl.seek_combined_ms(1500)
    main.seek_ms.assert_called_once_with(1500)
    insert.show_insert_surface.assert_called_with(False)


def test_seek_combined_in_insert_segment_routes_to_insert():
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(3000, 6000, src="b.mp4", src_in=0, src_out=4000, src_dur=4000)
    cut_id = sc.effects[0].id
    ctrl.set_sidecar(sc, 10000)
    ctrl.seek_combined_ms(5000)   # insert 안 (insert 시작 3000 + 2000)
    main.pause.assert_called()
    main.seek_ms.assert_called_with(6000)   # cut.out_ms 로 미리 (이탈 시점에 도달하도록)
    insert.set_insert_source.assert_called_once()
    args, kwargs = insert.set_insert_source.call_args
    assert kwargs.get("seek_ms") == 2000   # source_ms = src_in_ms 0 + 2000
    insert.show_insert_surface.assert_called_with(True)


def test_main_position_in_main_segment_emits_combined():
    ctrl, main, insert = _make_controller(10000)
    ctrl.set_sidecar(_sidecar_with_cut(3000, 6000, src_in=0, src_out=4000, src_dur=4000), 10000)
    received = []
    ctrl.combined_position_changed.connect(received.append)
    ctrl.on_main_position_changed(2000)
    assert received[-1] == 2000


def test_main_position_after_cut_emits_combined_with_insert_offset():
    ctrl, main, insert = _make_controller(10000)
    ctrl.set_sidecar(_sidecar_with_cut(3000, 6000, src_in=0, src_out=4000, src_dur=4000), 10000)
    received = []
    ctrl.combined_position_changed.connect(received.append)
    # main 7000 ms = cut 적용 후 결합 = 7000 - 3000(잘림) + 4000(insert) = 8000
    ctrl.on_main_position_changed(7000)
    assert received[-1] == 8000


def test_insert_position_emits_combined():
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(3000, 6000, src_in=0, src_out=4000, src_dur=4000)
    ctrl.set_sidecar(sc, 10000)
    ctrl._active_cut_id = sc.effects[0].id   # insert 진입한 상태 시뮬레이션
    received = []
    ctrl.combined_position_changed.connect(received.append)
    ctrl.on_insert_position_changed(1500)   # B 의 1500 ms = 결합 3000 + 1500 = 4500
    assert received[-1] == 4500


def test_main_position_at_cut_in_triggers_insert():
    """메인이 cut.in_ms 에 도달 → 보조 setSource + show + play, 메인 pause."""
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(3000, 6000, src="b.mp4", src_in=0, src_out=4000, src_dur=4000)
    ctrl.set_sidecar(sc, 10000)
    ctrl.on_main_position_changed(3000)   # 진입점 도달
    main.pause.assert_called()
    insert.set_insert_source.assert_called_once()
    args, kwargs = insert.set_insert_source.call_args
    assert kwargs.get("seek_ms") == 0
    assert kwargs.get("play_after_load") is True
    insert.show_insert_surface.assert_called_with(True)
    assert ctrl._active_cut_id == sc.effects[0].id


def test_insert_position_at_src_out_triggers_main_resume():
    """보조가 src_out_ms 도달 → 보조 pause·hide, 메인 seek(out_ms) + play."""
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(3000, 6000, src="b.mp4", src_in=0, src_out=4000, src_dur=4000)
    ctrl.set_sidecar(sc, 10000)
    ctrl._active_cut_id = sc.effects[0].id   # 진입한 상태
    ctrl.on_insert_position_changed(4000)    # src_out 도달
    insert.pause_insert.assert_called()
    insert.show_insert_surface.assert_called_with(False)
    main.seek_ms.assert_called_with(6000)
    main.play.assert_called()
    assert ctrl._active_cut_id is None


def test_main_at_cut_in_with_no_src_skips_insert():
    """src 비어있는 cut (단순 자르기) → insert 활성화 없이 그냥 cut.out_ms 로 점프."""
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(3000, 6000, src="", src_dur=0)
    ctrl.set_sidecar(sc, 10000)
    ctrl.on_main_position_changed(3000)
    insert.set_insert_source.assert_not_called()
    main.seek_ms.assert_called_with(6000)
    assert ctrl._active_cut_id is None


def test_splice_with_no_insert_does_not_pause_main():
    """splice (in == out) + insert 없음 → 완전 no-op. main pause 안 됨, 재생 계속.

    이전 버그: splice 위치에서 main 이 멈춤 (사용자 보고). 원인은 _enter_insert 가
    main.pause() 를 부른 뒤 seek+play 를 했지만 _active_cut_id 가 안 set 되어 다음
    position 업데이트마다 다시 들어가 무한 루프 → 시각적으로 정지 상태.
    """
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(5000, 5000, src="", src_dur=0)
    ctrl.set_sidecar(sc, 10000)
    ctrl.on_main_position_changed(5000)
    main.pause.assert_not_called()
    main.seek_ms.assert_not_called()
    insert.set_insert_source.assert_not_called()


def test_no_insert_range_cut_does_not_reenter_on_subsequent_positions():
    """단순 자르기 range (in < out, src 없음) → 첫 진입에서만 seek+play, 이후 재진입 없음.

    이전 버그: _enter_insert 의 no-insert 분기가 _active_cut_id 를 안 set 하고
    main.seek_ms+play 만 → 다음 position 업데이트(= out_ms 도달) 때 같은 cut 이
    _next_cut_at_or_after 에 다시 잡혀 무한 재진입.
    """
    ctrl, main, insert = _make_controller(10000)
    sc = _sidecar_with_cut(3000, 6000, src="", src_dur=0)
    ctrl.set_sidecar(sc, 10000)
    ctrl.on_main_position_changed(3000)
    # 첫 진입: seek_ms(6000) + play 호출됨.
    main.seek_ms.assert_called_with(6000)
    main.play.assert_called_once()
    main.seek_ms.reset_mock()
    main.play.reset_mock()
    main.pause.reset_mock()
    # 이제 main 이 6000 에 도달 (seek 직후 첫 position event).
    ctrl.on_main_position_changed(6000)
    # 같은 cut 으로 재진입 안 됨.
    main.pause.assert_not_called()
    main.seek_ms.assert_not_called()
