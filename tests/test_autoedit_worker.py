"""AutoEditWorker — QThread 안에서 analyzer 들 순차 실행, 진행률 emit, 결과 emit."""
from pathlib import Path
from PySide6.QtCore import Qt

from screen_recorder.autoedit.worker import AutoEditWorker
from screen_recorder.autoedit.analyzers.base import Analyzer


class _FakeAnalyzer(Analyzer):
    name = "fake"
    version = "v1"
    def __init__(self, payload: dict) -> None:
        self._payload = payload
    def analyze(self, media_path, *, progress=None, is_cancelled=None):
        if progress:
            progress(0.5)
        return self._payload


def test_worker_runs_analyzers_and_emits_result(qtbot, tmp_path: Path):
    fake_media = tmp_path / "v.mp4"
    fake_media.write_bytes(b"x")
    w = AutoEditWorker(
        media_path=fake_media,
        source_hash="abc",
        whisper_model="base",
        analyzers=[
            ("silence", _FakeAnalyzer({"silence_segments": [(100, 1000)]})),
        ],
    )
    with qtbot.waitSignal(w.result_ready, timeout=5000) as blocker:
        w.start()
    result = blocker.args[0]
    assert result.silence_segments == [(100, 1000)]
    assert result.source_hash == "abc"


def test_worker_emits_progress(qtbot, tmp_path: Path):
    fake_media = tmp_path / "v.mp4"
    fake_media.write_bytes(b"x")
    w = AutoEditWorker(
        media_path=fake_media,
        source_hash="abc",
        whisper_model="base",
        analyzers=[("silence", _FakeAnalyzer({"silence_segments": []}))],
    )
    progress_values = []
    w.progress_updated.connect(lambda label, frac: progress_values.append((label, frac)))
    with qtbot.waitSignal(w.result_ready, timeout=5000):
        w.start()
    assert any("silence" in lbl or "fake" in lbl for lbl, _ in progress_values)
