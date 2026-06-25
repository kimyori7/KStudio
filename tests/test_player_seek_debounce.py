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


def test_end_of_media_emits_media_ended(qtbot):
    """EndOfMedia(소스 파일 끝) 도달 시 media_ended 시그널 emit.

    SegmentPlaybackController 가 이 신호로 다음 클립으로 넘어간다(클립이 자기 소스 끝에서
    끝나 position_changed 로는 advance 가 누락되던 회귀의 보완 경로)."""
    w, m, a = _loaded_paused_player(qtbot)
    fired = []
    w.media_ended.connect(lambda: fired.append(True))
    w._on_main_media_status(QMediaPlayer.EndOfMedia)
    assert fired == [True]


def test_end_of_media_suppressed_during_force_frame(qtbot):
    """force-frame(play/pause 사이클) 중 EndOfMedia 는 media_ended 를 쏘지 않음 —
    끝 근처에서 일시정지 프레임 강제 중 잘못된 advance 방지."""
    w, m, a = _loaded_paused_player(qtbot)
    fired = []
    w.media_ended.connect(lambda: fired.append(True))
    w._suppress_state_signal = True
    w._on_main_media_status(QMediaPlayer.EndOfMedia)
    assert fired == []


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


def test_pending_seek_on_load_forces_frame(qtbot):
    """회귀 (2026-06-22): 보류된 seek 가 LoadedMedia 에서 적용될 때 setPosition 만
    하고 프레임을 안 밀어 화면이 빈(또는 stale 썸네일) 채 남던 버그.

    이미지 모드 갔다가 영상 모드로 복귀하면 탭 재활성에서 lazy reload → seek_ms 가
    아직 로딩 중이라 _pending_seek_ms 에 저장 → LoadedMedia 시 _on_main_media_status
    가 setPosition 만 했었다. seek_ms 와 동일하게 force-frame 디바운스를 켜야 한다."""
    w, m, _a = _loaded_paused_player(qtbot)
    w._pending_seek_ms = 5_000
    w._on_main_media_status(QMediaPlayer.LoadedMedia)
    assert m.setPosition.call_count == 1
    assert m.setPosition.call_args[0][0] == 5_000
    assert w._seek_frame_timer.isActive()      # force-frame 예약됨
    qtbot.wait(150)                             # 디바운스 발화 대기
    assert m.play.call_count == 1
    assert m.pause.call_count == 1
