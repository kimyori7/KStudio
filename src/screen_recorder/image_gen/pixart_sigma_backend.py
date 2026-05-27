"""PixArtSigmaPipeline 래퍼 — Phase 1 스모크 스크립트를 클래스로 정리.

Phase 1 실측 (2026-05-26):
- `.to("cuda")` 통째 적재는 5060 Ti / 가용 ~16GB 에서도 풀 적재 → step 당 40초 (13분/장).
- `enable_model_cpu_offload()` 모드: GPU 피크 1.38GB, 1024×1024 20-step **18.5초**.
→ 무조건 CPU offload 모드만 사용.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from .backend import ImageGenBackend, StepCallback
from .model_meta import MODEL_META, ImageGenModelMeta

_log = logging.getLogger(__name__)


class PixArtSigmaBackend(ImageGenBackend):
    """diffusers PixArtSigmaPipeline 래퍼.

    수명주기:
    - 생성 직후엔 `is_loaded()=False`. load() 명시 호출 후 generate 가능.
    - close() 호출 시 pipeline 해제 + `torch.cuda.empty_cache()`.
    """

    def __init__(self, meta: Optional[ImageGenModelMeta] = None) -> None:
        self._meta = meta or MODEL_META
        self._pipe: Optional[Any] = None
        self._cancel_requested = False

    # ---- ImageGenBackend Protocol ----

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        t0 = time.time()
        # 무거운 import 는 load 시점까지 지연 — UI 부팅 빨라짐 + 의존성 없는 환경에서
        # 모듈 import 만으로 죽지 않음.
        import torch  # noqa: F401  (caching allocator 등 부수효과)
        from diffusers import PixArtSigmaPipeline

        _log.info(
            "PixArtSigmaBackend.load: repo=%s torch_dtype=bf16 — CPU offload 강제",
            self._meta.repo_id,
        )
        pipe = PixArtSigmaPipeline.from_pretrained(
            self._meta.repo_id,
            torch_dtype=torch.bfloat16,
        )
        # 통째 GPU 는 spillover 유발 — Phase 1 실측 확인됨. 강제 offload.
        pipe.enable_model_cpu_offload()
        self._pipe = pipe
        _log.info(
            "PixArtSigmaBackend.load: 완료 (%.1f초)",
            time.time() - t0,
        )

    def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 20,
        guidance_scale: float = 4.5,
        seed: Optional[int] = None,
        step_cb: Optional[StepCallback] = None,
        out_path: Optional[Path] = None,
        reference_image: Optional[Path] = None,
        strength: float = 0.7,
    ) -> Path:
        if self._pipe is None:
            raise RuntimeError("backend not loaded — call load() first")
        if not prompt or not prompt.strip():
            raise ValueError("prompt 가 비었습니다")
        if reference_image is not None:
            # PixArt-Sigma 는 diffusers 표준 img2img pipeline 이 없음 — Phase 1 미지원.
            # 카탈로그 entry 의 supports_i2i=False 와 일치.
            raise NotImplementedError(
                "PixArt-Sigma 백엔드는 image-to-image 를 지원하지 않습니다. "
                "SDXL 또는 SD 3.5 Medium 을 사용하세요."
            )

        import torch

        self._cancel_requested = False

        # diffusers callback — 매 step 끝에 호출됨.
        # step_idx 는 0-based. UI 에는 1-based 로 emit.
        total = int(num_inference_steps)

        def _cb(pipe_obj, step_idx: int, _timestep, callback_kwargs):
            if self._cancel_requested:
                # diffusers 0.30+ 의 정식 중단 플래그.
                try:
                    pipe_obj._interrupt = True
                except Exception:
                    pass
            if step_cb is not None:
                try:
                    step_cb(step_idx + 1, total)
                except Exception:
                    _log.exception("step_cb raised — 무시하고 generate 계속")
            return callback_kwargs

        # seed=None → 랜덤 (None 그대로). 명시 시 cpu Generator 로 재현성.
        generator = None
        if seed is not None and seed >= 0:
            generator = torch.Generator("cpu").manual_seed(int(seed))

        t0 = time.time()
        result = self._pipe(
            prompt=prompt,
            height=int(height),
            width=int(width),
            num_inference_steps=total,
            guidance_scale=float(guidance_scale),
            generator=generator,
            callback_on_step_end=_cb,
        )
        elapsed = time.time() - t0

        # interrupt 로 중단된 경우 — result.images 가 비어있거나 부분 이미지.
        # diffusers 는 interrupt 시점에 partial latent 를 decode 해 image 를 돌려주지만,
        # KStudio 입장에선 사용자가 "취소" 누른 거니 결과 폐기.
        if self._cancel_requested:
            raise InterruptedError("generation cancelled by user")

        if not result.images:
            raise RuntimeError("generation returned no images")

        img = result.images[0]
        if out_path is None:
            # 임시 파일 — 호출자가 명시적으로 옮기거나 저장 안 함 → 세션 종료 시 OS 정리.
            fd, tmp = tempfile.mkstemp(prefix="kstudio_imggen_", suffix=".png")
            os.close(fd)
            out_path = Path(tmp)
        img.save(str(out_path))
        _log.info(
            "PixArtSigmaBackend.generate: %.1f초 (%dx%d, %d-step) → %s",
            elapsed, width, height, total, out_path,
        )
        return out_path

    def request_cancel(self) -> None:
        self._cancel_requested = True
        _log.info("PixArtSigmaBackend.request_cancel: 다음 step 경계에서 중단")

    def close(self) -> None:
        if self._pipe is None:
            return
        _log.info("PixArtSigmaBackend.close: pipeline 해제 + empty_cache")
        try:
            # accelerate hook 정리 — model_cpu_offload 가 register 한 hook 이 garbage
            # collected 되면 stale CUDA tensor 가 남을 수 있어 명시적 해제.
            self._pipe = None
            import gc
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception:
            _log.exception("PixArtSigmaBackend.close: cleanup error 무시")
