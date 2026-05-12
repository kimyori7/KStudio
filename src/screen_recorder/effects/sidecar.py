"""사이드카 (.kstudio) JSON 직렬화 + atomic write.

Schema v2 (2026-05-08): video_track 기반 NLE 모델. 기존 v1 의 trim / effects (전역)
는 폐기 — 사용자 결정 (마이그레이션 없음).

Schema v3 (2026-05-08): segment 갭(gap) 지원 — VideoSegment 에 start_ms 추가.
v2 (packed list) → v3 마이그레이션은 list 순서 누적합으로 자동 채움.
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


CURRENT_VERSION = 3


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
            # Phase 19.5 hotfix5 — trim 과 effects 도 직렬화. 이전엔 누락되어 영상
            # 자체에 추가한 효과(caption/zoom/broll/speed) 가 디스크에 저장되지 않아
            # "재시작 후 편집 사라짐" 회귀의 진짜 원인.
            "trim": _to_plain(self.trim),
            "effects": [_effect_to_dict(e) for e in self.effects],
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
        if version < 3:
            # v2 → v3: start_ms 가 없던 packed 모델 → 누적합으로 채움.
            track: list[VideoSegment] = []
            cursor = 0
            for s_raw in track_raw:
                seg = _segment_from_dict({**s_raw, "start_ms": cursor})
                track.append(seg)
                cursor += seg.duration_ms
        else:
            track = [_segment_from_dict(s) for s in track_raw]
        # trim 과 effects 복원 (Phase 19.5 hotfix5).
        trim_raw = d.get("trim")
        if isinstance(trim_raw, dict):
            trim = Trim(
                in_ms=int(trim_raw.get("in_ms", 0)),
                out_ms=int(trim_raw.get("out_ms", 0)),
            )
        else:
            trim = Trim(in_ms=0, out_ms=0)
        eff_raw = d.get("effects") or []
        effects = [_effect_from_dict(e) for e in eff_raw if isinstance(e, dict)]
        return cls(
            version=CURRENT_VERSION,
            source_path=str(d.get("source_path", "")),
            source_hash=str(d.get("source_hash", "")),
            video_track=track,
            trim=trim,
            effects=effects,
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
        "start_ms": seg.start_ms,
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
        "start_ms": int(d.get("start_ms", 0)),
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


_EFFECT_MIN_DURATION_MS = 100   # 클램프 후 폭이 이보다 짧으면 효과 제거.


def combined_duration_ms(video_track: list[VideoSegment]) -> int:
    """video_track 의 끝점 (= max(start_ms + duration_ms)). 빈 트랙은 0.

    Gap-aware 끝 — segment 가 시간상 분산되어 있으면 가장 늦은 끝점이 곧 사용자
    combined timeline 의 끝.
    """
    if not video_track:
        return 0
    return max(s.start_ms + s.duration_ms for s in video_track)


def clamp_effects_to_track(sidecar: Sidecar) -> list[Effect]:
    """sidecar.effects 의 in_ms/out_ms 를 video_track 끝점에 맞춰 clamp.

    규칙:
    - effect.in_ms >= combined_end_ms → 제거 (시작이 트랙 끝 이후).
    - effect.out_ms > combined_end_ms → out_ms 를 combined_end_ms 로 clamp.
    - clamp 후 out_ms - in_ms < _EFFECT_MIN_DURATION_MS → 제거 (너무 짧음).

    pure 함수 — 새 list 반환. 호출자가 sidecar.effects 에 대입.
    cut/trim/segment delete 등으로 트랙 끝이 줄어들 때 효과가 trailing zone 에
    남는 것을 자동 정리. 빈 트랙 (첫 segment 생성 전) 이면 clamp 건너뜀 — 효과
    보존. 트랙 생기면 그때 정리됨.
    """
    from dataclasses import replace
    end_ms = combined_duration_ms(sidecar.video_track)
    if end_ms <= 0:
        return list(sidecar.effects)
    out: list[Effect] = []
    for eff in sidecar.effects:
        if eff.in_ms >= end_ms:
            continue
        if eff.out_ms <= end_ms:
            out.append(eff)
            continue
        new_out = end_ms
        if new_out - eff.in_ms < _EFFECT_MIN_DURATION_MS:
            continue
        out.append(replace(eff, out_ms=int(new_out)))
    return out


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
