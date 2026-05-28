"""Qwen3-VL-4B 실제 generate 속도 측정 — TransformersBackend 직접 호출.

KStudio GUI 거치지 않고 백엔드 클래스 그대로 사용 → 실 환경에서 보이는 tok/s 측정.
사용자 보고 "대답 너무 느림" 진단용 (2026-05-26).

실행:
  .venv/Scripts/python scripts/smoke_qwen3_vl_4b_speed.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

# Windows cp949 콘솔 → 이모지 인코딩 실패 회피.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# KStudio src 경로 추가.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 콘솔에 INFO 로그 보이게 (TransformersBackend 의 device_map / tok/s 로그 확인용).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from screen_recorder.agent.backends.transformers_backend import TransformersBackend
from screen_recorder.agent.backends import ChatInput, AgentMessage, AgentEvent


async def main() -> int:
    print("=" * 70)
    print("Qwen3-VL-4B 속도 smoke test")
    print("=" * 70)

    # ---- 환경 확인 ----
    import torch
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA   : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        free, tot = torch.cuda.mem_get_info()
        print(f"GPU    : {torch.cuda.get_device_name(0)}")
        print(f"VRAM   : free={free/1e9:.1f}GB total={tot/1e9:.1f}GB")
    print()

    # ---- Backend 초기화 ----
    be = TransformersBackend(
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        modalities=frozenset({"text", "image", "video"}),
    )
    await be.start_session(system_prompt="sys", tools={}, model="qwen3-vl-4b-instruct")
    print(f"[1/3] Backend 초기화 OK ({be._repo_id})")
    print()

    # ---- 모델 로드 (cold) ----
    def _emit(item):
        if isinstance(item, AgentMessage) and item.role == "system":
            print(f"  [system] {item.text}")

    t0 = time.time()
    print("[2/3] 모델 로딩 중...")
    await be._ensure_model_loaded(emit_fn=_emit)
    load_elapsed = time.time() - t0
    print(f"[2/3] 모델 로드 완료 ({load_elapsed:.1f}초)")

    # 로드 후 VRAM 사용량.
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        free, tot = torch.cuda.mem_get_info()
        used = (tot - free) / 1e9
        print(f"      로드 후 VRAM 사용: {used:.1f}GB / {tot/1e9:.1f}GB")
    print()

    # ---- generate (warm-up 짧게 + 본 측정) ----
    print("[3/3] 짧은 warm-up...")
    received: list = []
    await be.send_message(ChatInput(text="안녕"), received.append)
    print(f"      warm-up 완료")
    print()

    print("[3/3] 본 측정 — '한국어로 자기소개 500자 이내'")
    received2: list = []
    t_gen0 = time.time()
    await be.send_message(
        ChatInput(text="한국어로 자기소개를 500자 이내로 해줘."),
        received2.append,
    )
    gen_elapsed = time.time() - t_gen0

    # assistant 메시지만 합쳐서 출력.
    asst_text = "".join(
        m.text for m in received2
        if isinstance(m, AgentMessage) and m.role == "assistant"
    )
    n_chars = len(asst_text)
    print()
    print("=" * 70)
    print("결과")
    print("=" * 70)
    print(f"generate 시간: {gen_elapsed:.1f}초")
    print(f"응답 길이    : {n_chars} 문자")
    if gen_elapsed > 0 and n_chars > 0:
        print(f"속도         : {n_chars / gen_elapsed:.1f} char/s (≈ {(n_chars/2.5) / gen_elapsed:.1f} tok/s 추정 — 한글 1token≈2.5char)")
    print()
    print("응답 (처음 300자):")
    print("-" * 70)
    print(asst_text[:300])
    print("-" * 70)

    # ---- 정리 ----
    await be.close()
    print()
    print("close() 후 VRAM:")
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        free, tot = torch.cuda.mem_get_info()
        print(f"  free={free/1e9:.1f}GB ({(tot-free)/1e9:.1f}GB 점유)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
