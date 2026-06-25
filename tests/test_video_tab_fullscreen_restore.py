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
    """풀스크린 진입/종료 후 위젯이 원래 splitter 구조로 복귀하고, 편집 모드 풀스크린은
    splitter 레이아웃을 쓴다.

    주의: 두 시나리오를 *한 테스트(단일 MainWindow)* 로 묶는다. 풀스크린에 진입하는
    테스트 함수가 한 프로세스에 2개 이상이면 Qt/QMediaPlayer 풀스크린 teardown 이
    세그폴트하는 기존 환경 취약점(베이스 코드에서도 재현) 때문 — 분리하면 스위트가
    죽는다. 단일 MainWindow 로 여러 번 enter/exit 하는 건 안전.
    """
    w._on_finished(str(gif_file))
    vt = w.tab_area.current_video_tab()
    assert vt is not None

    # === 시나리오 A: 재생(편집 OFF) 풀스크린 진입 → 종료 → 원위치 복원 ===
    # 회귀: 2026-05-12 QSplitter 도입 후 복귀 시 playbar 가 사라지던 버그.
    vt._on_fullscreen_toggled()
    holder = vt._fullscreen_holder
    assert holder is not None
    assert vt._fs_edit_layout is False           # 편집 OFF = floating overlay
    assert vt.player.parent() is holder          # floating: holder 직속
    holder.close()
    qtbot.wait(50)   # closeEvent 처리.
    assert vt.player.parent() is vt._preview_container, (
        f"player parent={vt.player.parent()}, expected preview_container"
    )
    assert vt.controls.parent() is vt._preview_container, (
        f"controls parent={vt.controls.parent()}, expected preview_container"
    )
    assert vt.timeline.parent() is vt._main_splitter, (
        f"timeline parent={vt.timeline.parent()}, expected splitter"
    )
    assert vt.player.isVisible()
    assert vt.controls.isVisible()

    # === 시나리오 B: 편집(편집 ON) 풀스크린 = splitter 레이아웃 + 토글 ===
    # 회귀 (2026-06-22): 편집 모드 풀스크린에서 편집 끄면 playbar 가 안 내려오고, 다시
    # 켜면 편집 UI 가 잘리고, 크기 조절이 안 되던 문제. 같은 MainWindow 재진입.
    vt.set_edit_mode(True)
    assert vt.is_edit_mode_on()
    vt._on_fullscreen_toggled()
    holder = vt._fullscreen_holder
    assert holder is not None
    # 편집 모드 풀스크린 → _main_splitter 가 holder 로 (리사이즈 가능 구조, UI 안 잘림).
    assert vt._fs_edit_layout is True
    assert vt._main_splitter.parent() is holder
    assert vt.timeline.parent() is vt._main_splitter
    assert vt.player.parent() is vt._preview_container

    # 편집 OFF → floating overlay (playbar 하단 복귀, player 가 holder 직속).
    vt.set_edit_mode(False)
    assert vt._fs_edit_layout is False
    assert vt.player.parent() is holder
    assert vt.controls.parent() is holder
    assert vt.timeline.parent() is holder

    # 편집 ON → 다시 splitter.
    vt.set_edit_mode(True)
    assert vt._fs_edit_layout is True
    assert vt._main_splitter.parent() is holder
    assert vt.timeline.parent() is vt._main_splitter

    # 종료 → 원위치 복원.
    holder.close()
    qtbot.wait(50)
    assert vt._fullscreen_holder is None
    assert vt.player.parent() is vt._preview_container
    assert vt.controls.parent() is vt._preview_container
    assert vt.timeline.parent() is vt._main_splitter
