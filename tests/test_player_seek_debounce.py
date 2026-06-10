"""seek_ms 의 force-frame(play/pause WMF 사이클) 디바운스 검증.

회귀(사용자 보고 2026-06-09 "출력하기하고 플레이 시키니까 멈추네", py-spy: 메인
스레드가 player_widget play() 에서 hang): seek_ms 가 매 호출마다 play()/pause() 를
부르는데, 재생바를 빠르게 드래그하면(mouseMove 연사) 이 WMF 사이클이 연사되어 메인
스레드가 deadlock. fix: setPosition 은 즉시, 무거운 force-frame 은 ~60ms 디바운스해
스크럽이 멈춘 뒤 한 번만 실행. (WMF hang 자체는 헤드리스 재현 불가 — 메커니즘만 검증.)
"""
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtMultimedia import QMediaPlayer

from screen_recorder.ui.video.player_widget import PlayerWidget


def _loaded_paused_player(qtbot):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w._path = Path("fake.mp4")     # is_loaded() True
    w._is_gif = False
    m = MagicMock()
    m.duration.return_value = 10000
    m.playbackState.return_value = QMediaPlayer.PausedState
    m.mediaStatus.return_value = QMediaPlayer.LoadedMedia
    a = MagicMock()
    a.isMuted.return_value = False
    w._media = m
    w._audio = a
    return w, m, a


def test_rapid_seek_defers_play_pause(qtbot):
    """빠른 연속 seek 30회 → setPosition 30회(즉시)이지만 play/pause 는 아직 0회,
    스크럽이 멈춘 뒤(타이머 발화) 딱 1회만."""
    w, m, _a = _loaded_paused_player(qtbot)
    for i in range(30):
        w.seek_ms(i * 100)
    assert m.setPosition.call_count == 30
    assert m.play.call_count == 0          # 연사 안 함 = deadlock 회피
    assert w._seek_frame_timer.isActive()
    qtbot.wait(150)                         # 디바운스 타이머 발화 대기
    assert m.play.call_count == 1
    assert m.pause.call_count == 1


def test_seek_while_playing_skips_force_frame(qtbot):
    """재생 중 seek 은 force-frame 불필요 — 타이머도 안 켜고 play 도 안 부른다."""
    w, m, _a = _loaded_paused_player(qtbot)
    m.playbackState.return_value = QMediaPlayer.PlayingState
    w.seek_ms(500)
    assert m.setPosition.call_count == 1
    assert not w._seek_frame_timer.isActive()
    qtbot.wait(120)
    assert m.play.call_count == 0


def test_stop_cancels_pending_force_frame(qtbot):
    """stop() 후엔 보류된 force-frame 이 발화하지 않는다(torn-down 미디어에 play 금지)."""
    w, m, _a = _loaded_paused_player(qtbot)
    w.seek_ms(500)
    assert w._seek_frame_timer.isActive()
    w.stop()
    assert not w._seek_frame_timer.isActive()
    qtbot.wait(120)
    assert m.play.call_count == 0
