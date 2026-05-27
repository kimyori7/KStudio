"""한국어 프롬프트 → 영어 자동 번역.

기본 백엔드: **Qwen3-VL-2B-Instruct** (로컬, transformers) — instruction-following 으로
시각 디테일 보존 정확도가 NLLB 보다 훨씬 높음.

배경 (2026-05-27 품질 체크):
- NLLB-200 distilled-600M 21개 케이스 → 64% 정확도. "노을" 누락, "눈(snow) → 눈(eye)"
  혼동, "지브리 → Hebrides 섬", "광각 렌즈 → reflective lens", "떡볶이 → asshole"
  같은 환각이 빈번. PixArt 프롬프트 흐름에 사용 불가.
- Qwen3-VL 2B 는 instruction-tuned 라 system prompt 로 "시각 디테일 보존" 강제 가능 +
  한국어 능력이 distilled 번역 모델보다 훨씬 강함 (사용자 환경에 이미 캐시됨).

Fallback:
- NLLB-200 distilled-600M (가벼움, 빠름, 품질 낮음)
- Claude Haiku 정액제 (인터넷, 매 호출 25~50초 subprocess 오버헤드)

PixArt-Sigma / FLUX / SDXL 등 디퓨전 모델은 학습 데이터의 비중이 99% 영어라 한국어
프롬프트 결과가 부정확함 (사용자 보고: "고양이라고 했는데 사람이 나옴").
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

_log = logging.getLogger(__name__)


_HANGUL_RE = re.compile(r"[가-힣]")
_NLLB_REPO = "facebook/nllb-200-distilled-600M"
_QWEN_REPO = "Qwen/Qwen3-VL-2B-Instruct"


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
    """NLLB-200 distilled-600M 로 한→영 번역. ~0.5초/번역 (warm).

    튜닝 (2026-05-27): 사용자 보고 "노을이 비치는 땅 → nook 어쩌고" — distilled-600M
    가 짧고 시각적 디테일 (노을, 빛, 분위기) 을 자주 누락하거나 음역 (예: 노을 →
    nook) 으로 망가뜨림. 다음으로 일부 완화:
    - num_beams 4 → 8: beam 폭 늘리면 model 이 더 자연스러운 path 발견.
    - length_penalty=1.2: 짧은 출력 페널티 — 디테일 단어 살릴 가능성 ↑.
    - no_repeat_ngram_size=3: 같은 3-gram 반복 방지 (NLLB 가 종종 "the the the" 식 반복).
    - early_stopping=True: 모든 beam 이 EOS 에 도달하면 즉시 종료 (속도 영향 미미).
    근본 해결은 NLLB-200-1.3B 또는 -3.3B 로 업그레이드 (~5~13GB 추가 다운로드).
    """
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
                num_beams=8,
                length_penalty=1.2,
                no_repeat_ngram_size=3,
                early_stopping=True,
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


# ============================================================================
# Qwen3-VL-2B-Instruct backend — 사용자 환경에 캐시된 instruction-following 모델.
# ============================================================================
_QWEN_SYSTEM_PROMPT = (
    "You are a strict Korean→English translator for image generation prompts.\n"
    "RULES (follow exactly):\n"
    "- Output ONE concise English line. NO elaboration. NO extra sentences.\n"
    "- Translate ONLY what is in the source. Do NOT invent subjects, scenes, or atmosphere.\n"
    "- Preserve every visual detail present: lighting (노을→sunset, 달빛→moonlight), "
    "mood, style, composition, camera angle.\n"
    "- Resolve homonyms by context: 눈+달리다→snow (not eye).\n"
    "- Cultural nouns stay: 한복→hanbok, 떡볶이→tteokbokki, 지브리→Studio Ghibli, 벚꽃→cherry blossom.\n"
    "- No preamble, no quotes, no markdown, no explanation.\n"
    "- Max 40 words.\n"
    "\n"
    "Examples:\n"
    "Korean: 노을이 비치는 창가의 삼색 고양이\n"
    "English: A calico cat by a sunset-lit window\n"
    "Korean: 김이 모락모락 나는 떡볶이\n"
    "English: Steaming hot tteokbokki\n"
    "Korean: 눈 위를 달리는 늑대\n"
    "English: A wolf running across snow"
)

_qwen_pipeline = None   # (processor, model, device)


def _ensure_qwen_loaded():
    """Qwen3-VL-2B 를 lazy 로드. ~4GB VRAM (bf16). 두 번째 호출부터 즉시 반환."""
    global _qwen_pipeline
    if _qwen_pipeline is not None:
        return _qwen_pipeline
    import torch
    from transformers import AutoProcessor

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    _log.info("Loading Qwen3-VL translator (%s, device=%s) — cold load 5~15초",
              _QWEN_REPO, device)
    # GPU bf16 (sm_120 지원), CPU 는 float32.
    dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32

    # Qwen3-VL 은 transformers 4.46+ 에서 Qwen2VLForConditionalGeneration 클래스 사용
    # (Qwen3 도 동일한 아키텍처 패밀리). 정확한 클래스명은 config 기반 AutoModel 로.
    from transformers import AutoModelForImageTextToText
    processor = AutoProcessor.from_pretrained(_QWEN_REPO)
    model = AutoModelForImageTextToText.from_pretrained(
        _QWEN_REPO,
        torch_dtype=dtype,
    )
    model = model.to(device)
    model.eval()
    _qwen_pipeline = (processor, model, device)
    return _qwen_pipeline


def _translate_via_qwen(prompt: str) -> Optional[str]:
    """Qwen3-VL-2B 로 한→영 번역. text-only 사용 (vision 토큰 없음)."""
    import torch
    processor, model, device = _ensure_qwen_loaded()
    try:
        messages = [
            {"role": "system", "content": [{"type": "text", "text": _QWEN_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ]
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = processor(text=[text], return_tensors="pt").to(device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                # 80 = 영문 ~40 단어 + 안전 마진. PixArt T5 한도 (~120 토큰) 안에 들어옴
                # + Qwen elaboration 차단. 사용자 결정 2026-05-27 "억제".
                max_new_tokens=80,
                do_sample=False,
                # greedy — translation 에선 deterministic 가 안전.
            )
        # 입력 토큰 부분을 잘라내 새로 생성된 부분만 추출.
        input_len = inputs.input_ids.shape[1]
        generated_ids = output_ids[:, input_len:]
        out = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
        # Qwen 가 종종 quote / "Translation: " prefix 붙일 때 청소.
        for prefix in ("Translation:", "English:", "English Translation:", "번역:"):
            if out.startswith(prefix):
                out = out[len(prefix):].strip()
        if (out.startswith('"') and out.endswith('"')) or (
            out.startswith("'") and out.endswith("'")
        ):
            out = out[1:-1].strip()
        return out or None
    except Exception:
        _log.exception("Qwen3-VL translation failed")
        return None


def unload_qwen() -> None:
    """KStudio 종료 / 메모리 회수 시 호출. 다음 번역 호출이 다시 로드."""
    global _qwen_pipeline
    if _qwen_pipeline is None:
        return
    _qwen_pipeline = None
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
    backend: str = "qwen",
    claude_model: str = "claude-haiku-4-5-20251001",
) -> Optional[str]:
    """sync wrapper — worker thread (QThread) 안에서 호출.

    backend:
    - "qwen"   (기본): Qwen3-VL-2B-Instruct 로컬. ~4GB VRAM bf16. 첫 호출 5~15초,
               이후 ~1~2초. instruction-following 으로 시각 디테일 보존 우수.
    - "nllb"  : NLLB-200 distilled-600M. 가볍지만 디테일 누락/환각 많음 (~64% 정확도).
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
        elif backend == "nllb":
            result = _translate_via_nllb(prompt)
        else:   # "qwen" (기본)
            result = _translate_via_qwen(prompt)
        if result:
            _translation_cache[prompt] = result
        return result
    except Exception:
        _log.exception("Korean→English translation failed (backend=%s) — fallback", backend)
        return None
