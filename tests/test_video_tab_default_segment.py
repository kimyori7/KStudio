"""영상 첫 로드 시 사이드카에 segment 가 자동으로 1개 들어가야 한다."""
import io
import pytest
from PIL import Image

from screen_recorder.core.settings import PlayerSettings
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def gif_file(tmp_path):
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


def test_first_load_creates_default_segment(qtbot, gif_file, tmp_path):
    """video_tab 생성 후 sidecar.video_track 에 segment 1개가 자동 생성된다."""
    tab = VideoTab(
        path=gif_file, source_label="region", duration_ms=200,
        player_settings=PlayerSettings(),
        sidecar_dir=tmp_path / "sc",
    )
    qtbot.addWidget(tab)
    sc = tab.sidecar()
    assert len(sc.video_track) == 1
    seg = sc.video_track[0]
    assert seg.src == str(gif_file)
    # duration 200 으로 들어감 — caller 가 명시적으로 넘김.
    assert seg.src_duration_ms == 200
    assert seg.media_kind == "video"
