"""편집 제안 큐 — Claude 가 propose_effect 로 쌓고 apply_proposals 로 커밋.

설계 원칙 (advisor 권고):
- Claude 의 mutation 도구는 직접 sidecar 를 건드리지 않음. 큐에만 쌓고 apply 시점에
  UI 스레드로 마샬링.
- payload 검증은 큐 추가 시점 — Claude 가 잘못된 데이터 보내면 즉시 거부.
- apply 는 active VideoTab.edit_controller.add_effect() 위임 — 같은 경로로 들어가
  undo/redo/autosave 모두 자동 활성.

Thread safety:
- ProposalQueue 는 `threading.Lock` 으로 보호. 도구는 worker(asyncio) 스레드에서
  add/list, UI 스레드에서 take_all. lock 으로 race 차단.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..effects.model import Effect
from ..effects.types.caption import CaptionEffect
from ..effects.types.cut import CutEffect
from ..effects.types.speed import SpeedEffect

_log = logging.getLogger(__name__)


VALID_TYPES = ("caption", "cut", "speed", "zoom", "broll", "arrow")
VALID_ACTIONS = ("add", "remove", "modify")


@dataclass
class EffectProposal:
    """큐에 쌓이는 한 제안.

    action="add" — payload 는 type 별 새 효과 스키마. type 필수.
    action="remove" — payload 는 {"effect_id": "..."}. type 은 선택(보고용).
    action="modify" — payload 는 {"effect_id": "...", ...override 필드}. 부분 갱신.
    """
    id: str = field(default_factory=lambda: f"prop_{uuid.uuid4().hex[:8]}")
    action: str = "add"
    type: str = ""
    payload: dict = field(default_factory=dict)
    note: Optional[str] = None


def build_effect_from_proposal(proposal: EffectProposal) -> Effect:
    """proposal.payload → Effect dataclass 인스턴스.

    payload 형식 (type 별):
    - caption: {in_ms, out_ms, text, track_idx?}
    - cut:     {in_ms, out_ms}   # out_ms == in_ms 면 splice point
    - speed:   {in_ms, out_ms, rate}
    - zoom:    {in_ms, out_ms, start:{x,y,scale}, end:{x,y,scale}}
    - broll:   {in_ms, out_ms, src, track_idx?}
    - arrow:   {in_ms, out_ms, start:{x,y}, end:{x,y}, track_idx?}
    """
    p = proposal.payload
    in_ms = int(p["in_ms"])
    out_ms = int(p["out_ms"])
    track_idx = int(p.get("track_idx", 0))

    t = proposal.type
    if t == "caption":
        text = str(p.get("text", ""))
        return CaptionEffect(in_ms=in_ms, out_ms=out_ms, text=text, track_idx=track_idx)
    if t == "cut":
        return CutEffect(in_ms=in_ms, out_ms=out_ms)
    if t == "speed":
        rate = float(p.get("rate", 1.0))
        return SpeedEffect(in_ms=in_ms, out_ms=out_ms, rate=rate)
    if t == "zoom":
        from ..effects.types.zoom import ZoomEffect, ZoomPoint
        start = p.get("start", {})
        end = p.get("end", {})
        extra: dict[str, Any] = {}
        # 2026-05-13: 사용자 보고 — 에이전트가 fit_screen 모드(기본)만 써서
        # 화면 전체가 줌됨. magnify_region 모드 / dest rect 도 propose 가능하도록
        # 옵션 필드 통과시킴. 누락 시 ZoomEffect 의 기본값 사용.
        if "mode" in p:
            extra["mode"] = str(p["mode"])
        for k in ("region_w", "region_h", "dest_cx", "dest_cy", "dest_w", "dest_h"):
            if k in p:
                extra[k] = float(p[k])
        return ZoomEffect(
            in_ms=in_ms, out_ms=out_ms,
            start=ZoomPoint(
                cx=float(start.get("x", 0.5)),
                cy=float(start.get("y", 0.5)),
                scale=float(start.get("scale", 1.0)),
            ),
            end=ZoomPoint(
                cx=float(end.get("x", 0.5)),
                cy=float(end.get("y", 0.5)),
                scale=float(end.get("scale", 1.5)),
            ),
            **extra,
        )
    if t == "broll":
        from ..effects.types.broll import BrollEffect, PipConfig
        src = str(p.get("src", ""))
        if not src:
            raise ValueError("broll payload requires 'src' (file path)")
        # 2026-05-14 회귀 fix: 사용자 보고 "AI 가 곁들임 추가하면 여전히 안 보임".
        # 원인: BrollEffect.placement 기본값 = "fullscreen" 인데 propose 가 placement
        # 명시 안 해 fullscreen 으로 들어감. PreviewOverlay 의 broll 가이드는
        # `placement != "pip"` 이면 skip → 사용자 입장에선 "추가됐는데 화면에 아무것도 없음".
        # 에이전트가 broll 을 propose 할 때 99% 의도는 PiP 박스 (작은 사각형으로 곁들임 표시).
        # 따라서 *propose 의 기본을 pip* 로 뒤집고, 사용자 명시(payload.placement="fullscreen")
        # 시에만 풀스크린.
        placement = str(p.get("placement", "pip"))
        return BrollEffect(
            in_ms=in_ms, out_ms=out_ms, src=src,
            placement=placement,
            pip=PipConfig() if placement == "pip" else None,
            track_idx=track_idx,
        )
    if t == "arrow":
        from ..effects.types.arrow import ArrowEffect, Point
        start = p.get("start", {})
        end = p.get("end", {})
        return ArrowEffect(
            in_ms=in_ms, out_ms=out_ms,
            start=Point(
                x=float(start.get("x", 0.3)),
                y=float(start.get("y", 0.5)),
            ),
            end=Point(
                x=float(end.get("x", 0.7)),
                y=float(end.get("y", 0.5)),
            ),
            track_idx=track_idx,
        )
    raise ValueError(f"Unknown effect type: {t!r}")


def apply_modify_overrides(target: Effect, overrides: dict) -> Effect:
    """기존 효과에 modify proposal 의 overrides 를 적용해 새 Effect 반환.

    핵심: nested dict (예: caption.font={"family":"...", "size":48}) 가 그대로
    `dataclasses.replace` 로 들어가면 *dataclass 자리에 dict* 가 박혀서 이후 paint /
    render 코드가 `AttributeError: 'dict' object has no attribute 'family'` 로 폭발.

    해결: target → asdict → overrides merge (nested 도 깊이 merge) → 사이드카 표준
    역직렬화 `_effect_from_dict` 로 재구성. 모든 nested dataclass 가 적절한 클래스 인스턴스
    가 됨.

    사용자 보고 (2026-05-13): "AI 가 작업 2번 하니까 플레이 화면에 효과들이 안 나옴".
    propose_modify_effect 의 첫 호출은 정상이지만 nested 필드 변경 시 sidecar 에 dict
    가 박혀 다음 paint 부터 모든 효과 그리기 실패.
    """
    from dataclasses import asdict
    from ..effects.sidecar import _effect_from_dict

    base = asdict(target)
    _deep_merge(base, overrides)
    return _effect_from_dict(base)


def _deep_merge(dst: dict, src: dict) -> None:
    """dst 를 in-place 로 src 와 깊이 merge. src 의 dict 값은 dst 의 같은 키 dict 와 재귀
    merge. 다른 값은 src 가 override.

    이래야 partial nested override 가 가능: 예 modify caption {font:{size:48}} 이 기존
    font.family 를 덮어쓰지 않고 size 만 바꿈.
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def validate_remove_payload(payload: dict) -> Optional[str]:
    """remove proposal 의 payload 검증 — effect_id 필수."""
    if "effect_id" not in payload:
        return "remove payload must include 'effect_id'"
    if not isinstance(payload["effect_id"], str) or not payload["effect_id"]:
        return "effect_id must be a non-empty string"
    return None


def validate_modify_payload(payload: dict) -> Optional[str]:
    """modify proposal 의 payload 검증 — effect_id 필수 + 최소 한 개 override 필드."""
    if "effect_id" not in payload:
        return "modify payload must include 'effect_id'"
    if not isinstance(payload["effect_id"], str) or not payload["effect_id"]:
        return "effect_id must be a non-empty string"
    override_keys = [k for k in payload.keys() if k != "effect_id"]
    if not override_keys:
        return "modify payload must include at least one override field besides 'effect_id'"
    return None


# 정규화 좌표 허용 범위 — Point.__post_init__ 와 동일 ([-0.5, 1.5]).
# 이 범위 밖 = Claude 가 픽셀 좌표 (예: 160) 로 잘못 보낸 것으로 간주하고 거부.
_COORD_MIN = -0.5
_COORD_MAX = 1.5


def _validate_xy(point: dict, label: str) -> Optional[str]:
    """{x, y} 가 0~1 정규화 범위 ([-0.5, 1.5]) 인지 검사.

    Claude 가 '320 픽셀 프레임 보고 x=160' 같은 픽셀 좌표 보내는 사고를 큐 적재
    *시점* 에 잡음 — apply 시점에 Point.__post_init__ 가 잡으면 Claude 는 이미 '성공'
    응답을 받은 상태라 다음 단계로 넘어가버림.
    """
    for key in ("x", "y"):
        if key not in point:
            return f"{label}.{key} missing"
        try:
            v = float(point[key])
        except (TypeError, ValueError):
            return f"{label}.{key} must be a number, got {point[key]!r}"
        if not (_COORD_MIN <= v <= _COORD_MAX):
            return (
                f"{label}.{key}={v} out of normalized range [{_COORD_MIN}, {_COORD_MAX}]. "
                f"좌표는 0~1 정규화 (0=좌상단, 1=우하단). 픽셀 값이 아닙니다."
            )
    return None


def validate_payload(eff_type: str, payload: dict) -> Optional[str]:
    """add proposal 의 payload 검증.

    필수 필드만 검사. 옵셔널 필드(track_idx) 는 누락 시 0 으로 기본값.
    """
    if eff_type not in VALID_TYPES:
        return f"unknown type {eff_type!r}. valid: {', '.join(VALID_TYPES)}"
    if "in_ms" not in payload or "out_ms" not in payload:
        return "payload must include in_ms and out_ms"
    try:
        in_ms = int(payload["in_ms"])
        out_ms = int(payload["out_ms"])
    except (TypeError, ValueError):
        return "in_ms / out_ms must be integers"
    if in_ms < 0 or out_ms < 0:
        return "in_ms / out_ms must be >= 0"
    if eff_type != "cut" and out_ms <= in_ms:
        return f"out_ms ({out_ms}) must be > in_ms ({in_ms}) for type {eff_type}"
    if eff_type == "caption" and "text" not in payload:
        return "caption payload must include 'text'"
    if eff_type == "speed":
        if "rate" not in payload:
            return "speed payload must include 'rate'"
        try:
            r = float(payload["rate"])
        except (TypeError, ValueError):
            return "speed rate must be a number"
        if r <= 0 or r > 10:
            return f"speed rate ({r}) out of allowed range (0, 10]"
    if eff_type == "broll":
        if "src" not in payload:
            return "broll payload must include 'src' (file path)"
        # placement 옵션 — 명시 시 "fullscreen" 또는 "pip" 만 허용. 누락 = "pip" 기본값.
        if "placement" in payload:
            pl = payload["placement"]
            if pl not in ("fullscreen", "pip"):
                return (
                    f"broll.placement={pl!r} invalid. "
                    "'pip' (작은 PIP 박스로 곁들임, 기본값) 또는 'fullscreen' (구간 전체 대체) 만 허용."
                )
    if eff_type == "arrow":
        for key in ("start", "end"):
            point = payload.get(key)
            if not isinstance(point, dict):
                return f"arrow payload must include {key}:{{x, y}}"
            err = _validate_xy(point, f"arrow.{key}")
            if err is not None:
                return err
    if eff_type == "zoom":
        for key in ("start", "end"):
            point = payload.get(key)
            if not isinstance(point, dict):
                return f"zoom payload must include {key}:{{x, y, scale}}"
            err = _validate_xy(point, f"zoom.{key}")
            if err is not None:
                return err
            # scale 은 픽셀 단위 아님 (1.0 = 원본, 2.0 = 2배). 양수.
            if "scale" not in point:
                return f"zoom.{key}.scale missing"
            try:
                s = float(point["scale"])
            except (TypeError, ValueError):
                return f"zoom.{key}.scale must be a number"
            if s <= 0 or s > 32:
                return f"zoom.{key}.scale={s} out of allowed range (0, 32]"
        # 옵션 — Phase 24/27 모드 / region / dest. 누락 시 ZoomEffect 의 기본값.
        mode = payload.get("mode")
        if mode is not None and mode not in ("fit_screen", "magnify_region"):
            return (
                f"zoom.mode={mode!r} invalid. "
                "fit_screen (전체 화면 줌인/팬) 또는 magnify_region (일부 영역만 확대) 만 허용."
            )
        for key in ("region_w", "region_h"):
            if key in payload:
                try:
                    v = float(payload[key])
                except (TypeError, ValueError):
                    return f"zoom.{key} must be a number"
                if not (0.05 <= v <= 1.0):
                    return f"zoom.{key}={v} out of allowed range [0.05, 1.0]"
        for key in ("dest_cx", "dest_cy"):
            if key in payload:
                try:
                    v = float(payload[key])
                except (TypeError, ValueError):
                    return f"zoom.{key} must be a number"
                if not (0.0 <= v <= 1.0):
                    return f"zoom.{key}={v} out of allowed range [0, 1]"
        for key in ("dest_w", "dest_h"):
            if key in payload:
                try:
                    v = float(payload[key])
                except (TypeError, ValueError):
                    return f"zoom.{key} must be a number"
                if not (0.05 <= v <= 2.0):
                    return f"zoom.{key}={v} out of allowed range [0.05, 2.0]"
    return None


def _dedup_signature(proposal: EffectProposal) -> Optional[tuple]:
    """add proposal 의 '동일성 식별 튜플'. None 이면 dedup 대상 아님.

    2026-05-19 사용자 보고: Claude 가 같은 cut 효과 (in_ms=104280, out_ms=105240) 를
    3번 propose → 사이드카에 의미 없는 중복. propose 시점에 차단해 Claude 가 즉시 자기
    교정하도록.

    설계 — type 별 '식별 필드' 정의:
    - cut: (in_ms, out_ms) 만. 같은 구간 자르기는 정확히 1번이 의미.
    - caption: + text. 같은 범위 + 다른 text 는 의도적 overlay 가능 → dup 아님.
    - speed: + rate. 같은 범위 + 다른 rate 는 conflict 지만 dup 아님 (apply 가 처리).
    - broll: + src. 같은 범위 + 다른 src 는 2개 곁들임 overlay 가능.
    - zoom/arrow: 좌표 미세 조정 가능성 + false positive 위험 → dedup 안 함.
    - remove/modify: 동일 effect_id 다중 호출이 의도일 수 있음 → dedup 안 함.
    """
    if proposal.action != "add":
        return None
    p = proposal.payload
    try:
        in_ms = int(p.get("in_ms", 0))
        out_ms = int(p.get("out_ms", 0))
    except (TypeError, ValueError):
        return None
    t = proposal.type
    if t == "cut":
        return ("cut", in_ms, out_ms)
    if t == "caption":
        return ("caption", in_ms, out_ms, str(p.get("text", "")))
    if t == "speed":
        try:
            rate = float(p.get("rate", 1.0))
        except (TypeError, ValueError):
            return None
        return ("speed", in_ms, out_ms, rate)
    if t == "broll":
        return ("broll", in_ms, out_ms, str(p.get("src", "")))
    return None


class ProposalQueue:
    """Thread-safe 제안 큐. add/list 는 worker(asyncio) 에서, take_all 은 UI 에서."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[EffectProposal] = []

    def add(self, proposal: EffectProposal) -> None:
        with self._lock:
            self._items.append(proposal)

    def is_duplicate(self, proposal: EffectProposal) -> bool:
        """proposal 이 큐의 기존 항목과 식별 튜플이 일치하는지.

        action != 'add' 거나 type 이 dedup 대상 아니면 항상 False.
        호출자(propose_effect)는 add() 전에 이 함수를 검사하여 중복이면 Claude 에게
        error_result 로 자기 교정 유도.
        """
        sig = _dedup_signature(proposal)
        if sig is None:
            return False
        with self._lock:
            for existing in self._items:
                if _dedup_signature(existing) == sig:
                    return True
        return False

    def list(self) -> list[EffectProposal]:
        """현재 큐 스냅샷. 외부 변경 영향 없도록 copy."""
        with self._lock:
            return list(self._items)

    def take_all(self) -> list[EffectProposal]:
        """전체 꺼내고 비움 — apply 시점 호출."""
        with self._lock:
            taken = list(self._items)
            self._items.clear()
            return taken

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._items)
