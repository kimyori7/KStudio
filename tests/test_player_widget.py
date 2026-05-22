from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMovie

from screen_recorder.ui.video.player_widget import PlayerWidget


@pytest.fixture
def gif_file(tmp_path):
    """Pillow 으로 생성한 유효한 2프레임 GIF (8×8, 100ms/frame)."""
    p = tmp_path / "test.gif"
    from PIL import Image
    import io
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


def test_create_player_for_gif(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    assert w.is_loaded()
    assert w.is_gif()


def test_create_player_for_video(qtbot, tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(p)
    assert w.is_loaded()
    assert not w.is_gif()


def test_play_pause_toggle_signal(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    with qtbot.waitSignal(w.playing_changed, timeout=500) as blocker:
        w.play()
    assert blocker.args == [True]


def test_seek_seconds_clamped_within_duration(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    w.seek_seconds(99999)
    assert w.position_ms() <= w.duration_ms()


def test_step_frame_forward_advances_position(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    # QMovie 는 이벤트 루프가 돌기 전까지 frameCount 가 완전히 확정되지 않음
    qtbot.waitUntil(lambda: w._movie.frameCount() > 1, timeout=1000)
    before = w.position_ms()
    w.step_frame(+1)
    after = w.position_ms()
    # GIF 의 2프레임 사이를 이동했으므로 position 이 증가
    assert after > before


def test_current_frame_returns_qimage(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    img = w.current_frame()
    assert isinstance(img, QImage)
    assert not img.isNull()


def test_pause_emits_playing_false(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    w.play()  # need to be playing first
    # QMovie.start() 는 비동기 — 이벤트 루프가 돌아야 Running 상태가 됨
    from PySide6.QtGui import QMovie
    qtbot.waitUntil(lambda: w._movie.state() == QMovie.Running, timeout=1000)
    received = []
    w.playing_changed.connect(received.append)
    w.pause()
    assert received == [False]


def test_stop_on_gif_emits_playing_false(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    w.play()
    received = []
    w.playing_changed.connect(received.append)
    w.stop()
    assert received == [False]


def test_release_file_handles_then_reload_works(qtbot, gif_file):
    """비활성 탭 디코더 해제 → 재활성화 시 reload 동작 검증 (Lazy + release 패턴 기반).

    VideoTab 의 hideEvent/showEvent 가 release_file_handles + load 를 반복 호출하는데,
    이 기본 building block 이 깨지면 안 됨.
    """
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    assert w.is_loaded()
    # 1. 해제 — setSource(QUrl()) + QMovie 정리.
    w.release_file_handles()
    # 2. 재로드 — 같은 경로로 다시.
    w.load(gif_file)
    assert w.is_loaded()
    # 3. 또 해제 + 재로드 (반복 안정성) — 메모리 누수 / dangling signal 회귀 가드.
    w.release_file_handles()
    w.load(gif_file)
    assert w.is_loaded()
    # 4. 마지막 해제 후 is_loaded — _path 가 클리어되진 않으므로 True 그대로지만
    #    실제 decoder 는 해제됨 (sharing violation 회피 동작 검증은 별도 OS 의존).
