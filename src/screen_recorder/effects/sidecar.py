"""사이드카 (.kstudio) JSON 직렬화 + atomic write.

Schema v2 (2026-05-08): video_track 기반 NLE 모델. 기존 v1 의 trim / effects (전역)
는 폐기 — 사용자 결정 (마이그레이션 없음).
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields, is_dataclass, asdict
import json
import os
from pathlib import Path
from typing import Any

from .model import Effect
from .segment import VideoSegment
from .types import effect_class_for


CURRENT_VERSION = 2


@dataclass
class Trim:
    """레거시 (v1) — 새 모델에서는 첫/끝 segment 의 src_in/out 으로 흡수. Stage D 에서 제거."""
    in_ms: int = 0
    out_ms: int = 0


@dataclass
class Sidecar:
    version: int = CURRENT_VERSION
    source_path: str = ""
    source_hash: str = ""
    video_track: list[VideoSegment] = field(default_factory=list)
    # 레거시 (v1) — Stage D 에서 제거.
    trim: Trim = field(default_factory=Trim)
    effects: list[Effect] = field(default_factory=list)

    # ---- serialize ----
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "video_track": [_segment_to_dict(s) for s in self.video_track],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Sidecar":
        version = int(d.get("version", 1))
        if version < 2:
            # v1 → v2: 옛 데이터 모두 폐기, 빈 track 으로 시작 (사용자 결정).
            return cls(
                version=CURRENT_VERSION,
                source_path=str(d.get("source_path", "")),
                source_hash=str(d.get("source_hash", "")),
                video_track=[],
            )
        track_raw = d.get("video_track") or []
        return cls(
            version=CURRENT_VERSION,
            source_path=str(d.get("source_path", "")),
            source_hash=str(d.get("source_hash", "")),
            video_track=[_segment_from_dict(s) for s in track_raw],
        )


def _segment_to_dict(seg: VideoSegment) -> dict[str, Any]:
    """VideoSegment → 사전. effects 도 nested 직렬화."""
    return {
        "id": seg.id,
        "src": seg.src,
        "src_in_ms": seg.src_in_ms,
        "src_out_ms": seg.src_out_ms,
        "src_duration_ms": seg.src_duration_ms,
        "media_kind": seg.media_kind,
        "image_duration_ms": seg.image_duration_ms,
        "effects": [_effect_to_dict(e) for e in seg.effects],
    }


def _segment_from_dict(d: dict[str, Any]) -> VideoSegment:
    """사전 → VideoSegment. effects 도 nested 역직렬화."""
    eff_raw = d.get("effects") or []
    kw: dict[str, Any] = {
        "src": str(d.get("src", "")),
        "src_in_ms": int(d.get("src_in_ms", 0)),
        "src_out_ms": int(d.get("src_out_ms", 0)),
        "src_duration_ms": int(d.get("src_duration_ms", 0)),
        "media_kind": str(d.get("media_kind", "video")),
        "image_duration_ms": int(d.get("image_duration_ms", 3000)),
        "effects": [_effect_from_dict(e) for e in eff_raw],
    }
    sid = d.get("id")
    if sid:
        kw["id"] = str(sid)
    return VideoSegment(**kw)


def _effect_to_dict(e: Effect) -> dict[str, Any]:
    """Effect (또는 자식 dataclass) → 사전. 중첩 dataclass 도 재귀 처리."""
    return _to_plain(e)


def _to_plain(value: Any) -> Any:
    """dataclass/list/dict/scalar → JSON-호환 사전 트리."""
    if is_dataclass(value):
        return {f.name: _to_plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    return value


def _effect_from_dict(d: dict[str, Any]) -> Effect:
    type_name = d.get("type")
    if not isinstance(type_name, str):
        raise KeyError("effect dict missing 'type'")
    cls = effect_class_for(type_name)  # KeyError if unknown
    return _from_plain(cls, d)


def _from_plain(cls: type, d: dict[str, Any]) -> Any:
    """사전 트리 → dataclass 인스턴스. 중첩 dataclass 자동 처리."""
    init_kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in d:
            continue
        raw = d[f.name]
        # 중첩 dataclass 재귀
        if is_dataclass(f.type) if isinstance(f.type, type) else False:
            init_kwargs[f.name] = _from_plain(f.type, raw) if raw is not None else None
        else:
            # f.type 이 string 또는 generic — 단순화: dict 면 자식 dataclass 추정 안 함, 그대로 전달
            init_kwargs[f.name] = _coerce_nested(f, raw)
    return cls(**init_kwargs)


def _coerce_nested(f, raw: Any) -> Any:
    """필드 type 힌트가 dataclass 인 경우 dict → dataclass 변환. 그 외는 raw 그대로."""
    # f.type 이 future annotation 으로 string 인 경우가 많음 → 클래스 객체 얻기 어려움.
    # 단순화: raw 가 dict 이고 cls.__annotations__ 의 해당 이름이 dataclass 면 변환.
    # 여기선 raw 가 dict 면 effect 의 알려진 자식 dataclass 풀에서 매칭 시도.
    if isinstance(raw, dict):
        # 캡션의 Font/Stroke/Background/Position/Fade, 줌의 ZoomPoint, broll 의 PipConfig
        from .types.caption import Font, Stroke, Background, Position, Fade
        from .types.zoom import ZoomPoint
        from .types.broll import PipConfig
        nested_pool: dict[str, type] = {
            "font": Font, "stroke": Stroke, "background": Background,
            "position": Position, "fade": Fade,
            "start": ZoomPoint, "end": ZoomPoint,
            "pip": PipConfig,
        }
        target_cls = nested_pool.get(f.name)
        if target_cls is not None:
            return _from_plain(target_cls, raw)
    return raw


def ensure_default_track(sidecar: Sidecar, source_duration_ms: int) -> None:
    """video_track 이 비어 있으면 source_path 가 가리키는 영상 1개 segment 로 채움.

    이미 segment 가 있으면 no-op. 영상 첫 로드 시 호출 (사이드카가 새로 생성됐거나
    v1 폐기 후 빈 상태일 때 단일 클립 트랙을 자연스럽게 시작).
    """
    if sidecar.video_track:
        return
    sidecar.video_track.append(VideoSegment(
        src=sidecar.source_path,
        src_in_ms=0,
        src_out_ms=0,
        src_duration_ms=int(max(0, source_duration_ms)),
        media_kind="video",
    ))


# ---- file I/O ----
def save_atomic(path: Path, sc: Sidecar) -> None:
    """JSON 직렬화 후 임시파일 → rename. 저장 중 프로세스 죽어도 기존 파일 보존."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(sc.to_dict(), ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def load(
    path: Path,
    *,
    missing_ok: bool = False,
    source_path: str = "",
    source_hash: str = "",
) -> Sidecar:
    """파일에서 Sidecar 로드.

    missing_ok=True 면 파일이 없을 때 빈 Sidecar 를 source_path/source_hash 로 반환.
    KeyError(unknown type) 같은 형식 오류는 그대로 raise.
    """
    path = Path(path)
    if not path.exists():
        if missing_ok:
            return Sidecar(source_path=source_path, source_hash=source_hash)
        raise FileNotFoundError(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    return Sidecar.from_dict(data)
