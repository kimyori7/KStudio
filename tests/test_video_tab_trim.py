"""VideoTab 의 트림 단축키."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from screen_recorder.core.settings import PlayerSettings


@pytest.fixture
def ffmpeg_or_skip():
    from screen_recorder.core.ffmpeg_check import find_ffmpeg
    p = find_ffmpeg()
    if not p:
        pytest.skip("ffmpeg required")
    p = Path(p).resolve()
    if not p.exists():
        pytest.skip(f"ffmpeg not at: {p}")
    return p


@pytest.fixture
def fixture_mp4(tmp_path, ffmpeg_or_skip):
    out = tmp_path / "f.mp4"
    subprocess.run(
        [str(ffmpeg_or_skip), "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "2", str(out)],
        check=True,
    )
    return out


@pytest.fixture
def video_tab(qtbot, fixture_mp4):
    from screen_recorder.ui.video_tab import VideoTab
    tab = VideoTab(
        path=fixture_mp4, source_label="region",
        duration_ms=2_000, player_settings=PlayerSettings(),
    )
    qtbot.addWidget(tab)
    tab.controls.set_duration_ms(2_000)
    tab.controls.set_position_ms(800)
    # player 가 실제로 800ms 위치에 있게 — 직접 stub
    tab.player.position_ms = lambda: 800
    return tab


def _send_key(widget, key, modifiers=Qt.NoModifier):
    ev = QKeyEvent(QEvent.KeyPress, key, modifiers)
    widget.keyPressEvent(ev)


def test_bracket_left_marks_in_at_current_position(video_tab):
    _send_key(video_tab, Qt.Key_BracketLeft)
    assert video_tab.controls.in_ms() == 800


def test_bracket_right_marks_out_at_current_position(video_tab):
    _send_key(video_tab, Qt.Key_BracketRight)
    assert video_tab.controls.out_ms() == 800


def test_escape_clears_trim_when_in_or_out_set(video_tab):
    video_tab.controls.set_in_ms(500)
    _send_key(video_tab, Qt.Key_Escape)
    assert video_tab.controls.in_ms() is None


def test_ctrl_enter_emits_trim_requested_when_active(video_tab, qtbot):
    """Ctrl+Enter (트림 실행 — Ctrl+E 는 편집 모드 토글로 이동됨)."""
    video_tab.controls.set_in_ms(500)
    video_tab.controls.set_out_ms(1_500)
    with qtbot.waitSignal(video_tab.trim_requested, timeout=500) as blocker:
        _send_key(video_tab, Qt.Key_Return, Qt.ControlModifier)
    assert blocker.args == [video_tab._source_path, 500, 1_500]


def test_ctrl_enter_noop_when_button_disabled(video_tab, qtbot):
    """in 만 있고 out 없으면 Ctrl+Enter 는 시그널 emit 안 함."""
    video_tab.controls.set_in_ms(500)
    with qtbot.assertNotEmitted(video_tab.trim_requested, wait=300):
        _send_key(video_tab, Qt.Key_Return, Qt.ControlModifier)


def test_seek_during_trim_auto_pauses(video_tab):
    """트림 활성 + 영상 재생 중 시크 → 자동 일시정지 + 그 위치로 이동."""
    pause_calls = []
    seek_calls = []
    video_tab.player.is_playing = lambda: True
    video_tab.player.pause = lambda: pause_calls.append(True)
    video_tab.player.seek_ms = lambda ms: seek_calls.append(ms)

    video_tab.controls.set_in_ms(500)   # 트림 활성
    video_tab._on_user_seek_request(2_000)
    assert pause_calls == [True]
    assert seek_calls == [2_000]


def test_seek_without_trim_does_not_pause(video_tab):
    """트림 비활성(in/out 모두 None) 상태에서 시크는 일시정지 안 함."""
    pause_calls = []
    seek_calls = []
    video_tab.player.is_playing = lambda: True
    video_tab.player.pause = lambda: pause_calls.append(True)
    video_tab.player.seek_ms = lambda ms: seek_calls.append(ms)

    video_tab.controls.clear_trim()
    video_tab._on_user_seek_request(2_000)
    assert pause_calls == []
    assert seek_calls == [2_000]
