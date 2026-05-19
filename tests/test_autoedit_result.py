"""AutoEditResult — 4 analyzer raw 결과 dataclass."""
from screen_recorder.autoedit.result import AutoEditResult


def test_result_default_empty():
    r = AutoEditResult(source_hash="abc")
    assert r.source_hash == "abc"
    assert r.silence_segments == []
    assert r.transcript_segments == []
    assert r.scene_changes == []
    assert r.beats == []


def test_result_to_dict_roundtrip():
    r = AutoEditResult(
        source_hash="abc",
        silence_segments=[(100, 200), (500, 800)],
        transcript_segments=[{"in_ms": 0, "out_ms": 1000, "text": "hi"}],
        scene_changes=[(2000, 35.0)],
        beats=[(1500, 0.8)],
    )
    d = r.to_dict()
    restored = AutoEditResult.from_dict(d)
    assert restored == r
