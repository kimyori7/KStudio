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


def test_fullscreen_hide_delay_is_three_seconds():
    """전체화면 자동 숨김 지연 = 3초 (사용자 요청 2026-06-04)."""
    from screen_recorder.ui import video_tab as mod
    assert mod._FS_HIDE_DELAY_MS == 3000


def test_fullscreen_hide_and_reveal_bars(qtbot, gif_file, monkeypatch):
    """재생 중 idle → 모든 바(컨트롤+타임라인) 숨김, 마우스 움직이면 다시 보임.

    하단 밴드 밖(화면 중앙)에서 움직여도 복원돼야 함 (YouTube/VLC 표준).
    헤드리스에서 실제 showFullScreen 은 Qt 정리 단계 세그폴트가 잦아, _fs 메서드가
    필요로 하는 최소 상태(더미 holder)만 구성해 로직만 검증한다 — controls/timeline 은
    reparent 하지 않는다 (해당 메서드들은 부모와 무관하게 hide()/show() 만 호출).
    """
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QWidget
    from screen_recorder.ui import video_tab as mod

    tab = VideoTab(path=gif_file, source_label="region", duration_ms=8000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    monkeypatch.setattr(tab.player, "is_playing", lambda: True)
    holder = QWidget()
    holder.resize(800, 600)
    qtbot.addWidget(holder)
    tab._fullscreen_holder = holder
    tab._fs_hide_timer = QTimer(holder)
    tab._fs_hide_timer.setSingleShot(True)
    try:
        # 재생 중 숨김 타이머 발화 → 두 바 모두 숨김.
        tab._fs_maybe_hide_controls()
        assert tab.controls.isHidden()
        assert tab.timeline.isHidden()

        # 화면 중앙(하단 밴드 밖)에서 마우스 움직임 → 두 바 다시 보임.
        class _FakeCursor:
            @staticmethod
            def pos():
                return holder.mapToGlobal(QPoint(holder.width() // 2, holder.height() // 2))
        monkeypatch.setattr(mod, "QCursor", _FakeCursor)
        tab._fs_handle_global_mouse_move()
        assert not tab.controls.isHidden()
        assert not tab.timeline.isHidden()

        # 일시정지 중엔 숨기지 않음.
        monkeypatch.setattr(tab.player, "is_playing", lambda: False)
        tab._fs_maybe_hide_controls()
        assert not tab.controls.isHidden()
    finally:
        tab._fullscreen_holder = None
        tab._fs_hide_timer = None


def test_arrow_keys_skip_one_second_by_default(qtbot, gif_file, monkeypatch):
    """← / → 단독 = 1초 건너뛰기 (기본값 확인 — 사용자 요청 검증)."""
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Right)
    qtbot.keyPress(tab, Qt.Key_Left)
    assert captured == [1, -1]


def test_arrow_seeks_when_child_widget_focused(qtbot, gif_file, monkeypatch):
    """자식 위젯(컨트롤 버튼 등)이 포커스여도 ← / → 가 seek 해야 한다.

    회귀(2026-06-04): 방향키 처리가 VideoTab.keyPressEvent 에만 있어 VideoTab 이 직접
    포커스일 때만 동작 → 편집 모드/풀스크린(포커스가 자식·holder)에서 안 먹힘.
    """
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.controls.play_btn.setFocus()      # 포커스를 자식 버튼으로
    qtbot.keyClick(tab.controls.play_btn, Qt.Key_Right)
    qtbot.keyClick(tab.controls.play_btn, Qt.Key_Left)
    assert captured == [1, -1]


def test_shift_arrow_medium_skip_with_child_focus(qtbot, gif_file, monkeypatch):
    """Shift + ← / → = 중간 건너뛰기(5초) — 자식 포커스 상태에서도."""
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=20000,
                   player_settings=PlayerSettings(skip_seconds=1, skip_medium_seconds=5))
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.controls.play_btn.setFocus()
    qtbot.keyClick(tab.controls.play_btn, Qt.Key_Right, modifier=Qt.ShiftModifier)
    assert captured == [5]


def test_arrow_in_external_text_input_not_hijacked(qtbot, gif_file, monkeypatch):
    """영상 탭 밖 텍스트 입력에 포커스면 방향키를 가로채지 않는다 (커서 이동 보호)."""
    from PySide6.QtWidgets import QLineEdit
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    edit = QLineEdit()
    qtbot.addWidget(edit)
    edit.setText("ab")
    edit.show()
    qtbot.waitExposed(edit)
    edit.setFocus()
    edit.end(False)                        # 커서 끝으로
    qtbot.keyClick(edit, Qt.Key_Left)      # 커서만 왼쪽 — seek 발생 금지
    assert captured == []


def test_apply_timeline_layout_restores_seek_bar(qtbot, gif_file):
    """_apply_timeline_layout(False) — 숨겨졌던 타임라인을 다시 보이게 + 시크 바 유지.

    풀스크린 복귀(_restore)가 이 funnel 을 호출해 시크 바를 되살린다 — 과거
    f6141ee("편집 갔다 오니 playbar 사라짐") 부류. 실제 showFullScreen 은 헤드리스
    세그폴트가 잦아 복귀가 부르는 funnel 을 직접 검증한다.
    """
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=8000,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    # 편집 모드로 펼침.
    tab._apply_timeline_layout(True)
    assert not tab.timeline.isHidden()
    assert not tab.timeline._top_scroll.isHidden()
    # 옛 _restore 가 하던 짓(타임라인 통째 hide)을 흉내 낸 뒤, funnel 이 되살리는지.
    tab.timeline.setVisible(False)
    tab._apply_timeline_layout(False)
    assert not tab.timeline.isHidden()                  # 다시 보임
    assert not tab.timeline._top_scroll.isHidden()      # 시크 바 생존
