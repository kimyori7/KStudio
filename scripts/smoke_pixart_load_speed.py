"""PixArt-Sigma 로드 시간 분해 측정 — ComfyUI 와의 차이 진단.

사용자 보고 2026-05-27: "comfyui 보면 모델 올리는건 순식간"

측정 단계:
A. import 시간 — torch / diffusers / transformers / accelerate
B. from_pretrained — 디스크 → CPU 메모리 (각 component 별)
C. enable_model_cpu_offload — accelerate hook 등록
D. 첫 generate 의 step 1 도착까지 (JIT + T5 swap + DiT swap)
E. 두 번째 generate 첫 step (warm)

실행:
  .venv/Scripts/python scripts/smoke_pixart_load_speed.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.WARNING,   # 디스크 fetch 로그 줄이기
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

REPO = "PixArt-alpha/PixArt-Sigma-XL-2-1024-MS"


def section(title: str) -> None:
    print(f"\n{'='*72}\n{title}\n{'='*72}")


def main() -> int:
    section("PixArt-Sigma 로드 시간 분해")

    # ---- A: import ----
    print("\n[A] 무거운 import 시간")
    t0 = time.time()
    import torch
    print(f"   torch                   : {time.time()-t0:.2f}초")
    t0 = time.time()
    import diffusers  # noqa
    print(f"   diffusers               : {time.time()-t0:.2f}초")
    t0 = time.time()
    import transformers  # noqa
    print(f"   transformers            : {time.time()-t0:.2f}초")
    t0 = time.time()
    import accelerate  # noqa
    print(f"   accelerate              : {time.time()-t0:.2f}초")
    print(f"   CUDA available          : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        free, tot = torch.cuda.mem_get_info()
        print(f"   VRAM 시작 (가용/전체)  : {free/1e9:.1f} / {tot/1e9:.1f} GB")

    # ---- B: from_pretrained ----
    section("[B] from_pretrained 디스크 → CPU 메모리")
    from diffusers import PixArtSigmaPipeline
    t0 = time.time()
    pipe = PixArtSigmaPipeline.from_pretrained(REPO, torch_dtype=torch.bfloat16)
    print(f"   PixArtSigmaPipeline.from_pretrained: {time.time()-t0:.2f}초")
    if torch.cuda.is_available():
        free, tot = torch.cuda.mem_get_info()
        print(f"   VRAM (CPU 상태)          : 사용 {(tot-free)/1e9:.1f} GB")

    # ---- C: enable_model_cpu_offload ----
    section("[C] enable_model_cpu_offload — accelerate hook 등록")
    t0 = time.time()
    pipe.enable_model_cpu_offload()
    print(f"   enable_model_cpu_offload : {time.time()-t0:.2f}초")
    if torch.cuda.is_available():
        free, tot = torch.cuda.mem_get_info()
        print(f"   VRAM 후                 : 사용 {(tot-free)/1e9:.2f} GB")

    # ---- D: 첫 generate — step 1 까지 시간 측정 ----
    section("[D] 첫 generate: step 1 도달 시간 + 전체 시간")
    step1_at = [0.0]
    gen_start = [0.0]

    def _cb_first(pipe_obj, step_idx, _ts, ckw):
        if step_idx == 0:
            step1_at[0] = time.time() - gen_start[0]
        return ckw

    gen_start[0] = time.time()
    pipe(
        prompt="a calico cat",
        height=512, width=512,
        num_inference_steps=4,    # 빠른 측정용
        guidance_scale=4.5,
        callback_on_step_end=_cb_first,
    )
    total1 = time.time() - gen_start[0]
    print(f"   step 1 까지              : {step1_at[0]:.2f}초")
    print(f"   전체 (4-step + decode)   : {total1:.2f}초")
    if torch.cuda.is_available():
        free, tot = torch.cuda.mem_get_info()
        print(f"   VRAM 피크 (generate 직후): 사용 {(tot-free)/1e9:.2f} GB")

    # ---- E: 두 번째 generate — warm ----
    section("[E] 두 번째 generate (warm) — pipeline 재사용")
    step1_at[0] = 0.0
    gen_start[0] = time.time()
    pipe(
        prompt="a dog",
        height=512, width=512,
        num_inference_steps=4,
        guidance_scale=4.5,
        callback_on_step_end=_cb_first,
    )
    total2 = time.time() - gen_start[0]
    print(f"   step 1 까지              : {step1_at[0]:.2f}초")
    print(f"   전체 (4-step + decode)   : {total2:.2f}초")

    section("정리 + 분석")
    print(f"첫 generate step1 도달    : {step1_at[0]:.2f}초 (이게 ComfyUI 와 비교할 핵심 지표)")
    print(f"두 번째 step1 도달         : {step1_at[0]:.2f}초 (warm 인지 확인)")
    print()
    print("ComfyUI 가 '순식간' 인 이유:")
    print("- ComfyUI 의 'Smart Memory': 모델을 GPU 에 상주, swap 없음")
    print("- enable_model_cpu_offload: 매 generate 첫 step 직전 weights swap → 매번 추가")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.exception("smoke failed")
        sys.exit(1)
