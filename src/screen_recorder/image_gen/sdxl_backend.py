"""StableDiffusionXLPipeline 래퍼 — t2i + i2i 공유 weights.

설계 (2026-05-27):
- SDXL 1.0 base 는 6.6B U-Net + dual text encoder. ~6.94GB 다운로드.
- t2i = `StableDiffusionXLPipeline`, i2i = `StableDiffusionXLImg2ImgPipeline`.
  diffusers 의 `from_pipe()` 로 같은 weights 를 두 pipeline 사이 공유 → 메모리 절약
  (한 번만 로드, 두 모드 모두 즉시 가용).
- 사용자 환경 (가용 ~7.5GB) 에서 통째 GPU 도 빡빡 — PixArt 와 동일하게
  `enable_model_cpu_offload()` 강제. GPU 피크 ~4GB 예상.
- cancel 은 `_interrupt` 플래그 (PixArt 와 동일 패턴).
- 기본 step=30 / guidance=5.0 — SDXL 공식 권장.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from .backend import ImageGenBackend, StepCallback
from .model_catalog import by_id, ImageGenModelEntry

_log = logging.getLogger(__name__)


class SDXLBackend(ImageGenBackend):
    """SDXL 1.0 base — t2i + i2i 동일 weights 공유.

    수명주기:
    - load() 시 t2i pipeline 만 만들고, i2i 호출 시 `from_pipe()` 로 lazy 변환.
    - close() 는 두 pipeline 모두 해제.
    """

    DEFAULT_ENTRY_ID = "sdxl-1.0"

    def __init__(self, entry: Optional[ImageGenModelEntry] = None) -> None:
        self._entry = entry or by_id(self.DEFAULT_ENTRY_ID)
        if self._entry is None:
            raise ValueError(f"SDXL catalog entry '{self.DEFAULT_ENTRY_ID}' not found")
        self._t2i_pipe: Optional[Any] = None
        self._i2i_pipe: Optional[Any] = None
        self._cancel_requested = False

    # ---- ImageGenBackend Protocol ----

    def is_loaded(self) -> bool:
        return self._t2i_pipe is not None

    def load(self) -> None:
        if self._t2i_pipe is not None:
            return
        t0 = time.time()
        import torch  # noqa: F401
        from diffusers import StableDiffusionXLPipeline

        _log.info(
            "SDXLBackend.load: repo=%s torch_dtype=fp16 — CPU offload 강제",
            self._entry.repo_id,
        )
        # SDXL 은 공식적으로 fp16 권장 (bf16 가능하지만 fp16 가 표준).
        # variant="fp16" 으로 명시하면 fp16 safetensors 만 다운로드 (~6.94GB).
        pipe = StableDiffusionXLPipeline.from_pretrained(
            self._entry.repo_id,
            torch_dtype=torch.float16,
            variant="fp16",
            use_safetensors=True,
        )
        pipe.enable_model_cpu_offload()
        self._t2i_pipe = pipe
        _log.info("SDXLBackend.load: 완료 (%.1f초)", time.time() - t0)

    def _ensure_i2i(self) -> Any:
        """i2i pipeline lazy 변환 — t2i weights 재사용 (`from_pipe`)."""
        if self._i2i_pipe is not None:
            return self._i2i_pipe
        if self._t2i_pipe is None:
            self.load()
        from diffusers import StableDiffusionXLImg2ImgPipeline
        # from_pipe 는 weights 를 재사용 → 추가 VRAM 거의 없음.
        self._i2i_pipe = StableDiffusionXLImg2ImgPipeline.from_pipe(self._t2i_pipe)
        _log.info("SDXLBackend._ensure_i2i: i2i pipeline 준비 (weights 공유)")
        return self._i2i_pipe

    def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 30,
        guidance_scale: float = 5.0,
        seed: Optional[int] = None,
        step_cb: Optional[StepCallback] = None,
        out_path: Optional[Path] = None,
        reference_image: Optional[Path] = None,
        strength: float = 0.7,
    ) -> Path:
        if self._t2i_pipe is None:
            raise RuntimeError("backend not loaded — call load() first")
        if not prompt or not prompt.strip():
            raise ValueError("prompt 가 비었습니다")

        import torch

        self._cancel_requested = False
        total = int(num_inference_steps)

        def _cb(pipe_obj, step_idx: int, _timestep, callback_kwargs):
            if self._cancel_requested:
                try:
                    pipe_obj._interrupt = True
                except Exception:
                    pass
            if step_cb is not None:
                try:
                    step_cb(step_idx + 1, total)
                except Exception:
                    _log.exception("step_cb raised — 무시")
            return callback_kwargs

        generator = None
        if seed is not None and seed >= 0:
            generator = torch.Generator("cpu").manual_seed(int(seed))

        t0 = time.time()
        if reference_image is not None:
            # ---- Image-to-Image ----
            pipe = self._ensure_i2i()
            from PIL import Image
            ref = Image.open(str(reference_image)).convert("RGB")
            # SDXL i2i 는 입력 이미지를 target 해상도로 리사이즈 권장.
            ref = ref.resize((int(width), int(height)), Image.LANCZOS)
            # i2i 에서 strength 가 실효 step 수를 줄임 (steps * strength).
            # UI 의 num_inference_steps 는 그대로 두고 strength 만 노출.
            result = pipe(
                prompt=prompt,
                image=ref,
                strength=float(strength),
                num_inference_steps=total,
                guidance_scale=float(guidance_scale),
                generator=generator,
                callback_on_step_end=_cb,
            )
        else:
            # ---- Text-to-Image ----
            result = self._t2i_pipe(
                prompt=prompt,
                height=int(height),
                width=int(width),
                num_inference_steps=total,
                guidance_scale=float(guidance_scale),
                generator=generator,
                callback_on_step_end=_cb,
            )
        elapsed = time.time() - t0

        if self._cancel_requested:
            raise InterruptedError("generation cancelled by user")
        if not result.images:
            raise RuntimeError("generation returned no images")

        img = result.images[0]
        if out_path is None:
            fd, tmp = tempfile.mkstemp(prefix="kstudio_imggen_sdxl_", suffix=".png")
            os.close(fd)
            out_path = Path(tmp)
        img.save(str(out_path))
        mode = "i2i" if reference_image is not None else "t2i"
        _log.info(
            "SDXLBackend.generate[%s]: %.1f초 (%dx%d, %d-step) → %s",
            mode, elapsed, width, height, total, out_path,
        )
        return out_path

    def request_cancel(self) -> None:
        self._cancel_requested = True
        _log.info("SDXLBackend.request_cancel: 다음 step 경계에서 중단")

    def close(self) -> None:
        if self._t2i_pipe is None and self._i2i_pipe is None:
            return
        _log.info("SDXLBackend.close: pipelines 해제 + empty_cache")
        try:
            self._i2i_pipe = None
            self._t2i_pipe = None
            import gc
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception:
            _log.exception("SDXLBackend.close: cleanup error 무시")
