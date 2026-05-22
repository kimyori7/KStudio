"""Qwen2.5-Omni 7B + 4-bit NF4 + CPU offload 실 검증.

사용자 환경에서 'Object of type type is not JSON serializable' 에러 재현/디버그.
KStudio 가 GPU 점유 중이면 종료 후 실행할 것.
"""
from __future__ import annotations

import sys
import time
import traceback
import torch


def main() -> int:
    print(f"[env] torch={torch.__version__} cuda={torch.version.cuda} "
          f"device={torch.cuda.get_device_name(0)}", flush=True)
    print(f"[env] free VRAM: {torch.cuda.mem_get_info()[0]/1e9:.1f} GB", flush=True)

    from transformers import (
        Qwen2_5OmniForConditionalGeneration,
        Qwen2_5OmniProcessor,
        BitsAndBytesConfig,
    )
    import bitsandbytes as bnb
    print(f"[env] bnb={bnb.__version__} transformers OK", flush=True)

    repo_id = "Qwen/Qwen2.5-Omni-7B"

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        llm_int8_enable_fp32_cpu_offload=True,
    )
    print(f"[config] {quant!r}", flush=True)

    print(f"[load] {repo_id} (4-bit NF4 + CPU offload) ...", flush=True)
    t0 = time.time()
    try:
        model = Qwen2_5OmniForConditionalGeneration.from_pretrained(
            repo_id,
            quantization_config=quant,
            device_map="auto",
            attn_implementation="sdpa",
        )
    except Exception as e:
        print(f"[FAIL] model load: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 2
    print(f"[load] OK in {time.time()-t0:.1f}s", flush=True)

    # disable_talker 호출 시도 (run-time 에 talker module 해제).
    try:
        disable = getattr(model, "disable_talker", None)
        if callable(disable):
            disable()
            print("[talker] disabled OK", flush=True)
    except Exception as e:
        print(f"[talker] disable failed (무시): {e}", flush=True)

    # device 분포 확인 — 어떤 모듈이 cpu / cuda 인지.
    try:
        hf_device_map = getattr(model, "hf_device_map", None)
        if hf_device_map:
            cpu_modules = [k for k, v in hf_device_map.items() if v == "cpu"]
            cuda_modules = [k for k, v in hf_device_map.items() if v != "cpu"]
            print(f"[device] cuda 모듈 {len(cuda_modules)}, cpu 모듈 {len(cpu_modules)}", flush=True)
            if cpu_modules:
                print(f"[device] cpu 로 간 모듈 (talker 등 OK): {cpu_modules[:10]}", flush=True)
    except Exception:
        pass

    print(f"[mem] peak VRAM = {torch.cuda.max_memory_allocated()/1e9:.2f} GB", flush=True)

    # processor 로드.
    print(f"[load] processor ...", flush=True)
    try:
        processor = Qwen2_5OmniProcessor.from_pretrained(repo_id)
    except Exception as e:
        print(f"[FAIL] processor load: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 3

    # 한 번 generate.
    conv = [
        {"role": "system", "content": [{"type": "text", "text": "너는 한국어 비서."}]},
        {"role": "user", "content": "1+1 은? 숫자만."},
    ]
    text = processor.apply_chat_template(conv, add_generation_prompt=True, tokenize=False)
    try:
        from qwen_omni_utils import process_mm_info
        audios, images, videos = process_mm_info(conv, use_audio_in_video=False)
    except Exception as e:
        print(f"[FAIL] process_mm_info: {e}", flush=True)
        return 4

    inputs = processor(
        text=text, audio=audios, images=images, videos=videos,
        return_tensors="pt", padding=True, use_audio_in_video=False,
    )
    inputs = inputs.to(model.device)

    print(f"[gen] generate(max_new=20) ...", flush=True)
    t0 = time.time()
    try:
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=20, do_sample=False,
                return_audio=False, use_audio_in_video=False,
            )
    except Exception as e:
        print(f"[FAIL] generate: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 5
    dt = time.time() - t0
    n_new = out.shape[1] - inputs["input_ids"].shape[1]
    print(f"[gen] OK in {dt:.2f}s, {n_new} tokens, {n_new/dt:.1f} tok/s", flush=True)

    result = processor.batch_decode(
        out[:, inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )
    print(f"[out] {result!r}", flush=True)
    print("[PASS] Qwen2.5-Omni 7B + 4-bit + CPU offload 동작", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
