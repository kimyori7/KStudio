"""VideoTab 의 트림 단축키 — Sidecar.trim 영구 저장 흐름."""
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
def video_tab(qtbot, fixture_mp4, tmp_path):
    from screen_recorder.ui.video_tab import VideoTab
    tab = VideoTab(
        path=fixture_mp4, source_label="region",
        duration_ms=2_000, player_settings=PlayerSettings(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.timeline.set_duration_ms(2_000)
    tab.timeline.set_position_ms(800)
    # player 가 800ms 위치
    tab.player.position_ms = lambda: 800
    return tab


def _send_key(widget, key, modifiers=Qt.NoModifier):
    ev = QKeyEvent(QEvent.KeyPress, key, modifiers)
    widget.keyPressEvent(ev)


def test_bracket_left_only_works_in_edit_mode(video_tab):
    """[ 는 편집 모드 OFF 에서 동작 안 함 — 사이드카 trim 변하지 않음."""
    assert video_tab.is_edit_mode_on() is False
    _send_key(video_tab, Qt.Key_BracketLeft)
    assert video_tab.sidecar().trim.in_ms == 0


def test_bracket_left_marks_in_at_current_position_in_edit_mode(video_tab):
    video_tab.set_edit_mode(True)
    _send_key(video_tab, Qt.Key_BracketLeft)
    assert video_tab.sidecar().trim.in_ms == 800


def test_bracket_right_marks_out_at_current_position_in_edit_mode(video_tab):
    video_tab.set_edit_mode(True)
    _send_key(video_tab, Qt.Key_BracketRight)
    assert video_tab.sidecar().trim.out_ms == 800


def test_escape_clears_trim_when_in_or_out_set(video_tab):
    video_tab.set_edit_mode(True)
    video_tab._edit_controller.update_trim(in_ms=500, out_ms=1500)
    _send_key(video_tab, Qt.Key_Escape)
    assert video_tab.sidecar().trim.in_ms == 0
    assert video_tab.sidecar().trim.out_ms == 0


def test_seek_during_trim_auto_pauses(video_tab):
    """트림 활성 + 영상 재생 중 시크 → 자동 일시정지 + 그 위치로 이동."""
    pause_calls = []
    seek_calls = []
    video_tab.player.is_playing = lambda: True
    video_tab.player.pause = lambda: pause_calls.append(True)
    video_tab.player.seek_ms = lambda ms: seek_calls.append(ms)

    video_tab.set_edit_mode(True)
    video_tab._edit_controller.update_trim(in_ms=500, out_ms=1500)
    video_tab._on_user_seek_request(2_000)
    assert pause_calls == [True]
    assert seek_calls == [2_000]


def test_seek_without_trim_does_not_pause(video_tab):
    pause_calls = []
    seek_calls = []
    video_tab.player.is_playing = lambda: True
    video_tab.player.pause = lambda: pause_calls.append(True)
    video_tab.player.seek_ms = lambda ms: seek_calls.append(ms)

    video_tab.player.seek_ms = lambda ms: seek_calls.append(ms)
    video_tab._on_user_seek_request(2_000)
    assert pause_calls == []
    assert seek_calls == [2_000]


def test_ctrl_enter_does_not_emit_trim_requested(video_tab, qtbot):
    """Ctrl+Enter 단축키는 제거 — 시그널 emit 안 함 (export 는 Ctrl+Shift+E)."""
    video_tab.set_edit_mode(True)
    video_tab._edit_controller.update_trim(in_ms=500, out_ms=1_500)
    with qtbot.assertNotEmitted(video_tab.trim_requested, wait=300):
        _send_key(video_tab, Qt.Key_Return, Qt.ControlModifier)
