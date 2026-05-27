"""NLLB-200 distilled-600M 실측 — Claude 대비 얼마나 빠른지 검증.

사용자 결정 2026-05-27: Claude SDK (25~50초/번역) → NLLB-200 (로컬, ~0.5초 기대).

측정:
1. Cold (첫 호출) — 모델 다운로드 + 로드 + 첫 번역
2. Warm-2 (두 번째, 다른 prompt) — 캐시는 없지만 모델은 메모리 상주
3. Cache hit (같은 prompt) — 0초 기대

실행:
  .venv/Scripts/python scripts/smoke_nllb_translation.py
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from screen_recorder.image_gen.translator import (
    translate_to_english_sync, clear_translation_cache, unload_nllb,
)


def main() -> int:
    print("=" * 72)
    print("NLLB-200 distilled-600M latency smoke (backend='nllb')")
    print("=" * 72)

    clear_translation_cache()
    unload_nllb()   # 정확한 cold 측정.

    prompts = [
        "노을이 비치는 창가의 삼색 고양이",
        "비 오는 도시의 네온사인, 사이버펑크 분위기",
        "노을이 비치는 창가의 삼색 고양이",  # 캐시 hit
    ]

    for i, p in enumerate(prompts, 1):
        t0 = time.time()
        result = translate_to_english_sync(p, backend="nllb")
        dt = time.time() - t0
        print(f"\n[{i}/{len(prompts)}] prompt: {p[:50]}")
        print(f"   elapsed: {dt:.2f}초")
        print(f"   result : {result}")

    print()
    print("=" * 72)
    print("분석:")
    print("- [1] = 모델 다운로드/로드 + 첫 번역 (cold)")
    print("- [2] = 모델 메모리 상주 후 두 번째 번역 (warm)")
    print("- [3] = 메모리 캐시 hit (0초)")
    print()
    print("Claude SDK 대비:")
    print("  Claude: 48.4초 + 24.5초 = 73초 (두 번)")
    print("  NLLB  : 위 결과로 비교")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
