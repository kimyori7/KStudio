"""TranscriptAnalyzer — Whisper transcribe 결과 → AutoEditResult.transcript_segments."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from screen_recorder.autoedit.analyzers.transcript import TranscriptAnalyzer
from screen_recorder.autoedit.analyzers.base import AnalyzerCancelled


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


def test_analyze_forwards_is_cancelled_to_transcribe(tmp_path: Path):
    """analyze(is_cancelled=cb) → _transcribe(is_cancelled=cb) — segment 루프까지 propagate.

    회귀 보호: 사용자가 자동편집 중 취소 눌렀는데 whisper 가 영상 끝까지 다 돈
    버그 (2026-05-28). _transcribe 가 콜백을 받아 Transcriber 의 segment 루프에 전달
    하지 않으면 cancel 이 발생해도 다음 segment 추론 안 멈춤.
    """
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    captured: dict = {}
    def _fake_transcribe(*args, **kwargs):
        captured["is_cancelled"] = kwargs.get("is_cancelled")
        return []

    with patch("screen_recorder.autoedit.analyzers.transcript._transcribe", _fake_transcribe):
        a = TranscriptAnalyzer()
        my_cb = lambda: False
        a.analyze(media, is_cancelled=my_cb)
    assert captured["is_cancelled"] is my_cb, "is_cancelled 콜백이 _transcribe 까지 전달돼야 함"


def test_analyze_normalizes_transcribe_cancelled_to_analyzer_cancelled(tmp_path: Path):
    """Transcriber 의 TranscribeCancelled → autoedit 의 AnalyzerCancelled 로 재발생.

    worker 가 try/except AnalyzerCancelled 패턴이라 별개 예외면 generic Exception
    경로로 빠져 "analyzer 실패" 로 기록 → 사용자에겐 취소가 아닌 에러로 보임.
    """
    from screen_recorder.agent.transcript import TranscribeCancelled

    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")

    def _raise_cancel(*args, **kwargs):
        raise TranscribeCancelled()

    with patch("screen_recorder.autoedit.analyzers.transcript._transcribe", _raise_cancel):
        a = TranscriptAnalyzer()
        with pytest.raises(AnalyzerCancelled):
            a.analyze(media, is_cancelled=lambda: True)
