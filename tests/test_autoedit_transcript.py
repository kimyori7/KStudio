"""TranscriptAnalyzer — Whisper transcribe 결과 → AutoEditResult.transcript_segments."""
from pathlib import Path
from unittest.mock import patch, MagicMock
from screen_recorder.autoedit.analyzers.transcript import TranscriptAnalyzer


def test_transcript_segments_mapped(tmp_path: Path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    fake_transcribe = MagicMock(return_value=[
        MagicMock(start=0.0, end=1.5, text="안녕하세요"),
        MagicMock(start=1.5, end=3.0, text="자동 편집입니다"),
    ])
    with patch("screen_recorder.autoedit.analyzers.transcript._transcribe", fake_transcribe):
        a = TranscriptAnalyzer()
        payload = a.analyze(media)
    segs = payload["transcript_segments"]
    assert segs[0] == {"in_ms": 0, "out_ms": 1500, "text": "안녕하세요"}
    assert segs[1] == {"in_ms": 1500, "out_ms": 3000, "text": "자동 편집입니다"}
