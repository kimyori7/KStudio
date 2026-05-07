"""사이드카 (.kstudio) JSON 직렬화 + atomic write."""
from __future__ import annotations
from dataclasses import dataclass, field, fields, is_dataclass, asdict
import json
import os
from pathlib import Path
from typing import Any

from .model import Effect
from .types import effect_class_for


CURRENT_VERSION = 1


@dataclass
class Trim:
    in_ms: int = 0
    out_ms: int = 0


@dataclass
class Sidecar:
    version: int = CURRENT_VERSION
    source_path: str = ""
    source_hash: str = ""
    trim: Trim = field(default_factory=Trim)
    effects: list[Effect] = field(default_factory=list)

    # ---- serialize ----
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "trim": asdict(self.trim),
            "effects": [_effect_to_dict(e) for e in self.effects],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Sidecar":
        trim_d = d.get("trim") or {}
        effects_d = d.get("effects") or []
        return cls(
            version=int(d.get("version", CURRENT_VERSION)),
            source_path=str(d.get("source_path", "")),
            source_hash=str(d.get("source_hash", "")),
            trim=Trim(in_ms=int(trim_d.get("in_ms", 0)),
                      out_ms=int(trim_d.get("out_ms", 0))),
            effects=[_effect_from_dict(e) for e in effects_d],
        )


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
