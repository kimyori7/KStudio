"""bitsandbytes 4-bit + Qwen2.5 + RTX 5060 Ti (sm_120) + CUDA 13.0 smoke test.

작은 모델 (0.5B, ~1GB) 로 4-bit 로드 + 한 번 generate 시도. 동작/속도/메모리만 확인.
실패하면 bitsandbytes 가 sm_120 (Blackwell) 미지원 → A 도 폐기.

성공하면 Qwen2.5-Omni 7B 에 같은 패턴 적용 가능.
"""
from __future__ import annotations

import time
import sys
import traceback

import torch


def main() -> int:
    print(f"[env] torch={torch.__version__} cuda={torch.version.cuda} "
          f"device={torch.cuda.get_device_name(0)}", flush=True)

    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    except Exception as e:
        print(f"[FAIL] transformers import: {e}", flush=True)
        return 1

    try:
        import bitsandbytes as bnb
        print(f"[env] bitsandbytes={bnb.__version__}", flush=True)
    except Exception as e:
        print(f"[FAIL] bitsandbytes import: {e}", flush=True)
        return 1

    repo_id = "Qwen/Qwen2.5-0.5B-Instruct"
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    print(f"[load] {repo_id} (4-bit NF4) ...", flush=True)
    t0 = time.time()
    try:
        model = AutoModelForCausalLM.from_pretrained(
            repo_id,
            quantization_config=quant_config,
            device_map="auto",
            attn_implementation="sdpa",
        )
        tokenizer = AutoTokenizer.from_pretrained(repo_id)
    except Exception as e:
        print(f"[FAIL] model load (4-bit): {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 2
    print(f"[load] OK in {time.time()-t0:.1f}s", flush=True)

    messages = [{"role": "user", "content": "1+1 은? 숫자만 한 줄로."}]
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    print(f"[gen] generate(max_new=30) ...", flush=True)
    t0 = time.time()
    try:
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=30, do_sample=False)
    except Exception as e:
        print(f"[FAIL] generate: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return 3
    dt = time.time() - t0
    n_new = out.shape[1] - inputs["input_ids"].shape[1]
    print(f"[gen] OK in {dt:.2f}s, {n_new} tokens, "
          f"{n_new/dt:.1f} tok/s", flush=True)

    result = tokenizer.decode(
        out[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )
    print(f"[out] {result!r}", flush=True)

    mem_gb = torch.cuda.max_memory_allocated() / 1e9
    print(f"[mem] peak VRAM = {mem_gb:.2f} GB (bf16 라면 ~1.0GB 예상, "
          f"4-bit 면 ~0.4GB)", flush=True)

    print("[PASS] bitsandbytes 4-bit + Qwen2.5-0.5B + sm_120 동작", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
