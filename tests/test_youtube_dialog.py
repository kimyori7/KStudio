from pathlib import Path

from screen_recorder.ui.youtube.download_dialog import YouTubeDownloadDialog


def test_video_mode_quality_items(qtbot):
    dlg = YouTubeDownloadDialog(mode="video", start_dir=Path("C:/d"), start_quality="best")
    qtbot.addWidget(dlg)
    items = [dlg.quality_combo.itemData(i) for i in range(dlg.quality_combo.count())]
    assert items == ["best", "1080", "720", "480"]


def test_mp3_mode_quality_items(qtbot):
    dlg = YouTubeDownloadDialog(mode="mp3", start_dir=Path("C:/d"), start_quality="192")
    qtbot.addWidget(dlg)
    items = [dlg.quality_combo.itemData(i) for i in range(dlg.quality_combo.count())]
    assert items == ["320", "256", "192"]


def test_start_quality_preselected(qtbot):
    dlg = YouTubeDownloadDialog(mode="video", start_dir=Path("C:/d"), start_quality="720")
    qtbot.addWidget(dlg)
    assert dlg.quality_combo.currentData() == "720"


def test_build_request_valid(qtbot):
    dlg = YouTubeDownloadDialog(mode="video", start_dir=Path("C:/d"), start_quality="720")
    qtbot.addWidget(dlg)
    dlg.url_edit.setText("https://youtu.be/x")
    req = dlg.build_request()
    assert req is not None
    assert req.url == "https://youtu.be/x"
    assert req.mode == "video"
    assert req.quality == "720"
    assert req.out_dir == Path("C:/d")


def test_build_request_empty_url_returns_none(qtbot):
    dlg = YouTubeDownloadDialog(mode="mp3", start_dir=Path("C:/d"), start_quality="192")
    qtbot.addWidget(dlg)
    dlg.url_edit.setText("   ")
    assert dlg.build_request() is None


def test_selected_dir_and_quality(qtbot):
    dlg = YouTubeDownloadDialog(mode="mp3", start_dir=Path("C:/music"), start_quality="256")
    qtbot.addWidget(dlg)
    assert dlg.selected_dir() == "C:/music" or dlg.selected_dir() == str(Path("C:/music"))
    assert dlg.selected_quality() == "256"
