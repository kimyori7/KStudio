"""SceneAnalyzer — PySceneDetect → 씬 시작 지점 ms 매핑."""
from pathlib import Path
from unittest.mock import patch, MagicMock
from screen_recorder.autoedit.analyzers.scene import SceneAnalyzer


def test_scene_changes_mapped_to_ms(tmp_path: Path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    # PySceneDetect 가 (start, end) 튜플 리스트 반환. start/end 는 FrameTimecode 객체.
    fake_scenes = [
        (MagicMock(get_seconds=lambda: 0.0), MagicMock(get_seconds=lambda: 5.0)),
        (MagicMock(get_seconds=lambda: 5.0), MagicMock(get_seconds=lambda: 12.5)),
    ]
    with patch("screen_recorder.autoedit.analyzers.scene._detect_scenes",
               return_value=fake_scenes):
        a = SceneAnalyzer()
        payload = a.analyze(media)
    # 첫 씬 0초는 영상 시작이라 제외 — 두 번째부터.
    assert payload["scene_changes"][0] == (5000, 30.0)
