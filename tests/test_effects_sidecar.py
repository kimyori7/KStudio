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
