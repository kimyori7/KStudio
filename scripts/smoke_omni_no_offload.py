"""Qwen2.5-Omni 7B + 4-bit + CPU offload OFF — 모든 weights GPU 에 fit 시도.

목적: talker 까지 GPU 에 두면 RAM 절감. 16GB VRAM 안에 fit 하는지 검증.
fit 안 되면 추가 조치 (talker meta device / INT8) 필요.
"""
from __future__ import annotations

import sys
import time
import traceback
import torch


def main() -> int:
    print(f"[env] free={torch.cuda.mem_get_info()[0]/1e9:.1f}GB / "
          f"{torch.cuda.mem_get_info()[1]/1e9:.1f}GB total", flush=True)

    from transformers import (
        Qwen2_5OmniForConditionalGeneration,
        BitsAndBytesConfig,
    )

    # CPU offload 없이 — 모두 GPU 강제.
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        # llm_int8_enable_fp32_cpu_offload=False (기본).
    )

    print("[load] Omni 4-bit (CPU offload OFF) ...", flush=True)
    t0 = time.time()
    try:
        model = Qwen2_5OmniForConditionalGeneration.from_pretrained(
            "Qwen/Qwen2.5-Omni-7B",
            quantization_config=quant,
            device_map="auto",
            attn_implementation="sdpa",
        )
    except Exception as e:
        print(f"[FAIL load] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 2
    print(f"[load] OK in {time.time()-t0:.1f}s", flush=True)

    # device 분포 확인 — 어디에 뭐가 있나.
    hf_map = getattr(model, "hf_device_map", None) or {}
    cpu_keys = sorted(k for k, v in hf_map.items() if v == "cpu")
    disk_keys = sorted(k for k, v in hf_map.items() if v == "disk")
    cuda_keys = sorted(k for k, v in hf_map.items() if isinstance(v, int) or str(v).startswith("cuda"))
    print(f"[device] cuda={len(cuda_keys)} cpu={len(cpu_keys)} disk={len(disk_keys)}", flush=True)
    print(f"[device] cuda 모듈 sample: {cuda_keys[:5]}", flush=True)
    if cpu_keys:
        print(f"[device] cpu 모듈: {cpu_keys[:10]}", flush=True)

    print(f"[mem] VRAM peak = {torch.cuda.max_memory_allocated()/1e9:.2f}GB", flush=True)
    print(f"[mem] VRAM still allocated = {torch.cuda.memory_allocated()/1e9:.2f}GB", flush=True)
    print("[PASS] no CPU offload — fit OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
