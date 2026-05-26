"""PixArt-Sigma 1024MS 직접 로드 + 1장 생성 — Phase 1 스모크 테스트.

목적 (2026-05-26 — 이미지 생성 패널 spec, FLUX schnell 게이트 회피):
1. diffusers 0.38 + PixArt-Sigma 가 sm_120 / Python 3.14 / CUDA 13 에서 동작하는지 확인.
2. 5060 Ti 16GB (가용 ~7.5GB) 환경에서 1024×1024 한 장 생성 시간 측정.
3. 통째 GPU 적재 vs CPU offload 메모리 비교.
4. step 별 latency (첫 step JIT vs 후속 step).
5. 영어/한국어 프롬프트 결과 비교.
6. close 후 VRAM 해제 확인.

실행:
  .venv/Scripts/python scripts/smoke_pixart_sigma.py

결과물:
  ~/Pictures/KStudio/smoke/ 폴더에 이미지 2장 + 콘솔 로그.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# Windows cp949 콘솔 → 이모지 인코딩 회피.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("smoke_pixart")

OUT_DIR = Path(os.path.expanduser("~")) / "Pictures" / "KStudio" / "smoke"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REPO = "PixArt-alpha/PixArt-Sigma-XL-2-1024-MS"


def _vram_used_gb() -> tuple[float, float]:
    import torch
    if not torch.cuda.is_available():
        return (0.0, 0.0)
    torch.cuda.synchronize()
    free, tot = torch.cuda.mem_get_info()
    return ((tot - free) / 1e9, tot / 1e9)


def _print_vram(label: str) -> None:
    used, tot = _vram_used_gb()
    print(f"  [VRAM] {label}: 사용 {used:.2f}GB / 전체 {tot:.2f}GB")


def main() -> int:
    print("=" * 72)
    print("PixArt-Sigma 1024MS — Phase 1 스모크 테스트")
    print("=" * 72)

    import torch
    print(f"PyTorch  : {torch.__version__}")
    print(f"CUDA     : {torch.cuda.is_available()} (build={torch.version.cuda})")
    print(f"GPU      : {torch.cuda.get_device_name(0)}")
    cap = torch.cuda.get_device_capability(0)
    print(f"Capability: sm_{cap[0]}{cap[1]}")
    _print_vram("시작")
    print()

    # ---- (1) Pipeline 다운로드 + 로드 ----
    print(f"[1/4] Pipeline 다운로드/로드 ({REPO})...")
    print("      구성: DiT 0.6B + T5-XXL ~4.7GB + VAE ~335MB (총 ~6.3GB)")
    t0 = time.time()
    from diffusers import PixArtSigmaPipeline
    pipe = PixArtSigmaPipeline.from_pretrained(
        REPO,
        torch_dtype=torch.bfloat16,
    )
    print(f"      다운로드/구성 완료 ({time.time() - t0:.1f}초)")
    _print_vram("CPU 상태 (아직 .to(cuda) 전)")
    print()

    # ---- (2) CPU offload 강제 ----
    # 1차 시도 (.to("cuda") 통째 적재) 결과 — 사용자 5060 Ti 16GB 환경에서 T5-XXL 9.5GB +
    # DiT 1.2GB + VAE 0.3GB + allocator overhead ≈ 15GB 차서 17.10/17.10 풀 적재 →
    # 매 step PCIe spillover → step 당 40초 (정상 1초 미만 대비 100배 느림).
    # 따라서 통째 GPU 는 5060 Ti / 가용 ≤8GB 환경에서 비현실적. CPU offload 강제.
    # accelerate 가 T5 → DiT → VAE 순서로 한 component 만 GPU 에 올리고 끝나면 CPU 로 swap.
    print("[2/4] enable_model_cpu_offload() — T5/DiT/VAE 를 component 단위로 GPU swap...")
    t0 = time.time()
    pipe.enable_model_cpu_offload()
    print(f"      OK ({time.time() - t0:.1f}초)")
    offload_mode = "cpu-offload (model-level)"
    _print_vram(f"offload 활성화 후 (generate 전)")
    print()

    # ---- (3) 영어 프롬프트 — step latency 측정 ----
    print("[3/4] 영어 프롬프트, 1024×1024, 20-step, guidance=4.5")
    print("-" * 72)
    en_prompt = (
        "A cinematic close-up portrait of a calico cat wearing a tiny astronaut helmet, "
        "warm sunset light through a porthole, shallow depth of field, ultra detailed fur, "
        "photorealistic, 4k"
    )
    print(f"prompt: {en_prompt[:80]}...")

    step_times: list[float] = []
    last_t = [0.0]

    def _step_cb(pipe_, step_idx, timestep, callback_kwargs):
        now = time.time()
        dt = now - last_t[0] if last_t[0] > 0 else 0.0
        step_times.append(dt)
        if step_idx == 0 or step_idx % 5 == 4 or step_idx == 19:
            used, _ = _vram_used_gb()
            print(f"  step {step_idx+1}/20  Δ={dt*1000:.0f}ms  VRAM={used:.2f}GB")
        last_t[0] = now
        return callback_kwargs

    t_gen0 = time.time()
    last_t[0] = t_gen0
    result = pipe(
        prompt=en_prompt,
        height=1024,
        width=1024,
        num_inference_steps=20,
        guidance_scale=4.5,
        generator=torch.Generator("cpu").manual_seed(42),
        callback_on_step_end=_step_cb,
    )
    gen_elapsed = time.time() - t_gen0
    out_path = OUT_DIR / "pixart_en_1024_seed42.png"
    result.images[0].save(out_path)
    used_peak, _ = _vram_used_gb()
    avg_step_ms = sum(step_times[1:]) / max(1, len(step_times) - 1) * 1000
    print()
    print(f"  결과: {out_path}")
    print(f"  총 시간: {gen_elapsed:.1f}초  (첫 step 제외 평균 {avg_step_ms:.0f}ms/step)")
    print(f"  피크 VRAM: {used_peak:.2f}GB")
    print()

    # ---- (4) 한국어 프롬프트 ----
    print("[4/4] 한국어 프롬프트 비교")
    print("-" * 72)
    ko_prompt = "노을이 비치는 창가에 앉아있는 삼색 고양이, 영화 같은 클로즈업, 사실적인 4k 사진"
    print(f"prompt: {ko_prompt}")
    t_gen0 = time.time()
    result_ko = pipe(
        prompt=ko_prompt,
        height=1024,
        width=1024,
        num_inference_steps=20,
        guidance_scale=4.5,
        generator=torch.Generator("cpu").manual_seed(42),
    )
    gen_elapsed = time.time() - t_gen0
    out_ko = OUT_DIR / "pixart_ko_1024_seed42.png"
    result_ko.images[0].save(out_ko)
    print(f"  결과: {out_ko} ({gen_elapsed:.1f}초)")
    print()

    # ---- 정리 ----
    print("[정리] pipe 해제 + empty_cache")
    del pipe
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    _print_vram("해제 후")

    print()
    print("=" * 72)
    print(f"완료. 결과 폴더: {OUT_DIR}")
    print(f"적재 모드: {offload_mode}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _log.exception("smoke failed")
        sys.exit(1)
