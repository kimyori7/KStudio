"""preview_proposal 도구 — apply 전 효과 결과 미리보기.

ffmpeg subprocess 의존을 피하려고 PIL 변환 함수 `_render_proposal_on_image` 를 직접
호출하는 단위 테스트 중심. 전체 흐름은 정상화 좌표 → PIL 변환 → 픽셀 검증.

Claude 의 자기 검증 워크플로우 (propose → preview → modify → apply) 가 가능한지가 핵심.
"""
from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from screen_recorder.agent.proposals import EffectProposal, ProposalQueue
from screen_recorder.agent.tools.preview import (
    PREVIEW_TOOL_NAMES, _render_proposal_on_image, make_preview_tools,
)


def _solid_image(w: int = 640, h: int = 360, color=(50, 80, 120)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


# ============================================================
# Zoom 미리보기 — crop + resize.
# ============================================================
def test_zoom_preview_scale_1_returns_original() -> None:
    """scale=1 이면 crop 의미 없음 — 원본 그대로 반환."""
    img = _solid_image()
    out = _render_proposal_on_image(img, "zoom", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end":   {"x": 0.5, "y": 0.5, "scale": 1.0},
    })
    assert out.size == img.size


def test_zoom_preview_2x_returns_resized_to_original() -> None:
    """scale=2 면 crop 후 다시 W,H 로 resize — 사이즈는 원본 유지."""
    img = _solid_image(640, 360)
    out = _render_proposal_on_image(img, "zoom", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end":   {"x": 0.5, "y": 0.5, "scale": 2.0},
    })
    assert out.size == (640, 360)


def test_zoom_preview_off_center_does_not_overflow() -> None:
    """corner 근처(0,0)에 중심 두고 scale=4 — crop 영역이 음수로 안 가야."""
    img = _solid_image(640, 360)
    # 좌상단 모서리에서 4배 줌. crop 영역을 frame 안쪽으로 clamp.
    out = _render_proposal_on_image(img, "zoom", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.0, "y": 0.0, "scale": 4.0},
        "end":   {"x": 0.0, "y": 0.0, "scale": 4.0},
    })
    assert out.size == (640, 360)
    # 픽셀 값이 모두 유효 (검정/오버플로 없음) — 단순 solid 라 그대로 색.


# ============================================================
# Arrow 미리보기 — 선 + 화살촉이 그려져 픽셀 변경.
# ============================================================
def test_arrow_preview_modifies_pixels() -> None:
    """화살표가 그려지면 픽셀 값이 변함 (배경 색 그대로가 아님)."""
    bg_color = (50, 80, 120)
    img = _solid_image(640, 360, bg_color)
    out = _render_proposal_on_image(img, "arrow", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.2, "y": 0.5},
        "end":   {"x": 0.8, "y": 0.5},
        "color": "#ff4040",
        "thickness": 12,
    })
    # 화살표 중간 (가로 0.5, 세로 0.5) 픽셀이 빨간색 계열이어야.
    px = out.getpixel((320, 180))
    assert px != bg_color, "화살표 자리에 픽셀 변화 없음 — 그려지지 않은 듯"
    # 빨간 채널이 다른 채널보다 큼 (대략적 red dominance).
    r, g, b = px[:3]
    assert r > g and r > b


def test_arrow_preview_arrowhead_at_end() -> None:
    """화살촉이 end 좌표 근처에 — end 픽셀이 색칠된 영역."""
    img = _solid_image(640, 360)
    out = _render_proposal_on_image(img, "arrow", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.1, "y": 0.5},
        "end":   {"x": 0.9, "y": 0.5},
        "color": "#ff0000",
        "thickness": 20,
    })
    # end 픽셀 (0.9*640=576, 0.5*360=180).
    px = out.getpixel((576, 180))
    r, g, b = px[:3]
    assert r > 200, f"end 좌표가 안 칠해짐, px={px}"


# ============================================================
# Caption 미리보기 — 텍스트 박스가 그려짐.
# ============================================================
def test_caption_preview_renders_text_box() -> None:
    """caption 텍스트 박스가 하단 영역에 — 그 부분 픽셀이 검정 배경."""
    img = _solid_image(640, 360, (100, 100, 100))   # 회색 배경.
    out = _render_proposal_on_image(img, "caption", {
        "in_ms": 0, "out_ms": 1000,
        "text": "Hello world",
    })
    # 하단 중앙쯤 검정 박스 안 픽셀.
    # padding 6, 박스 영역 대략 W/2 - 50 ~ W/2 + 50, H - 50 부근.
    px = out.getpixel((320, 320))
    # 박스 안은 검정 (0,0,0) 또는 흰색 텍스트.
    r, g, b = px[:3]
    # 회색 배경과 충분히 다름 (배경 = 100,100,100, 박스 = 검정/흰색).
    assert (r < 50 and g < 50 and b < 50) or (r > 200 and g > 200 and b > 200), \
        f"caption 박스 안 픽셀이 배경 색 — 안 그려진 듯, px={px}"


# ============================================================
# 도구 surface — 큐 조회 + 에러 패스.
# ============================================================
class _FakeAdapter:
    def __init__(self, src=None, dur=10000):
        self._src = src
        self._dur = dur
    def has_active_video(self) -> bool:
        return self._src is not None
    def source_path(self):
        return self._src
    def duration_ms(self) -> int:
        return self._dur
    def position_ms(self) -> int:
        return 0
    def sidecar(self):
        return None


def test_preview_tool_names_constant() -> None:
    assert PREVIEW_TOOL_NAMES == ("preview_proposal",)


def _invoke(tool_obj, args: dict) -> dict:
    """SDK @tool 데코레이터가 만든 객체의 handler 를 동기적으로 호출."""
    # claude_agent_sdk @tool 데코레이터는 SdkMcpTool 같은 객체로 감쌈 — handler 속성 또는
    # __call__ 로 접근 가능. 일단 handler 우선, 없으면 callable 자체.
    handler = getattr(tool_obj, "handler", None) or tool_obj
    return asyncio.run(handler(args))


def test_preview_rejects_when_no_active_video() -> None:
    queue = ProposalQueue()
    tools = make_preview_tools(_FakeAdapter(src=None), queue, ffmpeg_path="ffmpeg")
    assert len(tools) == 1
    result = _invoke(tools[0], {"proposal_id": "xx", "ms": 0})
    assert result.get("isError") is True


def test_preview_rejects_unknown_proposal_id() -> None:
    queue = ProposalQueue()
    queue.add(EffectProposal(action="add", type="arrow", payload={
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.3, "y": 0.5}, "end": {"x": 0.7, "y": 0.5},
    }))
    tools = make_preview_tools(_FakeAdapter(src="x.mp4"), queue, ffmpeg_path="ffmpeg")
    result = _invoke(tools[0], {"proposal_id": "prop_doesnotexist", "ms": 100})
    assert result.get("isError") is True
    txt = result["content"][0]["text"]
    assert "큐에 없음" in txt


def test_preview_rejects_unsupported_type() -> None:
    """speed / cut / broll 은 시각 미리보기 의미 없음 — 거부."""
    queue = ProposalQueue()
    queue.add(EffectProposal(
        id="prop_speed1", action="add", type="speed",
        payload={"in_ms": 0, "out_ms": 1000, "rate": 2.0},
    ))
    tools = make_preview_tools(_FakeAdapter(src="x.mp4"), queue, ffmpeg_path="ffmpeg")
    result = _invoke(tools[0], {"proposal_id": "prop_speed1", "ms": 100})
    assert result.get("isError") is True
    assert "시각 효과" in result["content"][0]["text"]


def test_preview_rejects_remove_action() -> None:
    queue = ProposalQueue()
    queue.add(EffectProposal(
        id="prop_rm1", action="remove", type="arrow",
        payload={"effect_id": "arr_xx"},
    ))
    tools = make_preview_tools(_FakeAdapter(src="x.mp4"), queue, ffmpeg_path="ffmpeg")
    result = _invoke(tools[0], {"proposal_id": "prop_rm1", "ms": 100})
    assert result.get("isError") is True
    # modify 는 이제 지원, remove 만 거부.
    assert "remove" in result["content"][0]["text"]
