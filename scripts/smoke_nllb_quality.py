"""한→영 번역 백엔드 품질 비교 — Qwen3-VL 2B vs NLLB-200 distilled-600M.

사용자 보고 2026-05-27:
- NLLB-600M 21개 케이스 → 64% 정확도. "노을"/"눈"/"지브리"/"광각" 디테일 누락/환각.
- Qwen3-VL 2B (instruction-tuned) 가 시각 디테일 보존 + 고유명사 처리 더 나을 것
  으로 기대 (system prompt 로 규칙 강제 가능).

실행:
  .venv/Scripts/python scripts/smoke_nllb_quality.py            # 기본 = qwen + nllb 비교
  .venv/Scripts/python scripts/smoke_nllb_quality.py qwen       # qwen 만
  .venv/Scripts/python scripts/smoke_nllb_quality.py nllb       # nllb 만
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
    translate_to_english_sync, clear_translation_cache,
    unload_nllb, unload_qwen,
)


# 카테고리, 한국어 프롬프트, 기대치 (살아있어야 하는 핵심 영어 단어).
CASES: list[tuple[str, str, list[str]]] = [
    # 1. 빛 / 시간대 — 가장 잘 망가지는 카테고리.
    ("빛/시간", "노을이 비치는 창가의 삼색 고양이",
     ["sunset", "calico", "cat", "window"]),
    ("빛/시간", "노을이 비치는 땅",
     ["sunset", "land"]),
    ("빛/시간", "아침 햇살이 들어오는 부엌",
     ["morning", "sunlight", "kitchen"]),
    ("빛/시간", "달빛 아래 호숫가",
     ["moonlight", "lake"]),
    ("빛/시간", "안개 낀 새벽 숲",
     ["fog", "dawn", "forest"]),

    # 2. 날씨 / 분위기
    ("날씨", "비 오는 도시의 네온사인, 사이버펑크 분위기",
     ["rain", "city", "neon", "cyberpunk"]),
    ("날씨", "눈 내리는 산골 마을",
     ["snow", "mountain", "village"]),
    ("날씨", "폭풍이 몰아치는 바다",
     ["storm", "sea"]),

    # 3. 인물
    ("인물", "한복을 입은 젊은 여성의 초상화",
     ["hanbok", "young", "woman", "portrait"]),
    ("인물", "검을 든 사무라이, 영화 같은 클로즈업",
     ["sword", "samurai", "cinematic", "close-up"]),

    # 4. 동물
    ("동물", "눈 위를 달리는 늑대",
     ["wolf", "snow", "running"]),
    ("동물", "벚꽃 아래 사슴 한 마리",
     ["cherry blossom", "deer"]),

    # 5. 스타일 / 화풍
    ("스타일", "수채화 풍의 정원",
     ["watercolor", "garden"]),
    ("스타일", "지브리 스튜디오 풍의 시골 풍경",
     ["ghibli", "countryside"]),
    ("스타일", "8-bit 픽셀 아트 게임 캐릭터",
     ["pixel art", "character"]),

    # 6. 구도 / 카메라
    ("구도", "로우앵글로 본 도시 야경",
     ["low angle", "city", "night"]),
    ("구도", "광각 렌즈로 찍은 사막 풍경",
     ["wide", "lens", "desert"]),

    # 7. 음식
    ("음식", "김이 모락모락 나는 떡볶이",
     ["tteokbokki", "steam"]),
    ("음식", "딸기 케이크와 따뜻한 커피",
     ["strawberry cake", "coffee"]),

    # 8. 추상 / 형용사 부담
    ("추상", "사실적이고 영화 같은 미래 도시",
     ["photorealistic", "cinematic", "future", "city"]),
    ("추상", "꿈처럼 몽환적인 보라색 안개",
     ["dreamlike", "purple", "mist"]),
]


def score(text: str, expected: list[str]) -> tuple[int, int, list[str]]:
    """기대 단어 몇 개 살아남았나. 대소문자 무시, 부분 일치."""
    low = text.lower()
    hit = []
    miss = []
    for w in expected:
        if w.lower() in low:
            hit.append(w)
        else:
            miss.append(w)
    return len(hit), len(expected), miss


def run_backend(backend: str) -> tuple[int, int, float, list[tuple[str, str, str, list[str]]]]:
    """한 backend 로 전체 케이스 돌려 점수 반환."""
    print()
    print("=" * 80)
    print(f"  Backend: {backend.upper()}")
    print("=" * 80)

    clear_translation_cache()
    unload_qwen()
    unload_nllb()

    by_cat: dict[str, list[tuple[int, int]]] = {}
    overall_hit = 0
    overall_total = 0
    fail_list: list[tuple[str, str, str, list[str]]] = []   # 누락 단어 ≥2개

    t_start = time.time()
    for i, (cat, ko, expected) in enumerate(CASES, 1):
        t0 = time.time()
        en = translate_to_english_sync(ko, backend=backend)
        dt = time.time() - t0
        en = en or "(번역 실패)"
        hit, total, miss = score(en, expected)
        by_cat.setdefault(cat, []).append((hit, total))
        overall_hit += hit
        overall_total += total
        marker = "✓" if hit == total else ("~" if hit >= total // 2 else "✗")
        print(f"[{i:2d}/{len(CASES)}] {marker} [{cat}] ({dt:5.2f}s) "
              f"{hit}/{total} 단어")
        print(f"      한국어: {ko}")
        print(f"      영  어: {en}")
        if miss:
            print(f"      누락: {', '.join(miss)}")
            if len(miss) >= 2:
                fail_list.append((cat, ko, en, miss))

    t_total = time.time() - t_start
    print()
    print(f"총 소요: {t_total:.1f}초")
    print()
    print(f"카테고리별 점수 ({backend}):")
    for cat, scores_list in by_cat.items():
        h = sum(x for x, _ in scores_list)
        t = sum(y for _, y in scores_list)
        pct = (h / t * 100) if t else 0
        print(f"  {cat:8s}: {h:2d}/{t:2d} ({pct:.0f}%)")
    overall_pct = (overall_hit / overall_total * 100) if overall_total else 0
    print(f"  전체   : {overall_hit}/{overall_total} ({overall_pct:.0f}%)")

    if fail_list:
        print()
        print(f"🚨 심각한 누락 — {backend} (≥2 단어 빠진 케이스):")
        for cat, ko, en, miss in fail_list:
            print(f"  - [{cat}] '{ko}'")
            print(f"      → '{en}'")
            print(f"      누락: {', '.join(miss)}")

    return overall_hit, overall_total, t_total, fail_list


def main() -> int:
    print("=" * 80)
    print("한→영 번역 백엔드 품질 비교")
    print("=" * 80)
    print(f"테스트 케이스: {len(CASES)}개")

    if len(sys.argv) > 1 and sys.argv[1] in ("qwen", "nllb", "claude"):
        backends = [sys.argv[1]]
    else:
        backends = ["qwen", "nllb"]

    results: dict[str, tuple[int, int, float]] = {}
    for be in backends:
        hit, total, dt, _fail = run_backend(be)
        results[be] = (hit, total, dt)

    if len(results) > 1:
        print()
        print("=" * 80)
        print("📊 비교 요약")
        print("=" * 80)
        print(f"{'backend':<10} {'정확도':<15} {'총시간':<10}")
        print("-" * 40)
        for be, (h, t, dt) in results.items():
            pct = (h / t * 100) if t else 0
            print(f"{be:<10} {h:>2}/{t} ({pct:.0f}%)      {dt:.1f}s")
        print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
