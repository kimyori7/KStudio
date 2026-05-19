"""VideoTab + BrollPipPlayer 통합 smoke 테스트.

BrollPipPlayer 가 생성되고 시그널 wiring 이 모두 연결되었는지 확인.
실제 broll 시간창 진입 / frame 도착은 별도 unit / 통합 테스트에서 검증.
"""
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


def test_video_tab_creates_broll_pip_player(qtbot, gif_file, tmp_path):
    """VideoTab 생성 후 _broll_pip 가 존재하고 idle 상태."""
    tab = VideoTab(
        path=gif_file, source_label="region", duration_ms=200,
        player_settings=PlayerSettings(),
        sidecar_dir=tmp_path / "sc",
    )
    qtbot.addWidget(tab)
    assert hasattr(tab, "_broll_pip")
    assert tab._broll_pip.active_effect_id() is None


def test_video_tab_broll_pip_receives_sidecar(qtbot, gif_file, tmp_path):
    """sidecar_replaced 가 BrollPipPlayer.set_sidecar 로 흐른다."""
    tab = VideoTab(
        path=gif_file, source_label="region", duration_ms=200,
        player_settings=PlayerSettings(),
        sidecar_dir=tmp_path / "sc",
    )
    qtbot.addWidget(tab)
    # 초기엔 sidecar 가 들어가 있어야 — set_sidecar 호출 흔적 (effects 비어도 sidecar 자체는 None 아님).
    assert tab._broll_pip._sidecar is not None
