from pathlib import Path
from unittest.mock import patch
from screen_recorder.autoedit.analyzers.bpm import BPMAnalyzer


def test_beats_mapped_to_ms_with_confidence(tmp_path: Path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    with patch("screen_recorder.autoedit.analyzers.bpm._beat_track",
               return_value=([0.5, 1.0, 1.5], 120.0)):
        a = BPMAnalyzer()
        payload = a.analyze(media)
    assert payload["beats"] == [(500, 0.7), (1000, 0.7), (1500, 0.7)]
