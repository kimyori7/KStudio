"""한국어 프롬프트 → 영어 자동 번역 (Claude Haiku 정액제 활용).

PixArt-Sigma / FLUX / SDXL 등 디퓨전 모델은 학습 데이터의 비중이 99% 영어라 한국어
프롬프트 결과가 부정확함 (사용자 보고 2026-05-27: "고양이라고 했는데 사람이 나옴").

해결책: 한국어 감지 → Claude Haiku 4.5 로 영어 번역 → 영어 prompt 로 generate.
KStudio 가 이미 사용자 Claude 정액제로 동작하므로 별도 API 키 / 외부 의존 없음.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

_log = logging.getLogger(__name__)


_HANGUL_RE = re.compile(r"[가-힣]")


def has_korean(text: str) -> bool:
    """한글 음절 (가~힣) 한 자라도 있으면 True."""
    return bool(_HANGUL_RE.search(text))


_TRANSLATE_SYSTEM_PROMPT = (
    "You translate Korean image-generation prompts to English for a Stable Diffusion-style "
    "model (PixArt-Sigma). Rules:\n"
    "- Output ONLY the English translation. No preamble, no quotes, no markdown.\n"
    "- Preserve every visual detail, subject, lighting, style, composition, camera angle.\n"
    "- If the input is already English, output it unchanged.\n"
    "- Use vivid, concrete adjectives (e.g. '사실적인' → 'photorealistic', "
    "'영화 같은' → 'cinematic').\n"
    "- Keep it under 200 words."
)


async def _translate_via_claude(prompt: str, model: str) -> str:
    """Claude SDK 의 query() — 한 번 묻고 끝. mcp_server 없음, 도구 호출 없음."""
    from claude_agent_sdk import (
        query, ClaudeAgentOptions,
        AssistantMessage, TextBlock,
    )

    opts = ClaudeAgentOptions(
        mcp_servers={},
        allowed_tools=[],
        env={"ANTHROPIC_API_KEY": ""},   # 정액제 강제 (KStudio 패턴)
        model=model,
        system_prompt=_TRANSLATE_SYSTEM_PROMPT,
        include_partial_messages=False,
        max_turns=1,
    )
    parts: list[str] = []
    async for sdk_msg in query(prompt=prompt, options=opts):
        if isinstance(sdk_msg, AssistantMessage):
            for block in sdk_msg.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
    out = "".join(parts).strip()
    # Claude 가 종종 quote / "Translation: " 같은 prefix 붙일 때 청소.
    for prefix in ("Translation:", "English:", "번역:"):
        if out.startswith(prefix):
            out = out[len(prefix):].strip()
    if out.startswith('"') and out.endswith('"'):
        out = out[1:-1].strip()
    return out


# 세션 내 번역 결과 캐시 — 같은 한국어 prompt 재시도 시 즉시 반환.
# 실측 (2026-05-27 사용자 보고): claude_agent_sdk.query() 는 매번 Claude CLI subprocess
# 를 새로 spawn → Node.js 시작 + TLS handshake + 인증으로 5~10초 over head. 첫 번역은
# 어쩔 수 없지만 같은 prompt 재시도 / seed 만 바꿔 재생성 같은 흐름에서 캐시 효과 큼.
# 영속 X — 메모리 dict 만. KStudio 재시작 시 비움.
_translation_cache: dict[str, str] = {}


def clear_translation_cache() -> None:
    """테스트 / 사용자 메모리 회수 용."""
    _translation_cache.clear()


def translate_to_english_sync(
    prompt: str,
    *,
    model: str = "claude-haiku-4-5-20251001",
) -> Optional[str]:
    """sync wrapper — worker thread (QThread) 안에서 호출.

    반환:
    - 한글 없으면 None (호출자가 원본 그대로 사용)
    - 번역 성공 시 영어 문자열 (캐시 hit 시 즉시)
    - Claude SDK 실패 (의존성 / 인증 / 네트워크 등) 시 None — 호출자가 원본 fallback

    첫 번역은 Claude CLI subprocess spawn + TLS handshake 로 5~10초 — 두 번째 같은
    prompt 부터는 메모리 캐시로 0초.
    """
    if not has_korean(prompt):
        return None
    cached = _translation_cache.get(prompt)
    if cached is not None:
        _log.info("translation cache hit (len=%d)", len(prompt))
        return cached
    try:
        result = asyncio.run(_translate_via_claude(prompt, model))
        if result:
            _translation_cache[prompt] = result
        return result
    except Exception:
        _log.exception("Korean→English translation failed — falling back to original prompt")
        return None
