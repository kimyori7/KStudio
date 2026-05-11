"""Sidecar v2 — video_track 필드 직렬화."""
from screen_recorder.effects import Sidecar
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.types.caption import CaptionEffect


def test_sidecar_default_has_empty_track_and_v2():
    sc = Sidecar(source_path="x.mp4", source_hash="h")
    assert sc.version == 3
    assert sc.video_track == []


def test_sidecar_to_dict_with_segment():
    cap = CaptionEffect(in_ms=100, out_ms=500, text="hi")
    seg = VideoSegment(
        src="src.mp4", src_in_ms=1000, src_out_ms=5000,
        src_duration_ms=10000, effects=[cap],
    )
    sc = Sidecar(
        source_path="x.mp4", source_hash="h", video_track=[seg],
    )
    d = sc.to_dict()
    assert d["version"] == 3
    assert len(d["video_track"]) == 1
    seg_raw = d["video_track"][0]
    assert seg_raw["src"] == "src.mp4"
    assert seg_raw["src_in_ms"] == 1000
    assert seg_raw["src_out_ms"] == 5000
    assert seg_raw["media_kind"] == "video"
    assert len(seg_raw["effects"]) == 1
    assert seg_raw["effects"][0]["type"] == "caption"
    assert seg_raw["effects"][0]["text"] == "hi"


def test_sidecar_from_dict_v2_round_trip():
    cap = CaptionEffect(in_ms=100, out_ms=500, text="hi")
    seg = VideoSegment(
        src="src.mp4", src_in_ms=1000, src_out_ms=5000,
        src_duration_ms=10000, effects=[cap],
    )
    sc = Sidecar(
        source_path="x.mp4", source_hash="h", video_track=[seg],
    )
    d = sc.to_dict()
    sc2 = Sidecar.from_dict(d)
    assert sc2.version == 3
    assert len(sc2.video_track) == 1
    assert sc2.video_track[0].src == "src.mp4"
    assert sc2.video_track[0].id == seg.id
    assert sc2.video_track[0].src_in_ms == 1000
    assert sc2.video_track[0].src_out_ms == 5000
    assert len(sc2.video_track[0].effects) == 1
    assert sc2.video_track[0].effects[0].text == "hi"
    assert sc2.video_track[0].effects[0].type == "caption"


def test_sidecar_v1_legacy_load_drops_old_data():
    """Schema v1 로 저장된 옛 데이터 → 빈 video_track 으로 시작 (마이그레이션 안 함)."""
    plain_v1 = {
        "version": 1,
        "source_path": "x.mp4",
        "source_hash": "h",
        "trim": {"in_ms": 1000, "out_ms": 5000},
        "effects": [
            {"type": "caption", "id": "c1", "in_ms": 0, "out_ms": 1000, "text": "old"}
        ],
    }
    sc = Sidecar.from_dict(plain_v1)
    assert sc.version == 3
    assert sc.video_track == []


def test_sidecar_v2_packed_migrates_to_v3_with_cumulative_start_ms():
    """v2 packed 데이터(start_ms 없음) → v3 누적합으로 자동 채움."""
    plain_v2 = {
        "version": 2,
        "source_path": "x.mp4",
        "source_hash": "h",
        "video_track": [
            {"src": "a.mp4", "src_in_ms": 0, "src_out_ms": 3000,
             "src_duration_ms": 3000, "media_kind": "video"},
            {"src": "b.mp4", "src_in_ms": 0, "src_out_ms": 2000,
             "src_duration_ms": 2000, "media_kind": "video"},
        ],
    }
    sc = Sidecar.from_dict(plain_v2)
    assert sc.version == 3
    assert len(sc.video_track) == 2
    assert sc.video_track[0].start_ms == 0
    assert sc.video_track[1].start_ms == 3000


def test_sidecar_image_segment_round_trip():
    """이미지 segment 도 직렬화 round-trip 가능."""
    seg = VideoSegment(
        src="img.png", media_kind="image", image_duration_ms=4000,
    )
    sc = Sidecar(source_path="x.mp4", source_hash="h", video_track=[seg])
    d = sc.to_dict()
    sc2 = Sidecar.from_dict(d)
    assert sc2.video_track[0].media_kind == "image"
    assert sc2.video_track[0].image_duration_ms == 4000
