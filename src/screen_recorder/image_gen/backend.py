"""ImageGenBackend Protocol + GenEvent dataclass.

PixArtSigma 외에 다른 모델로 갈아끼울 수 있도록 인터페이스 분리.
백엔드는 "프롬프트 받아서 step 진행하다 이미지 한 장을 디스크에 저장" 만 책임.
스레딩 / Qt 시그널은 [runtime.py](runtime.py) 가 담당.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol


@dataclass
class GenEvent:
    """generate() 의 yield 이벤트 (현재는 callback 으로 전달, dataclass 는 향후 확장 대비)."""
    type: str          # "step" | "image_ready" | "error" | "cancelled"
    step: int = 0
    total_steps: int = 0
    image_path: Optional[Path] = None
    message: str = ""


# step 진행 콜백: (current_step_1based, total_steps) — UI 에 progress emit 용.
StepCallback = Callable[[int, int], None]


class ImageGenBackend(Protocol):
    """이미지 생성 백엔드. 모든 메서드 동기 — 호출 측 (runtime) 이 QThread 에서 호출."""

    def is_loaded(self) -> bool:
        """pipeline 이 GPU/CPU 로 로드되어 즉시 generate 가능한지."""
        ...

    def load(self) -> None:
        """모델 로드 (디스크 → 메모리). 이미 로드되어 있으면 no-op.

        다운로드는 사전에 [models/downloader.ModelDownloadJob] 으로 완료된 상태를 가정.
        """
        ...

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
    ) -> Path:
        """1장 생성. 결과 이미지를 out_path (None 이면 임시 파일) 에 저장하고 경로 반환.

        cancel 요청을 받으면 ``InterruptedError`` 를 raise.
        step_cb 는 매 step 후 호출 — UI progress.
        """
        ...

    def request_cancel(self) -> None:
        """다음 step 경계에서 generate 중단. step_cb 가 호출되는 시점에 체크.

        실제 중단은 diffusers `pipe._interrupt` 플래그 또는 사용자 정의 flag.
        """
        ...

    def close(self) -> None:
        """모델 메모리 해제 + `torch.cuda.empty_cache()`. 재로드 가능 상태로."""
        ...
