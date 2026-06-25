"""라이브러리 이름 바꾸기 — 디스크 rename + 열린 탭 핸들 해제/재로드.

회귀: 영상이 편집 탭에서 열려 있으면 Windows WMF/QMovie 가 파일 핸들을 잡고 있어
`old_path.rename(target)` 이 WinError 32 ("다른 프로세스가 파일을 사용 중") 로 실패.
삭제 경로(_close_tab_and_release_handles)와 동일하게 rename 전에 player 핸들을 먼저
해제하면 성공해야 하고, 열린 탭은 새 경로로 투명하게 재로드돼야 한다.
"""
from __future__ import annotations
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.ui.video_tab import VideoTab
from screen_recorder.core.settings import AppSettings


def _img() -> QImage:
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


@pytest.fixture
def gif_file(tmp_path):
    from PIL import Image
    p = tmp_path / "rec_20260622_160747.gif"
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


def test_rename_image_entry_renames_on_disk(w, tmp_path):
    """이미지 항목 rename — 탭 핸들 해제 경로를 타지 않는 기본 동작 회귀."""
    w._on_screenshot_captured(_img(), "region")
    w._save_current_screenshot()
    saved = list((tmp_path / "shots").glob("*.png"))[0]
    entry_id = w.library_model.entries()[0].id

    w.library_model.rename(entry_id, "renamed_shot")

    new_path = saved.with_name("renamed_shot.png")
    assert new_path.exists()
    assert not saved.exists()
    assert w.library_model.get(entry_id).path == new_path


def test_rename_video_open_in_tab_succeeds_and_reloads(w, gif_file, qtbot):
    """영상이 탭에서 열린 채 rename — 핸들 해제 후 성공 + 탭이 새 경로로 재로드.

    GIF (QMovie) 는 WMF 없이도 Windows 에서 파일 핸들을 잡으므로 헤드리스에서 실제
    핸들 해제 경로를 검증할 수 있다.
    """
    w._on_finished(str(gif_file))
    entry = w.library_model.entries()[0]
    entry_id = entry.id
    vt = w.tab_area.tab_widget_for_entry(entry_id)
    assert isinstance(vt, VideoTab)
    qtbot.wait(50)  # showEvent → _ensure_player_loaded.

    w.library_model.rename(entry_id, "260623 Sample")

    new_path = gif_file.with_name("260623 Sample.gif")
    assert new_path.exists(), "디스크 파일이 새 이름으로 바뀌어야 함 (WinError 32 없이)"
    assert not gif_file.exists()
    assert w.library_model.get(entry_id).path == new_path
    # 탭의 in-memory 소스 경로도 갱신 — 이후 export/preview 가 새 경로 사용.
    assert Path(vt.source_path()) == new_path
    # edit controller / sidecar 도 마이그레이션.
    assert Path(vt.edit_controller()._video_path) == new_path


def test_rename_collision_does_not_touch_disk(w, gif_file, qtbot, monkeypatch):
    """같은 이름 파일이 이미 있으면 rename 거부 — 원본 파일 그대로.

    QMessageBox.warning 은 모달이라 헤드리스에서 블로킹 → 스텁으로 대체.
    """
    monkeypatch.setattr(
        "screen_recorder.ui.main_window.QMessageBox.warning",
        lambda *a, **k: None,
    )
    # 충돌 대상 파일 미리 생성.
    clash = gif_file.with_name("260623 Sample.gif")
    clash.write_bytes(b"existing")
    w._on_finished(str(gif_file))
    entry_id = w.library_model.entries()[0].id
    qtbot.wait(50)

    w.library_model.rename(entry_id, "260623 Sample")

    # 원본 그대로, 충돌 파일도 안 바뀜.
    assert gif_file.exists()
    assert clash.read_bytes() == b"existing"
