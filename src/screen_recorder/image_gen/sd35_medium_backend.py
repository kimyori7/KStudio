"""StableDiffusion3Pipeline 래퍼 — SD 3.5 Medium t2i + i2i.

설계 (2026-05-27):
- 2.5B MMDiT + dual CLIP + T5-XXL text encoder. ~5.1GB 다운로드.
- t2i = `StableDiffusion3Pipeline`, i2i = `StableDiffusion3Img2ImgPipeline`.
  SDXL 와 동일 패턴으로 `from_pipe()` 로 weights 공유.
- 사용자 환경 (가용 ~7.5GB) 에 GPU fit 가능 — 단 T5-XXL 가 ~5GB 라 추론 시 빠듯.
  `enable_model_cpu_offload()` 강제하여 안전 마진 확보.
- 기본 step=40 / guidance=4.5 — SD 3.5 공식 권장.
- License: Stability Community License (개인/소상공인 free, 사용자 결정 OK).
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


class SD35MediumBackend(ImageGenBackend):
    """Stable Diffusion 3.5 Medium — t2i + i2i 동일 weights 공유."""

    DEFAULT_ENTRY_ID = "sd35-medium"

    def __init__(self, entry: Optional[ImageGenModelEntry] = None) -> None:
        self._entry = entry or by_id(self.DEFAULT_ENTRY_ID)
        if self._entry is None:
            raise ValueError(f"SD 3.5 Medium catalog entry '{self.DEFAULT_ENTRY_ID}' not found")
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
        from diffusers import StableDiffusion3Pipeline

        _log.info(
            "SD35MediumBackend.load: repo=%s torch_dtype=bf16 — CPU offload 강제",
            self._entry.repo_id,
        )
        # SD3 는 공식적으로 bf16 권장 (T5 가 bf16 에서 안정).
        pipe = StableDiffusion3Pipeline.from_pretrained(
            self._entry.repo_id,
            torch_dtype=torch.bfloat16,
        )
        pipe.enable_model_cpu_offload()
        self._t2i_pipe = pipe
        _log.info("SD35MediumBackend.load: 완료 (%.1f초)", time.time() - t0)

    def _ensure_i2i(self) -> Any:
        if self._i2i_pipe is not None:
            return self._i2i_pipe
        if self._t2i_pipe is None:
            self.load()
        from diffusers import StableDiffusion3Img2ImgPipeline
        self._i2i_pipe = StableDiffusion3Img2ImgPipeline.from_pipe(self._t2i_pipe)
        _log.info("SD35MediumBackend._ensure_i2i: i2i pipeline 준비 (weights 공유)")
        return self._i2i_pipe

    def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 40,
        guidance_scale: float = 4.5,
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
            pipe = self._ensure_i2i()
            from PIL import Image
            ref = Image.open(str(reference_image)).convert("RGB")
            ref = ref.resize((int(width), int(height)), Image.LANCZOS)
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
            fd, tmp = tempfile.mkstemp(prefix="kstudio_imggen_sd35m_", suffix=".png")
            os.close(fd)
            out_path = Path(tmp)
        img.save(str(out_path))
        mode = "i2i" if reference_image is not None else "t2i"
        _log.info(
            "SD35MediumBackend.generate[%s]: %.1f초 (%dx%d, %d-step) → %s",
            mode, elapsed, width, height, total, out_path,
        )
        return out_path

    def request_cancel(self) -> None:
        self._cancel_requested = True
        _log.info("SD35MediumBackend.request_cancel: 다음 step 경계에서 중단")

    def close(self) -> None:
        if self._t2i_pipe is None and self._i2i_pipe is None:
            return
        _log.info("SD35MediumBackend.close: pipelines 해제 + empty_cache")
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
            _log.exception("SD35MediumBackend.close: cleanup error 무시")
