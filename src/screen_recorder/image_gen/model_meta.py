"""이미지 생성 모델 메타데이터 — 다운로드 / 표시용 정보.

향후 모델 추가 시 ImageGenModelMeta 리스트로 확장. 첫 출시는 PixArt-Sigma 단일.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ImageGenModelMeta:
    """이미지 생성 모델 메타데이터."""

    id: str                          # 내부 식별자 (settings 저장용)
    display_name: str                # UI 표시 이름
    repo_id: str                     # HuggingFace repo
    description: str                 # 사용자 설명
    estimated_size_gb: float         # 대략 다운로드 크기
    estimated_vram_gb: float         # CPU offload 시 GPU 피크 (참고용)
    default_steps: int               # 권장 기본 step 수
    default_guidance: float          # 권장 guidance_scale
    default_resolution: int          # 권장 정사각 해상도 (예 1024)
    supports_korean: bool            # 한국어 프롬프트 지원 (T5 encoder 등)


# Phase 1 실측 (2026-05-26) 결과 기반:
# - 다운로드 ~6.3GB (DiT 0.6B + T5-XXL ~4.7GB + VAE ~335MB)
# - CPU offload 모드에서 GPU 피크 1.38GB
# - 1024×1024 20-step 18.5초 (영어) / 22.1초 (한국어)
PIXART_SIGMA_1024MS = ImageGenModelMeta(
    id="pixart-sigma-1024ms",
    display_name="PixArt-Sigma 1024MS",
    repo_id="PixArt-alpha/PixArt-Sigma-XL-2-1024-MS",
    description=(
        "0.6B DiT + T5-XXL 텍스트 인코더. ungated (HF 로그인 불필요). "
        "1024×1024 약 20초/장. T5 가 다국어라 한국어 프롬프트도 동작 — "
        "단 학습 데이터 비중은 영어. CPU offload 모드 (GPU 피크 ~1.5GB)."
    ),
    estimated_size_gb=6.3,
    estimated_vram_gb=1.5,
    default_steps=20,
    default_guidance=4.5,
    default_resolution=1024,
    supports_korean=True,
)


MODEL_META: ImageGenModelMeta = PIXART_SIGMA_1024MS
"""현재 기본 모델 — 첫 출시는 PixArt-Sigma 단일."""


def estimated_size_bytes(meta: Optional[ImageGenModelMeta] = None) -> int:
    """ModelDownloadJob 의 estimated_size_bytes 파라미터 용 — GB → bytes."""
    m = meta or MODEL_META
    return int(m.estimated_size_gb * 1024 * 1024 * 1024)
