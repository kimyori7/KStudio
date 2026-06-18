"""AudioTab — 오디오 자르기 탭 brain. 트림/중간컷이 풀 segment 위 경계/중간 CutEffect 로
표현되고, 실제 내보내기 keep 계산(compute_audio_keep_intervals)이 의도대로 나오는지.

플레이어 로드는 showEvent 까지 지연 → 더미 파일로도 안전(소리 디코드 안 함).
"""
from screen_recorder.core.settings import PlayerSettings
from screen_recorder.encode.audio_export import compute_audio_keep_intervals


def _make_tab(qtbot, tmp_path, name="v.mp3"):
    from screen_recorder.ui.audio_tab import AudioTab
    mp3 = tmp_path / name
    mp3.write_bytes(b"\x00")
    tab = AudioTab(path=mp3, player_settings=PlayerSettings(), sidecar_dir=tmp_path)
    qtbot.addWidget(tab)
    return tab


def test_audio_tab_builds_and_loads_sidecar(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path, "voice.mp3")
    sc = tab._edit_controller.sidecar()
    assert len(sc.video_track) == 1
    assert sc.video_track[0].src.endswith("voice.mp3")
    assert tab.editor._filename == "voice.mp3"


def test_trim_becomes_boundary_cuts_and_keep(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab._on_duration(10000)
    tab._on_trim_changed(1000, 9000)
    # segment 는 풀 유지, 트림은 경계 컷으로.
    seg = tab._edit_controller.sidecar().video_track[0]
    assert seg.src_in_ms == 0 and seg.src_out_ms == 0
    _, keep = compute_audio_keep_intervals(tab._edit_controller.sidecar())
    assert keep == [(1000, 9000)]


def test_front_back_trim_plus_middle_cut_keep(qtbot, tmp_path):
    """사용자 시나리오: 앞 트림 + 뒤 트림 + 중간 컷 모두 내보내기에 반영."""
    tab = _make_tab(qtbot, tmp_path)
    tab._on_duration(10000)
    tab._on_trim_changed(1000, 9000)
    tab._on_cuts_changed([(4000, 5000)])
    _, keep = compute_audio_keep_intervals(tab._edit_controller.sidecar())
    assert keep == [(1000, 4000), (5000, 9000)]


def test_middle_cut_synced_back_to_editor_without_boundary(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab._on_duration(10000)
    tab._on_trim_changed(1000, 9000)
    tab._on_cuts_changed([(4000, 5000)])
    # editor 는 중간컷만 표시(경계 컷=트림은 핸들로). 트림은 (1000,9000).
    assert tab.editor.cuts() == [(4000, 5000)]
    assert tab.editor.trim() == (1000, 9000)


def test_ctrl_z_undo_reverts_cut(qtbot, tmp_path):
    """컷 후 undo() 가 컷을 되돌린다(EditController History 배선)."""
    tab = _make_tab(qtbot, tmp_path)
    tab._on_duration(10000)
    tab._on_cuts_changed([(4000, 5000)])
    assert any(e.type == "cut" for e in tab._edit_controller.sidecar().effects)
    tab._undo()
    assert not any(e.type == "cut" for e in tab._edit_controller.sidecar().effects)


def test_keep_intervals_recomputed_for_playback_skip(qtbot, tmp_path):
    """컷을 만들면 재생 건너뛰기용 keep 구간이 갱신된다(이어붙은 재생)."""
    tab = _make_tab(qtbot, tmp_path)
    tab._on_duration(10000)
    tab._on_cuts_changed([(4000, 5000)])
    assert tab._keep == [(0, 4000), (5000, 10000)]


def test_cut_only_no_trim(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab._on_duration(8000)
    tab._on_cuts_changed([(3000, 4000)])
    cuts = [(e.in_ms, e.out_ms) for e in tab._edit_controller.sidecar().effects
            if e.type == "cut"]
    assert cuts == [(3000, 4000)]
    _, keep = compute_audio_keep_intervals(tab._edit_controller.sidecar())
    assert keep == [(0, 3000), (4000, 8000)]
