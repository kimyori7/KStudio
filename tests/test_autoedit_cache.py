"""autoedit cache — 디스크 JSON load/save + 키 무효화."""
from pathlib import Path
from screen_recorder.autoedit.result import AutoEditResult
from screen_recorder.autoedit.cache import save, load, build_key, CACHE_SCHEMA_VERSION


def test_build_key_includes_all_inputs():
    k = build_key(source_hash="abc", whisper_model="base", analyzer_versions={"silence": "v1", "transcript": "v1"})
    assert "abc" in k
    assert CACHE_SCHEMA_VERSION in k
    assert "base" in k


def test_save_load_roundtrip(tmp_path: Path):
    r = AutoEditResult(source_hash="abc", silence_segments=[(100, 200)])
    key = build_key(source_hash="abc", whisper_model="base", analyzer_versions={"silence": "v1"})
    save(tmp_path, key, r)
    loaded = load(tmp_path, key)
    assert loaded == r


def test_load_missing_returns_none(tmp_path: Path):
    assert load(tmp_path, "missing-key") is None


def test_load_corrupted_returns_none(tmp_path: Path):
    p = tmp_path / "corrupt.autoedit.json"
    p.write_text("{ not json")
    assert load(tmp_path, "corrupt") is None
