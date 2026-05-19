"""풀스크린 진입 → 종료 후 player/controls/timeline 이 원래 splitter 구조로 복귀.

회귀: 2026-05-12 의 QSplitter 도입 이후 _on_fullscreen_toggled 는 outer layout
indexOf 로 위치를 캡처했는데, 실제 widget 들은 splitter 안 자식이라 indexOf=-1.
복귀 시 outer layout 끝에 모두 append 되어 splitter 가 비고 playbar (controls)
가 엉뚱한 위치에 가버림. 사용자 보고: "영상 편집 갔다가 편집 끝니까 플레이바 사라짐".
"""
from pathlib import Path
import pytest
from PySide6.QtGui import QImage

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


@pytest.fixture
def gif_file(tmp_path):
    from PIL import Image
    p = tmp_path / "rec.gif"
    f1 = Image.new("P", (8, 8), 0)
    f2 = Image.new("P", (8, 8), 1)
    pal = [255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6)
    f1.putpalette(pal); f2.putpalette(pal)
    f1.save(p, format="GIF", save_all=True, append_images=[f2], duration=100, loop=0)
    return p


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"; f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path / "shots")
    s.general.output_dir = str(tmp_path / "videos")
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_fullscreen_exit_restores_controls_inside_preview_container(w, gif_file, qtbot):
    """풀스크린 후 controls 와 player 는 preview_container 자식이어야 함."""
    w._on_finished(str(gif_file))
    vt = w.tab_area.current_video_tab()
    assert vt is not None
    # 풀스크린 진입.
    vt._on_fullscreen_toggled()
    holder = vt._fullscreen_holder
    assert holder is not None
    # 풀스크린 종료.
    holder.close()
    qtbot.wait(50)   # closeEvent 처리.
    # 복귀 후 player, controls 는 preview_container 의 자식이어야.
    assert vt.player.parent() is vt._preview_container, (
        f"player parent={vt.player.parent()}, expected preview_container"
    )
    assert vt.controls.parent() is vt._preview_container, (
        f"controls parent={vt.controls.parent()}, expected preview_container"
    )
    # timeline 은 splitter 의 자식이어야.
    assert vt.timeline.parent() is vt._main_splitter, (
        f"timeline parent={vt.timeline.parent()}, expected splitter"
    )
    # 셋 다 visible.
    assert vt.player.isVisible()
    assert vt.controls.isVisible()
