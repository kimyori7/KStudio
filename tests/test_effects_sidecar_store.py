"""영상 hash + 사이드카 폴더 매핑."""
from pathlib import Path

import pytest

from screen_recorder.effects.sidecar_store import (
    compute_video_hash, SidecarStore, default_sidecar_dir,
)
from screen_recorder.effects.sidecar import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect


def test_compute_video_hash_stable_for_same_content(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    payload = b"x" * (2 * 1024 * 1024)  # 2MB — 첫 1MB 만 hash
    a.write_bytes(payload)
    b.write_bytes(payload)
    assert compute_video_hash(a) == compute_video_hash(b)
    # 40자 hex (sha-1)
    assert len(compute_video_hash(a)) == 40


def test_compute_video_hash_differs_for_different_content(tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"a" * 2048)
    b.write_bytes(b"b" * 2048)
    assert compute_video_hash(a) != compute_video_hash(b)


def test_compute_video_hash_handles_under_1mb(tmp_path: Path):
    """파일이 1MB 보다 작아도 hash 계산 — 파일 전체가 hash 대상."""
    small = tmp_path / "small.mp4"
    small.write_bytes(b"hello")
    h = compute_video_hash(small)
    assert len(h) == 40


def test_default_sidecar_dir_is_appdata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    d = default_sidecar_dir()
    assert d == tmp_path / "appdata" / "KStudio" / "sidecars"


def test_store_save_and_load(tmp_path: Path):
    store_dir = tmp_path / "sidecars"
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video-content" * 100)

    store = SidecarStore(store_dir)
    sc = Sidecar(
        source_path=str(video),
        source_hash=compute_video_hash(video),
        trim=Trim(in_ms=0, out_ms=10000),
        effects=[CaptionEffect(in_ms=0, out_ms=1000, text="hi")],
    )
    store.save_for(video, sc)
    loaded = store.load_for(video)
    assert loaded is not None
    assert loaded.effects[0].text == "hi"


def test_store_load_returns_none_when_missing(tmp_path: Path):
    store_dir = tmp_path / "sidecars"
    video = tmp_path / "v.mp4"
    video.write_bytes(b"new-video-content")

    store = SidecarStore(store_dir)
    assert store.load_for(video) is None


def test_store_hash_collision_creates_new_file(tmp_path: Path, monkeypatch):
    """두 영상 파일의 첫 1MB 가 같으면 hash 충돌. source_path 가 다르면 새 사이드카 생성."""
    store_dir = tmp_path / "sidecars"
    same_payload = b"same-bytes" * 200

    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    v1.write_bytes(same_payload)
    v2.write_bytes(same_payload)
    assert compute_video_hash(v1) == compute_video_hash(v2)  # 충돌

    store = SidecarStore(store_dir)
    store.save_for(v1, Sidecar(source_path=str(v1), source_hash=compute_video_hash(v1),
                                effects=[CaptionEffect(in_ms=0, out_ms=1, text="v1")]))
    store.save_for(v2, Sidecar(source_path=str(v2), source_hash=compute_video_hash(v2),
                                effects=[CaptionEffect(in_ms=0, out_ms=1, text="v2")]))

    loaded1 = store.load_for(v1)
    loaded2 = store.load_for(v2)
    assert loaded1.effects[0].text == "v1"
    assert loaded2.effects[0].text == "v2"
    # 두 파일이 별도로 존재
    files = sorted(p.name for p in store_dir.glob("*.kstudio"))
    assert len(files) == 2
