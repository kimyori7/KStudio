"""FLUX.1 schnell GGUF Q4_K_S 직접 로드 + 1장 생성 — Phase 1 스모크 테스트.

목적 (2026-05-26 — 이미지 생성 패널 spec):
1. diffusers 0.38 + GGUF 가 sm_120 / Python 3.14 / CUDA 13 에서 동작하는지 확인.
2. 5060 Ti 16GB (가용 ~7.5GB) 환경에서 1024×1024 한 장 생성 시간 측정.
3. T5-XXL CPU offload 동작 확인 (transformer 만 GPU, encoder 는 CPU).
4. step 별 latency 측정 (첫 step JIT vs 후속 step).
5. 영어/한국어 프롬프트 결과 비교.
6. close 후 VRAM 해제 확인.

실행:
  .venv/Scripts/python scripts/smoke_flux_schnell.py

결과물:
  ~/Pictures/KStudio/smoke/ 폴더에 5장 이미지 + 콘솔 로그.
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
_log = logging.getLogger("smoke_flux")

# 출력 폴더 (사용자 Pictures 아래).
OUT_DIR = Path(os.path.expanduser("~")) / "Pictures" / "KStudio" / "smoke"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GGUF_REPO = "city96/FLUX.1-schnell-gguf"
GGUF_FILENAME = "flux1-schnell-Q4_K_S.gguf"   # ~6.8GB
BASE_REPO = "black-forest-labs/FLUX.1-schnell"   # VAE/text encoder 출처


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
    print("FLUX.1 schnell GGUF Q4_K_S — Phase 1 스모크 테스트")
    print("=" * 72)

    import torch
    print(f"PyTorch  : {torch.__version__}")
    print(f"CUDA     : {torch.cuda.is_available()} (build={torch.version.cuda})")
    print(f"GPU      : {torch.cuda.get_device_name(0)}")
    print(f"Capability: sm_{torch.cuda.get_device_capability(0)[0]}{torch.cuda.get_device_capability(0)[1]}")
    _print_vram("시작")
    print()

    # ---- (1) GGUF transformer 다운로드 ----
    print("[1/5] GGUF transformer 다운로드 중...")
    t0 = time.time()
    from huggingface_hub import hf_hub_download
    gguf_path = hf_hub_download(
        repo_id=GGUF_REPO,
        filename=GGUF_FILENAME,
    )
    print(f"      OK ({time.time() - t0:.1f}초) — {gguf_path}")
    print(f"      파일 크기: {os.path.getsize(gguf_path) / 1e9:.2f}GB")
    print()

    # ---- (2) GGUF transformer 로드 ----
    print("[2/5] GGUF transformer 로딩 (GPU bf16)...")
    t0 = time.time()
    from diffusers import FluxTransformer2DModel, GGUFQuantizationConfig
    transformer = FluxTransformer2DModel.from_single_file(
        gguf_path,
        quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
        torch_dtype=torch.bfloat16,
        config=BASE_REPO,
        subfolder="transformer",
    )
    print(f"      로드 완료 ({time.time() - t0:.1f}초)")
    _print_vram("transformer 로드 후 (아직 .to(cuda) 전)")
    print()

    # ---- (3) Pipeline 구성 + CPU offload ----
    print("[3/5] FluxPipeline 구성 + CPU offload 활성화...")
    t0 = time.time()
    from diffusers import FluxPipeline
    pipe = FluxPipeline.from_pretrained(
        BASE_REPO,
        transformer=transformer,
        torch_dtype=torch.bfloat16,
    )
    # T5-XXL + CLIP 은 CPU 에, transformer 와 VAE 만 generate 직전에 GPU 로 swap.
    # enable_model_cpu_offload() 는 accelerate 가 자동으로 layer swap.
    pipe.enable_model_cpu_offload()
    print(f"      Pipeline 준비 완료 ({time.time() - t0:.1f}초)")
    _print_vram("Pipeline 준비 후 (generate 전)")
    print()

    # ---- (4) 본 측정 — step 별 latency 측정 callback ----
    print("[4/5] 본 측정: 영어 프롬프트, 1024×1024, 4-step")
    print("-" * 72)
    en_prompt = (
        "A cinematic close-up portrait of a calico cat wearing a tiny astronaut helmet, "
        "warm sunset light through a porthole, shallow depth of field, ultra detailed fur, "
        "photorealistic, 4k"
    )
    print(f"prompt: {en_prompt[:80]}...")
    print()

    step_times: list[float] = []
    last_t = [time.time()]

    def _step_cb(pipe_, step_idx, timestep, callback_kwargs):
        now = time.time()
        dt = now - last_t[0]
        step_times.append(dt)
        used, _ = _vram_used_gb()
        print(f"  step {step_idx+1}/4  Δ={dt*1000:.0f}ms  VRAM={used:.2f}GB")
        last_t[0] = now
        return callback_kwargs

    t_gen0 = time.time()
    last_t[0] = t_gen0
    result = pipe(
        prompt=en_prompt,
        height=1024,
        width=1024,
        num_inference_steps=4,
        guidance_scale=0.0,   # schnell 은 guidance=0
        generator=torch.Generator("cpu").manual_seed(42),
        callback_on_step_end=_step_cb,
    )
    gen_elapsed = time.time() - t_gen0
    img = result.images[0]
    out_path = OUT_DIR / "en_1024_seed42.png"
    img.save(out_path)
    used_peak, _ = _vram_used_gb()
    print()
    print(f"  결과: {out_path} ({gen_elapsed:.1f}초, 피크 VRAM={used_peak:.2f}GB)")
    print(f"  step 평균 (첫 step 제외): "
          f"{sum(step_times[1:]) / max(1, len(step_times) - 1) * 1000:.0f}ms")
    print()

    # ---- (5) 한국어 프롬프트 — 결과 품질 비교 ----
    print("[5/5] 한국어 프롬프트 비교")
    print("-" * 72)
    ko_prompt = "노을이 비치는 창가에 앉아있는 삼색 고양이, 영화 같은 클로즈업, 사실적인 4k 사진"
    print(f"prompt: {ko_prompt}")
    t_gen0 = time.time()
    result_ko = pipe(
        prompt=ko_prompt,
        height=1024,
        width=1024,
        num_inference_steps=4,
        guidance_scale=0.0,
        generator=torch.Generator("cpu").manual_seed(42),
    )
    gen_elapsed = time.time() - t_gen0
    out_ko = OUT_DIR / "ko_1024_seed42.png"
    result_ko.images[0].save(out_ko)
    print(f"  결과: {out_ko} ({gen_elapsed:.1f}초)")
    print()

    # ---- 정리 ----
    print("[정리] pipe 해제 + empty_cache")
    del pipe, transformer
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    _print_vram("해제 후")

    print()
    print("=" * 72)
    print(f"완료. 결과 폴더: {OUT_DIR}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _log.exception("smoke failed")
        sys.exit(1)
