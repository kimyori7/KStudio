import io
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from screen_recorder.core.settings import PlayerSettings
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def gif_file(tmp_path):
    """Pillow 으로 생성한 유효한 2프레임 GIF (8×8, 100ms/frame)."""
    p = tmp_path / "test.gif"
    frames = [
        Image.new("RGB", (8, 8), color=(255, 0, 0)).convert("P"),
        Image.new("RGB", (8, 8), color=(255, 255, 255)).convert("P"),
    ]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True,
        append_images=[frames[1]], loop=0, duration=100,
    )
    p.write_bytes(buf.getvalue())
    return p


def test_video_tab_loads_file(qtbot, gif_file):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    assert tab.player.is_loaded()


def test_space_key_toggles_play(qtbot, gif_file):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    with qtbot.waitSignal(tab.player.playing_changed, timeout=500):
        qtbot.keyPress(tab, Qt.Key_Space)


def test_arrow_right_uses_skip_seconds(qtbot, gif_file, monkeypatch):
    settings = PlayerSettings(skip_seconds=2)
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=settings)
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Right)
    assert captured == [2]


def test_shift_arrow_uses_medium_skip(qtbot, gif_file, monkeypatch):
    settings = PlayerSettings(skip_seconds=1, skip_medium_seconds=5)
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=settings)
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Right, modifier=Qt.ShiftModifier)
    assert captured == [5]


def test_ctrl_arrow_uses_large_skip(qtbot, gif_file, monkeypatch):
    settings = PlayerSettings(skip_seconds=1, skip_large_seconds=10)
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=settings)
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Right, modifier=Qt.ControlModifier)
    assert captured == [10]


def test_comma_period_keys_step_frame(qtbot, gif_file, monkeypatch):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    captured: list[int] = []
    monkeypatch.setattr(tab.player, "step_frame", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Period)
    qtbot.keyPress(tab, Qt.Key_Comma)
    assert captured == [+1, -1]


def test_snapshot_signal(qtbot, gif_file):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    with qtbot.waitSignal(tab.snapshot_requested, timeout=200) as blocker:
        tab.controls.snapshot_btn.click()
    img, label_at = blocker.args
    assert img is not None
    assert "@" in label_at


def test_seek_bar_visible_in_playback_mode(qtbot, gif_file):
    """편집 모드 OFF(일반 재생)에서도 시크 바(슬라이더)가 보여야 한다.

    회귀(2026-06-04): 시크 바가 VideoTimeline 으로 이동한 뒤, 편집 OFF 시 타임라인이
    통째로 숨겨져 재생 모드에서 시크 바가 사라졌다 ("영상 모드에서 재생 바가 어디갔지?").
    isHidden() 으로 검증 — 슬라이더는 조상(_top_scroll) 을 통해 숨겨지므로 컨테이너의
    isHidden 을 본다 (memory: 헤드리스에선 isVisible 대신 isHidden).
    """
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=8000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    assert not tab.is_edit_mode_on()
    # 타임라인 + 시크 바 컨테이너는 보여야 함.
    assert not tab.timeline.isHidden()
    assert not tab.timeline._top_scroll.isHidden()
    # 단, 편집용 영상 트랙 / 효과 줄은 숨겨져 있어야 함 (일반 플레이어 모습).
    assert tab.timeline.video_track_lane.isHidden()
    assert tab.timeline.effect_lanes.isHidden()
    assert tab.timeline._scroll.isHidden()


def test_edit_mode_reveals_full_timeline(qtbot, gif_file):
    """편집 모드 ON 시 시크 바에 더해 영상 트랙 + 효과 줄이 펼쳐진다."""
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=8000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    tab.set_edit_mode(True)
    assert not tab.timeline._top_scroll.isHidden()      # 시크 바 여전히 보임
    assert not tab.timeline.video_track_lane.isHidden()
    assert not tab.timeline.effect_lanes.isHidden()
    assert not tab.timeline._scroll.isHidden()
    # 편집 OFF 로 돌리면 다시 시크 바만.
    tab.set_edit_mode(False)
    assert not tab.timeline._top_scroll.isHidden()
    assert tab.timeline.effect_lanes.isHidden()


def test_fullscreen_roundtrip_keeps_seek_bar(qtbot, gif_file):
    """풀스크린 진입→복귀 후에도 시크 바가 살아 있어야 한다.

    _restore 가 _apply_timeline_layout 으로 타임라인을 splitter 에 되돌린다 —
    과거 f6141ee("편집 갔다 오니 playbar 사라짐") 와 같은 부류라 명시 검증.
    """
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=8000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    tab._on_fullscreen_toggled()
    assert tab._fullscreen_holder is not None
    tab._fullscreen_holder.close()                          # _restore 발화
    assert tab._fullscreen_holder is None
    assert tab._main_splitter.indexOf(tab.timeline) >= 0    # splitter 로 복귀
    assert not tab.timeline._top_scroll.isHidden()          # 시크 바 생존
    assert tab.timeline._scroll.isHidden()                  # 여전히 재생 모드
