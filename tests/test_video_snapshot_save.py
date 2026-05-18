"""영상에서 한 프레임을 캡처 → 저장 시 파일명과 디스크 저장이 정상 동작하는지."""
from pathlib import Path
import pytest
from PySide6.QtGui import QImage

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


def _img() -> QImage:
    img = QImage(20, 20, QImage.Format_ARGB32)
    img.fill(0xFFAA1122)
    return img


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path / "shots")
    s.general.output_dir = str(tmp_path / "videos")
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_video_snapshot_tab_label_is_clean_filename_immediately(w):
    """사용자 요청 회귀: snapshot 직후 (저장 전) 탭/라이브러리 라벨이 'region @ 01:23.4'
    같이 보이면 안 되고, 실제 저장될 파일명 ('screenshot_<date>_<time>.png') 로 즉시
    표시되어야 한다.
    """
    w._on_video_snapshot(_img(), "region @ 01:23.4")
    tab = w._current_screenshot_tab()
    assert tab is not None
    base = w.tab_area._tab_base_labels.get(tab, "")
    assert ":" not in base, f"탭 라벨에 ':' 노출: {base}"
    assert "@" not in base, f"탭 라벨에 '@' 노출: {base}"
    assert base.startswith("screenshot_"), f"탭 라벨이 파일명 패턴이 아님: {base}"
    # 라이브러리 entry 의 display_name 도 동일하게 즉시 깔끔한 파일명.
    entry = w.library_model.entries()[0]
    assert entry.display_name.startswith("screenshot_")


def test_video_snapshot_save_uses_safe_default_filename(w, tmp_path):
    """비디오 프레임 캡처 → Ctrl+S 저장 시 파일이 디스크에 생성되어야 한다.

    회귀: snapshot label_at='region @ 01:23.4' 가 tab.source_label() 로 들어가는데,
    default filename_pattern='screenshot_{date}_{time}' 는 {target} 미사용이라
    안전해야 함. 그러나 실제로 저장이 되는지 + 파일명에 ':' 같은 잘못된 문자가
    안 들어가는지 확인.
    """
    # 비디오 탭에서 스냅샷 emit 흐름 시뮬레이션 — label_at 에 ':' / '@' 포함.
    w._on_video_snapshot(_img(), "region @ 01:23.4")
    # 새로 생긴 screenshot 탭 활성화 확인
    tab = w._current_screenshot_tab()
    assert tab is not None
    # 저장 실행
    w._save_current_screenshot()
    # 저장 폴더에 실제 파일이 생겼는지
    save_dir = Path(tmp_path / "shots")
    files = list(save_dir.glob("*.png"))
    assert files, f"저장된 파일이 없음. save_dir={save_dir}, contents={list(save_dir.iterdir()) if save_dir.exists() else 'NOT EXISTS'}"
    # 파일명에 잘못된 Windows 문자가 없어야 함
    for f in files:
        assert ":" not in f.name, f"파일명에 ':' 가 포함됨: {f.name}"
        assert "@" not in f.name, f"파일명에 '@' 가 포함됨: {f.name}"


@pytest.fixture
def gif_file(tmp_path):
    """Pillow-generated valid 2-frame GIF."""
    from PIL import Image
    p = tmp_path / "rec_test.gif"
    f1 = Image.new("P", (8, 8), 0)
    f2 = Image.new("P", (8, 8), 1)
    palette = [255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6)
    f1.putpalette(palette)
    f2.putpalette(palette)
    f1.save(p, format="GIF", save_all=True, append_images=[f2], duration=100, loop=0)
    return p


def test_gif_snapshot_save_full_flow(w, gif_file, tmp_path):
    """GIF 녹화 → 비디오 탭 자동 오픈 → snapshot 버튼 → 저장 — end-to-end.

    GIF 첫 프레임이 비동기로 들어오므로 _on_snapshot 직접 호출은 빈 frame 가능 —
    여기선 _on_video_snapshot 을 직접 호출해 라벨/저장 경로만 검증.
    """
    w._on_finished(str(gif_file))
    vt = w.tab_area.current_video_tab()
    assert vt is not None
    # snapshot 흐름을 직접 호출 — current_frame() 의 GIF QImage 디코드 비동기성 회피.
    w._on_video_snapshot(_img(), "region @ 00:00.0")
    tab = w._current_screenshot_tab()
    assert tab is not None
    w._save_current_screenshot()
    save_dir = Path(tmp_path / "shots")
    files = list(save_dir.glob("*.png"))
    assert files, f"GIF snapshot 저장 실패. save_dir={save_dir}"


def test_video_snapshot_tab_label_stays_clean_after_save(w):
    """snapshot 직후의 미리 만든 display_name 과 save 후의 실제 파일명이 같은
    패턴이어야 한다 (둘 다 'screenshot_<date>_<time>.png'). 패턴은 같지만 시각 차이로
    파일명이 약간 다를 수 있어 prefix 만 검사.
    """
    w._on_video_snapshot(_img(), "region @ 01:23.4")
    tab = w._current_screenshot_tab()
    assert tab is not None
    base_before = w.tab_area._tab_base_labels.get(tab, "")
    assert base_before.startswith("screenshot_")
    w._save_current_screenshot()
    base_after = w.tab_area._tab_base_labels.get(tab, "")
    assert base_after.startswith("screenshot_"), f"저장 후 탭 라벨 회귀: {base_after}"
