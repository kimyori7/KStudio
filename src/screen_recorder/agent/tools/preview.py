"""Preview 도구 — apply 전에 효과 결과 미리보기.

Claude 가 propose_effect 후 apply 전에 "이 좌표가 정말 의도한 위치인가" 자기 검증할 수
있도록 큐의 proposal 을 frame 에 합성한 PNG 반환. 좌표 어긋남을 사용자 손 빌리지 않고
스스로 잡아 propose_modify_effect 로 보정 가능 → 1차 시도 정확도 향상.

지원 type:
- zoom    : end 시점 crop+resize (가장 변형 큰 시점).
- arrow   : 시작점→끝점 선 + 화살촉 overlay.
- caption : 하단 중앙 텍스트 박스 overlay (대략적 — 실제 렌더 위치/폰트와 차이 가능).

미지원:
- cut / speed / broll : 시각 미리보기 의미 적음. error_result 로 거부.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Optional

from claude_agent_sdk import tool

from ..adapter import VideoSessionAdapter
from ..frame_extractor import extract_frame_png
from ..proposals import ProposalQueue
from ._response import error_result, image_result, no_active_video

_log = logging.getLogger(__name__)


PREVIEW_TOOL_NAMES = ("preview_proposal",)


# preview 가 시각적으로 의미 있는 효과 type — 그 외는 미지원.
_PREVIEWABLE_TYPES = frozenset({"zoom", "arrow", "caption"})


def make_preview_tools(
    adapter: VideoSessionAdapter,
    queue: ProposalQueue,
    ffmpeg_path: Optional[str],
) -> list:
    @tool(
        "preview_proposal",
        "큐에 쌓인 편집 제안 1개를 실제 적용 전에 미리 보기. "
        "proposal_id 가 가리키는 효과를 ms 시점 프레임에 합성한 PNG 반환. "
        "**자기 검증 워크플로우**: propose_effect → preview_proposal 로 결과 확인 → "
        "어긋났으면 propose_modify_effect 로 좌표 보정 → 다시 preview → apply_proposals. "
        "지원: zoom (end 시점 crop), arrow (선+화살촉), caption (하단 텍스트). "
        "cut/speed/broll 은 시각 미리보기 의미 없어 미지원.",
        {"proposal_id": str, "ms": int, "width": int},
    )
    async def preview_proposal(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        if not ffmpeg_path:
            return error_result("ffmpeg 경로 미설정 — preview 도구 비활성.")
        src = adapter.source_path()
        if not src:
            return error_result("활성 영상의 소스 경로가 없습니다.")

        proposal_id = str(args.get("proposal_id", "")).strip()
        if not proposal_id:
            return error_result("proposal_id 필수.")
        ms = max(0, int(args.get("ms", 0)))
        width = int(args.get("width") or 640)

        # 큐에서 id 매칭.
        target = None
        for p in queue.list():
            if p.id == proposal_id:
                target = p
                break
        if target is None:
            return error_result(
                f"proposal_id={proposal_id!r} 큐에 없음. "
                f"list_proposals 로 현재 큐 확인 후 다시 시도."
            )

        if target.action == "remove":
            return error_result(
                "preview 는 remove action 미지원 — 삭제 후 효과 자체가 없어 시각화 의미 없음."
            )

        # add: target.payload + target.type 그대로 사용.
        # modify: 기존 효과 + payload override 합성. 사이드카에서 target_effect 찾고
        #   apply_modify_overrides 로 새 Effect dataclass 만든 뒤 dict 화 → 동일 렌더 경로.
        if target.action == "modify":
            from dataclasses import asdict
            from ..proposals import apply_modify_overrides
            sc = adapter.sidecar()
            eid = str(target.payload.get("effect_id", ""))
            base_eff = next((e for e in (sc.effects if sc else []) if getattr(e, "id", "") == eid), None)
            if base_eff is None:
                return error_result(
                    f"modify preview: effect_id={eid!r} 가 사이드카에 없음. "
                    f"이미 사라진 효과를 modify 하려는 중일 수 있음."
                )
            overrides = {k: v for k, v in target.payload.items() if k != "effect_id"}
            try:
                merged_eff = apply_modify_overrides(base_eff, overrides)
            except (TypeError, ValueError, KeyError) as exc:
                return error_result(f"modify preview: override 적용 실패 — {exc}")
            preview_type = getattr(merged_eff, "type", "")
            if preview_type not in _PREVIEWABLE_TYPES:
                return error_result(
                    f"preview 는 시각 효과({', '.join(sorted(_PREVIEWABLE_TYPES))}) 만 지원. "
                    f"이 effect: type={preview_type!r}."
                )
            preview_payload = asdict(merged_eff)
            # ZoomEffect 등의 nested dict 가 {cx, cy, scale} 키 사용 — preview 는 x/y 기대.
            # asdict 결과를 우리 payload schema (x/y) 로 정규화.
            preview_payload = _normalize_payload_for_preview(preview_type, preview_payload)
        else:
            if target.type not in _PREVIEWABLE_TYPES:
                return error_result(
                    f"preview 는 시각 효과({', '.join(sorted(_PREVIEWABLE_TYPES))}) 만 지원. "
                    f"이 proposal: type={target.type!r}."
                )
            preview_type = target.type
            preview_payload = target.payload

        try:
            frame_png = extract_frame_png(src, ms, ffmpeg_path, width=width)
        except Exception as exc:
            _log.warning("preview_proposal: frame extract failed: %s", exc)
            return error_result(f"프레임 추출 실패: {exc}")

        try:
            from PIL import Image
            img = Image.open(io.BytesIO(frame_png)).convert("RGB")
            preview_img = _render_proposal_on_image(img, preview_type, preview_payload)
        except Exception as exc:
            _log.exception("preview_proposal: render failed")
            return error_result(f"미리보기 렌더 실패: {exc}")

        buf = io.BytesIO()
        preview_img.save(buf, format="PNG", optimize=True)
        return image_result(
            buf.getvalue(),
            caption=(
                f"preview: {target.type} {proposal_id} @ {ms}ms "
                f"(width={width}). 실제 export 와 차이 있을 수 있음 — 대략적 자기 검증용."
            ),
        )

    return [preview_proposal]


def _normalize_payload_for_preview(eff_type: str, payload: dict) -> dict:
    """asdict(Effect) → preview 가 기대하는 payload shape.

    zoom: ZoomPoint 의 cx/cy 키를 x/y 로 매핑. arrow.Point 는 이미 x/y 라 변환 없음.
    caption: 그대로.
    """
    if eff_type == "zoom":
        out = dict(payload)
        for k in ("start", "end"):
            pt = payload.get(k)
            if isinstance(pt, dict):
                out[k] = {
                    "x": pt.get("x", pt.get("cx", 0.5)),
                    "y": pt.get("y", pt.get("cy", 0.5)),
                    "scale": pt.get("scale", 1.0),
                }
        return out
    return payload


# 한글 폰트 lookup — Windows 기본 폰트들 우선. 못 찾으면 PIL 기본(라틴만) fallback.
_KOREAN_FONT_CANDIDATES = (
    "C:/Windows/Fonts/malgun.ttf",         # 맑은 고딕 (Windows 기본)
    "C:/Windows/Fonts/malgunbd.ttf",       # 맑은 고딕 Bold
    "C:/Windows/Fonts/gulim.ttc",          # 굴림
    "C:/Windows/Fonts/NanumGothic.ttf",    # 나눔고딕 (선택 설치)
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)


def _load_korean_font(size: int):
    """한글 렌더 가능한 truetype 폰트 로드. 못 찾으면 None (호출자가 default 사용)."""
    from PIL import ImageFont
    import os
    for path in _KOREAN_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return None


def _render_proposal_on_image(img, eff_type: str, payload: dict):
    """img 위에 효과 type 에 맞는 시각 변형/overlay 적용해 새 이미지 반환.

    PIL Image 객체 in/out. payload 는 propose_effect 에서 검증된 정규화 좌표 가정.
    """
    from PIL import Image, ImageDraw

    W, H = img.size

    if eff_type == "zoom":
        # zoom 의 *최종* (end) 시점을 미리보기 — 가장 변형 큰 순간. 보간 중간 시점은
        # 사용자가 'ms' 인자로 다른 시점을 골라 여러 번 호출 가능.
        end = payload.get("end") or {}
        cx = float(end.get("x", 0.5))
        cy = float(end.get("y", 0.5))
        scale = float(end.get("scale", 1.0))
        if scale <= 1.0:
            return img
        crop_w = W / scale
        crop_h = H / scale
        cx_px = cx * W
        cy_px = cy * H
        left = max(0.0, min(W - crop_w, cx_px - crop_w / 2))
        top = max(0.0, min(H - crop_h, cy_px - crop_h / 2))
        cropped = img.crop((int(left), int(top), int(left + crop_w), int(top + crop_h)))
        return cropped.resize((W, H), Image.LANCZOS)

    if eff_type == "arrow":
        start = payload.get("start") or {}
        end = payload.get("end") or {}
        sx = float(start.get("x", 0.3)) * W
        sy = float(start.get("y", 0.5)) * H
        ex = float(end.get("x", 0.7)) * W
        ey = float(end.get("y", 0.5)) * H
        color = str(payload.get("color", "#ff4040"))
        # thickness 는 source 픽셀 단위 — preview width 에 비례 스케일.
        # 1920 원본 기준 6px → width=640 기준 약 2px.
        raw_thickness = int(payload.get("thickness", 6))
        thickness = max(2, raw_thickness * W // 1920)

        draw = ImageDraw.Draw(img)
        draw.line([(sx, sy), (ex, ey)], fill=color, width=thickness)

        # arrowhead — 단순 이등변 삼각형.
        dx = ex - sx
        dy = ey - sy
        length = max(1.0, math.hypot(dx, dy))
        ux, uy = dx / length, dy / length
        ah = max(8, thickness * 3)
        # perpendicular.
        px, py = -uy, ux
        base_x = ex - ux * ah
        base_y = ey - uy * ah
        wing = ah * 0.55
        p1 = (base_x + px * wing, base_y + py * wing)
        p2 = (base_x - px * wing, base_y - py * wing)
        draw.polygon([(ex, ey), p1, p2], fill=color)
        return img

    if eff_type == "caption":
        text = str(payload.get("text", "")) or "(빈 caption)"
        draw = ImageDraw.Draw(img)
        # 한글 truetype 폰트 우선 — 없으면 PIL default (라틴만 지원, 한글 □□□).
        # 폰트 크기는 이미지 높이의 ~5% 정도.
        font_size = max(14, H // 18)
        font = _load_korean_font(font_size)
        if font is None:
            from PIL import ImageFont
            font = ImageFont.load_default()

        # 텍스트 박스 측정.
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw = len(text) * 8
            th = 16

        x = (W - tw) // 2
        y = H - th - max(20, H // 10)
        pad = 6
        draw.rectangle(
            [x - pad, y - pad, x + tw + pad, y + th + pad],
            fill=(0, 0, 0),
            outline=(255, 255, 255),
        )
        draw.text((x, y), text, fill=(255, 255, 255), font=font)
        return img

    # 도달 안 함 — _PREVIEWABLE_TYPES 로 사전 차단.
    return img
