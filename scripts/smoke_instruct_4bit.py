"""Qwen2.5-7B-Instruct (text-only, ~12GB, cache 있음) + 4-bit + CPU offload.

Omni 와 같은 BitsAndBytesConfig 경로 — 'Object of type type is not JSON serializable'
재현 시도. 7B-Instruct 가 더 가볍고 cache 있어 빠르게 결과 나옴.
"""
from __future__ import annotations

import sys
import time
import traceback
import torch


def main() -> int:
    print(f"[env] device={torch.cuda.get_device_name(0)} "
          f"free={torch.cuda.mem_get_info()[0]/1e9:.1f}GB", flush=True)

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        llm_int8_enable_fp32_cpu_offload=True,
    )
    print(f"[config] {quant!r}", flush=True)

    repo = "Qwen/Qwen2.5-7B-Instruct"
    print(f"[load] {repo} 4-bit ...", flush=True)
    t0 = time.time()
    try:
        model = AutoModelForCausalLM.from_pretrained(
            repo, quantization_config=quant,
            device_map="auto", attn_implementation="sdpa",
        )
        tok = AutoTokenizer.from_pretrained(repo)
    except Exception as e:
        print(f"[FAIL load] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 2
    print(f"[load] OK in {time.time()-t0:.1f}s", flush=True)
    print(f"[mem] peak={torch.cuda.max_memory_allocated()/1e9:.2f}GB", flush=True)

    messages = [{"role": "user", "content": "1+1?"}]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(model.device)

    print(f"[gen] ...", flush=True)
    t0 = time.time()
    try:
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=10, do_sample=False)
    except Exception as e:
        print(f"[FAIL gen] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 3
    dt = time.time() - t0
    n = out.shape[1] - inputs["input_ids"].shape[1]
    print(f"[gen] OK {dt:.2f}s {n} tok ({n/dt:.1f} tok/s)", flush=True)
    print(f"[out] {tok.decode(out[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)!r}",
          flush=True)
    print("[PASS]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
