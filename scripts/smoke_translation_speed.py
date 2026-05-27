"""번역 시간 직접 측정 — Claude Haiku 정액제 호출 latency 분리 진단.

사용자 보고 2026-05-27: "번역이 또 왤케 오래걸려 ㅋㅋ"

측정:
1. Cold (첫 호출) — Claude CLI subprocess spawn + TLS handshake + Haiku 응답
2. Warm-2 (두 번째, 다른 prompt) — subprocess 재 spawn (asyncio.run 가 매번 새 loop)
3. Cache hit (같은 prompt) — 0 초 기대

실행:
  .venv/Scripts/python scripts/smoke_translation_speed.py
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
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from screen_recorder.image_gen.translator import (
    translate_to_english_sync, clear_translation_cache,
)


def main() -> int:
    print("=" * 72)
    print("Translation latency smoke — Claude Haiku 정액제")
    print("=" * 72)

    clear_translation_cache()

    prompts = [
        "노을이 비치는 창가의 삼색 고양이",
        "비 오는 도시의 네온사인, 사이버펑크 분위기",
        "노을이 비치는 창가의 삼색 고양이",  # 캐시 hit
    ]

    for i, p in enumerate(prompts, 1):
        t0 = time.time()
        result = translate_to_english_sync(p)
        dt = time.time() - t0
        print(f"\n[{i}/{len(prompts)}] prompt: {p[:50]}")
        print(f"   elapsed: {dt:.2f}초")
        print(f"   result : {result}")

    print()
    print("=" * 72)
    print("분석:")
    print("- [1] = cold subprocess + TLS + Haiku 응답 (보통 5~10초 추정)")
    print("- [2] = asyncio.run 새 loop + 새 subprocess (cold 와 비슷할 것)")
    print("- [3] = 메모리 캐시 hit (0초 기대)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
