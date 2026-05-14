"""AutoEditCoordinator — 버튼→worker→리뷰 다이얼로그→적용 전 과정 통합."""
from pathlib import Path
from PySide6.QtCore import Qt

from screen_recorder.autoedit.coordinator import AutoEditCoordinator
from screen_recorder.autoedit.analyzers.base import Analyzer


class _FakeAnalyzer(Analyzer):
    name = "fake"
    version = "v1"
    def __init__(self, payload):
        self._p = payload
    def analyze(self, media_path, *, progress=None, is_cancelled=None):
        return self._p


def test_coordinator_run_emits_result(qtbot, tmp_path: Path):
    fake_media = tmp_path / "v.mp4"
    fake_media.write_bytes(b"x")
    c = AutoEditCoordinator(parent=None)
    c.set_analyzers([("silence", _FakeAnalyzer({"silence_segments": [(0, 1000)]}))])
    with qtbot.waitSignal(c.result_ready, timeout=5000) as blocker:
        c.run(
            media_path=fake_media,
            source_hash="abc",
            whisper_model="base",
            cache_dir=tmp_path,
        )
    result, failed = blocker.args
    assert result.silence_segments == [(0, 1000)]
    assert failed == []


def test_coordinator_uses_cache_on_hit(qtbot, tmp_path: Path):
    """캐시 hit 이면 worker 안 띄움 — 즉시 result emit."""
    from screen_recorder.autoedit.result import AutoEditResult
    from screen_recorder.autoedit.cache import save, build_key
    cached = AutoEditResult(source_hash="abc", silence_segments=[(5, 50)])
    key = build_key(source_hash="abc", whisper_model="base", analyzer_versions={"silence": "v1"})
    save(tmp_path, key, cached)

    fake_media = tmp_path / "v.mp4"
    fake_media.write_bytes(b"x")
    c = AutoEditCoordinator(parent=None)
    c.set_analyzers([("silence", _FakeAnalyzer({"silence_segments": [(999, 9999)]}))])
    with qtbot.waitSignal(c.result_ready, timeout=5000) as blocker:
        c.run(media_path=fake_media, source_hash="abc", whisper_model="base", cache_dir=tmp_path)
    result, _ = blocker.args
    assert result.silence_segments == [(5, 50)]
