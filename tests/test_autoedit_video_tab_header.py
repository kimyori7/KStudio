"""VideoTab 의 새 헤더 row 에 [🪄 자동 편집] 버튼 표시."""
from pathlib import Path
from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.ui.video_tab import VideoTab


def test_video_tab_has_autoedit_button(qtbot, tmp_path: Path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000)
    tab = VideoTab(
        path=p, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    assert tab.autoedit_button() is not None
    assert "자동 편집" in tab.autoedit_button().text()
