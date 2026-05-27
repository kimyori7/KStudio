"""이미지 생성 모델 카탈로그 — Text-to-Image / Image-to-Image 둘 다 지원.

설계 (2026-05-27 사용자 결정):
- 카탈로그 axis = **checkpoint** 1개 row (SDXL t2i + SDXL i2i 는 같은 weights 공유 →
  한 row). `supports_t2i` / `supports_i2i` 플래그로 모드 가용성 표시.
- 정렬: `quality_rank` 오름차순 (1 = 최고 품질). UI 가 그대로 표시.
- 사용자 환경 (RTX 5060 Ti 16GB, 가용 ~7.5GB, sm_120 Blackwell) 제약 + 사용자
  결정 ("빡빡해도 좋은 거, license 개인용 OK") 반영.
- `is_implemented` False = 카탈로그엔 보이지만 백엔드 미구현. UI 는 "다음 업데이트
  지원 예정" 표시 + 다운로드 비활성. Phase 1 출시 시 SDXL / SD 3.5 Medium 만 True.

확장 방법:
- 새 모델 추가 → `CATALOG` 에 `ImageGenModelEntry` 추가 + `is_implemented=False`.
- 백엔드 구현 → 같은 entry 의 `is_implemented=True` + `backend_kind` 분기 추가
  (`runtime.py` 의 backend factory).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# fp16 variant 받기용 표준 패턴 — SDXL/SD3.5/FLUX 모두 같은 diffusers 레이아웃.
# HF snapshot_download 의 allow_patterns 로 전달.
#
# 배경 (2026-05-27 사용자 보고): SDXL 1.0 다운로드 시 카탈로그 추정 6.94GB 에 비해
# 실제 27.9GB 받음. snapshot_download 기본 동작은 repo 의 모든 파일 (fp32 .bin +
# fp16 .safetensors + native + non_ema 등 모든 variant) 을 받기 때문. fp16 만 골라
# 받게 패턴 명시하면 카탈로그 추정값과 일치.
DIFFUSERS_FP16_ALLOW = [
    "*.json",                    # model_index.json + 각 sub-component config
    "*.txt",                     # README, special_tokens_map.txt 등
    "*.fp16.safetensors",        # fp16 weights (각 sub-dir 의)
    "tokenizer*/**",             # tokenizer/, tokenizer_2/ 전체
    "*.model",                   # sentencepiece (T5 등)
    "*.spm",
    "vocab*",
    "merges*",
]

# variant 없는 모델 (PixArt 등) 용 — 명백히 큰 무관 파일만 제외.
HEAVY_VARIANT_IGNORE = [
    "*.bin",                     # PyTorch native (대부분 safetensors 와 중복)
    "*.msgpack",                 # Flax
    "*.ot",                      # Rust transformers
    "*.onnx*",
    "*.h5",                      # TensorFlow
    "*.tflite",
    "*non_ema*",                 # SD 의 non-EMA variant (필요 X)
]


@dataclass(frozen=True)
class ImageGenModelEntry:
    """이미지 생성 모델 카탈로그 항목 — 다운로드 + UI 표시 + backend dispatch 키."""

    id: str                          # 내부 식별자 (settings 저장용)
    display_name: str                # UI 표시 이름
    repo_id: str                     # HuggingFace repo
    quality_rank: int                # 1 = 최고 품질 (정렬 키)
    estimated_size_gb: float         # 다운로드 크기 (정확 검증 필요)
    estimated_vram_gb: float         # 추론 시 GPU 피크
    speed_label: str                 # UI 표시 ("10~20초/장")
    license_label: str               # 짧은 라벨 ("상업 OK", "비상업")
    license_note: Optional[str]      # 추가 설명
    supports_t2i: bool
    supports_i2i: bool
    supports_inpaint: bool
    default_steps: int
    default_guidance: float
    default_resolution: int
    backend_kind: str                # "pixart" / "sdxl" / "sd35_medium" / "sd35_large" / "flux"
    is_implemented: bool             # 현재 코드에서 실제 generate 가능?
    description: str
    # 다운로드 시 HF snapshot_download 에 넘길 패턴 — variant 다중 받기 방지.
    download_allow_patterns: Optional[tuple[str, ...]] = None
    download_ignore_patterns: Optional[tuple[str, ...]] = None


CATALOG: tuple[ImageGenModelEntry, ...] = (
    # Rank 1 — FLUX.1-dev. 12B DiT. CPU offload 강제 → 2~4분/장. 비상업 라이선스.
    ImageGenModelEntry(
        id="flux1-dev",
        display_name="FLUX.1 dev",
        repo_id="black-forest-labs/FLUX.1-dev",
        quality_rank=1,
        estimated_size_gb=23.8,
        estimated_vram_gb=8.0,    # CPU offload 시 GPU 피크 (DiT 단일 transformer 블록)
        speed_label="2~4분/장 (CPU offload)",
        license_label="비상업",
        license_note="개인용/실험 OK · 상업 콘텐츠엔 사용 불가 (FLUX.1 [dev] License)",
        supports_t2i=True,
        supports_i2i=True,        # FLUX.1 Kontext 별도 — 일단 t2i 우선
        supports_inpaint=True,
        default_steps=28,
        default_guidance=3.5,
        default_resolution=1024,
        backend_kind="flux",
        is_implemented=False,     # Phase 1 미구현 — UI 에 "준비 중" 표시
        description=(
            "FLUX.1 dev — 12B parameters. 현재 오픈 모델 중 텍스트 충실도/디테일 최고 수준. "
            "사용자 환경에서는 CPU offload 강제라 1024×1024 한 장에 2~4분. "
            "라이선스: 비상업 (개인용/연구만)."
        ),
        # FLUX 는 단일 .safetensors (flux1-dev.safetensors ~24GB) + T5/CLIP — variant 없음.
        download_ignore_patterns=tuple(HEAVY_VARIANT_IGNORE),
    ),
    # Rank 2 — SD 3.5 Large. 8B MMDiT. CPU offload 강제 → 1~2분/장.
    ImageGenModelEntry(
        id="sd35-large",
        display_name="Stable Diffusion 3.5 Large",
        repo_id="stabilityai/stable-diffusion-3.5-large",
        quality_rank=2,
        estimated_size_gb=16.5,
        estimated_vram_gb=8.0,
        speed_label="1~2분/장 (CPU offload)",
        license_label="상업 OK*",
        license_note="Stability Community License — 연 매출 $1M 이하 상업 사용 무료",
        supports_t2i=True,
        supports_i2i=True,
        supports_inpaint=False,
        default_steps=40,
        default_guidance=4.5,
        default_resolution=1024,
        backend_kind="sd35_large",
        is_implemented=False,     # Phase 1 미구현
        description=(
            "Stable Diffusion 3.5 Large — 8B MMDiT. 텍스트 충실도 우수, 손/구도 안정. "
            "사용자 환경에서 CPU offload 분 단위. 라이선스: Stability Community."
        ),
        download_ignore_patterns=tuple(HEAVY_VARIANT_IGNORE),
    ),
    # Rank 3 — SD 3.5 Medium. 2.5B MMDiT. GPU fit. 10~20초/장. Phase 1 구현 대상.
    ImageGenModelEntry(
        id="sd35-medium",
        display_name="Stable Diffusion 3.5 Medium",
        repo_id="stabilityai/stable-diffusion-3.5-medium",
        quality_rank=3,
        estimated_size_gb=5.1,
        estimated_vram_gb=5.5,
        speed_label="10~20초/장",
        license_label="상업 OK*",
        license_note="Stability Community License — 연 매출 $1M 이하 상업 사용 무료",
        supports_t2i=True,
        supports_i2i=True,
        supports_inpaint=False,
        default_steps=40,
        default_guidance=4.5,
        default_resolution=1024,
        backend_kind="sd35_medium",
        is_implemented=True,      # Phase 1 구현
        description=(
            "Stable Diffusion 3.5 Medium — 2.5B MMDiT. 사용자 GPU 에 fit 하면서 텍스트 "
            "충실도 SDXL 이상. img2img 지원."
        ),
        # SD 3.5 Medium 은 diffusers 레이아웃, fp16 variant 있음 (T5-XXL fp16 가 큰 비중).
        download_allow_patterns=tuple(DIFFUSERS_FP16_ALLOW),
    ),
    # Rank 4 — SDXL 1.0. 6.6B UNet. GPU fit. 8~15초/장. Phase 1 구현 대상 (workhorse).
    ImageGenModelEntry(
        id="sdxl-1.0",
        display_name="SDXL 1.0",
        repo_id="stabilityai/stable-diffusion-xl-base-1.0",
        quality_rank=4,
        estimated_size_gb=6.94,
        estimated_vram_gb=7.0,
        speed_label="8~15초/장",
        license_label="상업 OK",
        license_note="CreativeML Open RAIL++-M (상업 사용 가능)",
        supports_t2i=True,
        supports_i2i=True,
        supports_inpaint=False,    # 별도 inpaint checkpoint (sd-xl-inpainting-1.0) 필요
        default_steps=30,
        default_guidance=5.0,
        default_resolution=1024,
        backend_kind="sdxl",
        is_implemented=True,       # Phase 1 구현
        description=(
            "SDXL 1.0 — 6.6B U-Net + dual text encoder. 가장 표준화/안정. img2img 동일 "
            "weights 재사용. KStudio Phase 1 의 workhorse."
        ),
        # SDXL repo 는 fp32 .bin + fp16 .safetensors + native + non_ema 모두 있어
        # 전체 받으면 ~28GB. fp16 only 만 받으면 ~7GB (카탈로그 추정값과 일치).
        download_allow_patterns=tuple(DIFFUSERS_FP16_ALLOW),
    ),
    # Rank 5 — PixArt-Sigma 1024MS. 0.6B DiT. 가장 가벼움 + 이미 캐시됨.
    ImageGenModelEntry(
        id="pixart-sigma-1024ms",
        display_name="PixArt-Sigma 1024MS",
        repo_id="PixArt-alpha/PixArt-Sigma-XL-2-1024-MS",
        quality_rank=5,
        estimated_size_gb=6.3,
        estimated_vram_gb=1.5,
        speed_label="10~20초/장 (CPU offload)",
        license_label="상업 OK",
        license_note="OpenRAIL (상업 사용 가능)",
        supports_t2i=True,
        supports_i2i=False,       # diffusers 표준 img2img pipeline 없음 — text-only fallback
        supports_inpaint=False,
        default_steps=20,
        default_guidance=4.5,
        default_resolution=1024,
        backend_kind="pixart",
        is_implemented=True,       # 기존 백엔드
        description=(
            "PixArt-Sigma 1024MS — 0.6B DiT + T5-XXL. 가장 가벼움 (CPU offload 시 GPU "
            "피크 ~1.5GB). T5 다국어라 한국어 프롬프트도 동작. text-to-image 전용."
        ),
        # PixArt 는 single variant — 무거운 무관 파일만 제외.
        download_ignore_patterns=tuple(HEAVY_VARIANT_IGNORE),
    ),
)


def by_id(model_id: str) -> Optional[ImageGenModelEntry]:
    """카탈로그에서 model_id 로 entry 찾기. 못 찾으면 None."""
    for e in CATALOG:
        if e.id == model_id:
            return e
    return None


def t2i_models() -> list[ImageGenModelEntry]:
    """Text-to-Image 지원 모델 — 품질순 정렬."""
    return sorted(
        [e for e in CATALOG if e.supports_t2i],
        key=lambda e: e.quality_rank,
    )


def i2i_models() -> list[ImageGenModelEntry]:
    """Image-to-Image 지원 모델 — 품질순 정렬."""
    return sorted(
        [e for e in CATALOG if e.supports_i2i],
        key=lambda e: e.quality_rank,
    )


def default_model_for_mode(mode: str) -> ImageGenModelEntry:
    """모드별 권장 기본 — '구현 완료 모델 중 품질 최상'.

    Phase 1 기준: t2i = SDXL 1.0 / i2i = SDXL 1.0 (PixArt 는 i2i 미지원).
    """
    items = t2i_models() if mode == "t2i" else i2i_models()
    for e in items:
        if e.is_implemented:
            return e
    return items[0]   # 모든 모델이 미구현이면 첫 entry


def estimated_size_bytes(entry: ImageGenModelEntry) -> int:
    """ModelDownloadJob 의 estimated_size_bytes 파라미터 용."""
    return int(entry.estimated_size_gb * 1024 * 1024 * 1024)
