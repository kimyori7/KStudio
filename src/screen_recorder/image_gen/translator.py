"""한국어 프롬프트 → 영어 자동 번역.

기본 백엔드: **NLLB-200 distilled-600M** (로컬, transformers) — ~0.5초/번역.
Fallback: Claude Haiku (정액제) — 인터넷 OK 지만 매 호출 25~50초 subprocess
오버헤드 (실측 2026-05-27).

PixArt-Sigma / FLUX / SDXL 등 디퓨전 모델은 학습 데이터의 비중이 99% 영어라 한국어
프롬프트 결과가 부정확함 (사용자 보고: "고양이라고 했는데 사람이 나옴").

해결책: 한국어 감지 → NLLB 로 영어 번역 → 영어 prompt 로 generate.
NLLB-200 = ComfyUI 커뮤니티의 prompt 번역 표준. 다국어 + 시각 디테일 보존 + transformers 호환.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

_log = logging.getLogger(__name__)


_HANGUL_RE = re.compile(r"[가-힣]")
_NLLB_REPO = "facebook/nllb-200-distilled-600M"


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


# NLLB-200 singleton — (tokenizer, model, device) tuple. 모듈 전역. 첫 호출 시
# ~5-10초 (디스크/다운로드 + bf16 변환), 후속 호출 ~0.5초. KStudio 종료까지 메모리 상주.
# transformers 의 `pipeline("translation")` 은 일부 빌드 (사용자 환경 포함) 에서 task
# registry 에 빠져있어 직접 AutoModelForSeq2SeqLM 사용 (2026-05-27).
_nllb_pipeline = None


def _ensure_nllb_loaded():
    """NLLB-200 distilled-600M 을 lazy 로드. 두 번째 호출부터 즉시 반환."""
    global _nllb_pipeline
    if _nllb_pipeline is not None:
        return _nllb_pipeline
    import torch
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    _log.info("Loading NLLB-200 translator (%s, device=%s) — cold load 5~10초",
              _NLLB_REPO, device)
    tokenizer = AutoTokenizer.from_pretrained(_NLLB_REPO, src_lang="kor_Hang")
    # GPU 면 float16, CPU 면 float32 (CPU 는 fp16 연산 미지원).
    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    model = AutoModelForSeq2SeqLM.from_pretrained(_NLLB_REPO, torch_dtype=dtype)
    model = model.to(device)
    model.eval()
    _nllb_pipeline = (tokenizer, model, device)
    return _nllb_pipeline


def _translate_via_nllb(prompt: str) -> Optional[str]:
    """NLLB-200 distilled-600M 로 한→영 번역. ~0.5초/번역 (warm)."""
    import torch
    tokenizer, model, device = _ensure_nllb_loaded()
    try:
        # src_lang 는 _ensure_nllb_loaded 에서 kor_Hang 으로 설정됨.
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=400)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        forced_bos = tokenizer.convert_tokens_to_ids("eng_Latn")
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                forced_bos_token_id=forced_bos,
                max_length=400,
                num_beams=4,
            )
        text = tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0].strip()
        return text or None
    except Exception:
        _log.exception("NLLB translation failed")
        return None


def unload_nllb() -> None:
    """KStudio 종료 / 메모리 회수 시 호출. 다음 번역 호출이 다시 로드."""
    global _nllb_pipeline
    if _nllb_pipeline is None:
        return
    _nllb_pipeline = None
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def translate_to_english_sync(
    prompt: str,
    *,
    backend: str = "nllb",
    claude_model: str = "claude-haiku-4-5-20251001",
) -> Optional[str]:
    """sync wrapper — worker thread (QThread) 안에서 호출.

    backend:
    - "nllb"   (기본): NLLB-200 distilled-600M 로컬. 첫 호출 5~10초, 이후 ~0.5초.
    - "claude": Claude Haiku 정액제. 매 호출 25~50초 (CLI subprocess spawn).

    반환:
    - 한글 없으면 None (호출자가 원본 그대로 사용)
    - 번역 성공 시 영어 문자열 (캐시 hit 시 즉시)
    - 실패 시 None — 호출자가 원본 fallback
    """
    if not has_korean(prompt):
        return None
    cached = _translation_cache.get(prompt)
    if cached is not None:
        _log.info("translation cache hit (len=%d)", len(prompt))
        return cached
    try:
        if backend == "claude":
            result = asyncio.run(_translate_via_claude(prompt, claude_model))
        else:
            result = _translate_via_nllb(prompt)
        if result:
            _translation_cache[prompt] = result
        return result
    except Exception:
        _log.exception("Korean→English translation failed (backend=%s) — fallback", backend)
        return None
