"""사이드카 직렬화 + atomic write."""
import json
from pathlib import Path

import pytest

from screen_recorder.effects.sidecar import Sidecar, Trim, save_atomic, load
from screen_recorder.effects.types.caption import CaptionEffect, Font
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.effects.types.cut import CutEffect


def _sample_sidecar() -> Sidecar:
    return Sidecar(
        version=1,
        source_path="D:/Recordings/test.mp4",
        source_hash="abc123",
        trim=Trim(in_ms=0, out_ms=30000),
        effects=[
            CaptionEffect(id="c1", in_ms=1000, out_ms=4000,
                          text="안녕", font=Font(family="Pretendard", size=48)),
            SpeedEffect(id="s1", in_ms=5000, out_ms=10000, rate=2.0),
            CutEffect(id="cut1", in_ms=12000, out_ms=14000),
        ],
    )


def test_roundtrip_preserves_all_fields():
    sc = _sample_sidecar()
    d = sc.to_dict()
    sc2 = Sidecar.from_dict(d)
    assert sc2.version == 1
    assert sc2.source_path == "D:/Recordings/test.mp4"
    assert sc2.trim.in_ms == 0 and sc2.trim.out_ms == 30000
    assert len(sc2.effects) == 3
    assert sc2.effects[0].text == "안녕"
    assert sc2.effects[0].font.family == "Pretendard"
    assert sc2.effects[1].rate == 2.0
    assert sc2.effects[2].type == "cut"


def test_to_dict_yields_serializable_json():
    sc = _sample_sidecar()
    json.dumps(sc.to_dict(), ensure_ascii=False)  # 예외 없이 직렬화 가능


def test_save_atomic_then_load(tmp_path: Path):
    sc = _sample_sidecar()
    target = tmp_path / "x.kstudio"
    save_atomic(target, sc)
    loaded = load(target)
    assert loaded.source_hash == "abc123"
    assert loaded.effects[0].text == "안녕"


def test_save_atomic_uses_tmp_then_rename(tmp_path: Path, monkeypatch):
    """저장 도중 프로세스가 죽어도 기존 파일이 손상되지 않는지 — 임시파일 → rename 확인."""
    sc = _sample_sidecar()
    target = tmp_path / "x.kstudio"
    target.write_text('{"existing": "old"}', encoding="utf-8")

    save_atomic(target, sc)
    # 새 내용으로 교체됨
    assert "existing" not in target.read_text(encoding="utf-8")
    # 임시 파일이 남아있지 않음
    assert not list(tmp_path.glob("*.tmp"))


def test_load_unknown_effect_type_raises(tmp_path: Path):
    target = tmp_path / "bogus.kstudio"
    target.write_text(
        json.dumps({
            "version": 1, "source_path": "x", "source_hash": "y",
            "trim": {"in_ms": 0, "out_ms": 1000},
            "effects": [{"type": "wand", "id": "w1", "in_ms": 0, "out_ms": 100}],
        }),
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="unknown effect type"):
        load(target)


def test_load_missing_file_returns_empty_sidecar(tmp_path: Path):
    """사이드카가 없으면 효과 0개의 빈 사이드카로 반환 (탭 열기 시 자연스러운 fallback)."""
    target = tmp_path / "missing.kstudio"
    sc = load(target, missing_ok=True, source_path="src.mp4", source_hash="h")
    assert sc.effects == []
    assert sc.source_hash == "h"


# ---- Stage 4a: CutEffect 확장 round-trip ----

def test_sidecar_cut_with_insert_roundtrip():
    """CutEffect + B 영상 필드들이 JSON round-trip 으로 보존됨."""
    from screen_recorder.effects.sidecar import Sidecar
    from screen_recorder.effects.types.cut import CutEffect

    sc = Sidecar(
        source_path="D:/Recordings/a.mp4",
        source_hash="abc123",
        effects=[CutEffect(
            in_ms=4000, out_ms=7000,
            src="D:/Clips/intro.mp4",
            src_in_ms=500, src_out_ms=4500,
            src_duration_ms=6000,
            scale_mode="fill",
        )],
    )
    d = sc.to_dict()
    restored = Sidecar.from_dict(d)

    assert len(restored.effects) == 1
    e = restored.effects[0]
    assert isinstance(e, CutEffect)
    assert e.in_ms == 4000
    assert e.out_ms == 7000
    assert e.src == "D:/Clips/intro.mp4"
    assert e.src_in_ms == 500
    assert e.src_out_ms == 4500
    assert e.src_duration_ms == 6000
    assert e.scale_mode == "fill"
    assert e.has_insert
    assert e.insert_duration_ms == 4000


def test_sidecar_cut_splice_with_insert_roundtrip():
    """splice point (in_ms == out_ms) cut 도 round-trip 보존."""
    from screen_recorder.effects.sidecar import Sidecar
    from screen_recorder.effects.types.cut import CutEffect

    sc = Sidecar(effects=[CutEffect(
        in_ms=3000, out_ms=3000,
        src="D:/Clips/b.mp4",
        src_in_ms=0, src_out_ms=2000,
        src_duration_ms=2000,
    )])
    restored = Sidecar.from_dict(sc.to_dict())
    e = restored.effects[0]
    assert e.is_splice
    assert e.has_insert
    assert e.insert_duration_ms == 2000


def test_sidecar_cut_simple_roundtrip():
    """src 비어있는 단순 자르기도 round-trip 보존 (기본값으로 복원)."""
    from screen_recorder.effects.sidecar import Sidecar
    from screen_recorder.effects.types.cut import CutEffect

    sc = Sidecar(effects=[CutEffect(in_ms=5000, out_ms=8000)])
    restored = Sidecar.from_dict(sc.to_dict())
    e = restored.effects[0]
    assert isinstance(e, CutEffect)
    assert not e.has_insert
    assert e.src == ""
    assert e.scale_mode == "fit"


def test_sidecar_cut_legacy_dict_loads_with_defaults():
    """기존 사이드카 (src 필드 없음) 도 dataclass 기본값으로 정상 로드."""
    from screen_recorder.effects.sidecar import Sidecar

    legacy = {
        "version": 1,
        "source_path": "",
        "source_hash": "",
        "trim": {"in_ms": 0, "out_ms": 0},
        "effects": [{
            "id": "uuid-legacy",
            "type": "cut",
            "in_ms": 1000,
            "out_ms": 2000,
        }],
    }
    sc = Sidecar.from_dict(legacy)
    assert len(sc.effects) == 1
    e = sc.effects[0]
    assert e.in_ms == 1000
    assert e.out_ms == 2000
    assert e.src == ""
    assert e.scale_mode == "fit"
