"""SilenceAnalyzer — Whisper VAD 결과 → 무음 구간 (start_ms, end_ms)."""
from pathlib import Path
from unittest.mock import patch
from screen_recorder.autoedit.analyzers.silence import SilenceAnalyzer


def test_silence_segments_are_gaps_between_voice(tmp_path: Path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    fake_voice = [(1.0, 2.0), (3.0, 4.0)]
    with patch("screen_recorder.autoedit.analyzers.silence._detect_voice_intervals",
               return_value=(fake_voice, 5.0)):
        a = SilenceAnalyzer()
        payload = a.analyze(media)
    assert payload["silence_segments"] == [
        (0, 1000), (2000, 3000), (4000, 5000),
    ]


def test_no_voice_means_entire_video_silent(tmp_path: Path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    with patch("screen_recorder.autoedit.analyzers.silence._detect_voice_intervals",
               return_value=([], 10.0)):
        a = SilenceAnalyzer()
        payload = a.analyze(media)
    assert payload["silence_segments"] == [(0, 10000)]


def test_all_voice_means_no_silence(tmp_path: Path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    with patch("screen_recorder.autoedit.analyzers.silence._detect_voice_intervals",
               return_value=([(0.0, 5.0)], 5.0)):
        a = SilenceAnalyzer()
        payload = a.analyze(media)
    assert payload["silence_segments"] == []
