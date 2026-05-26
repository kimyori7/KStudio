"""KStudio 이미지 생성 모듈 — PixArt-Sigma 1024MS 기반.

공개 API:
- `ImageGenRuntime` — UI 측 핸들 (Signal 어댑터, QThread 관리).
- `ImageGenBackend` Protocol + `GenEvent` dataclass.
- `PixArtSigmaBackend` — diffusers `PixArtSigmaPipeline` 래퍼.
- `MODEL_META` — 메타데이터 (repo_id / 다운로드 크기 / 캐시 경로).
"""
from .backend import GenEvent, ImageGenBackend
from .model_meta import MODEL_META, ImageGenModelMeta
from .pixart_sigma_backend import PixArtSigmaBackend
from .runtime import ImageGenRuntime

__all__ = [
    "GenEvent",
    "ImageGenBackend",
    "ImageGenModelMeta",
    "ImageGenRuntime",
    "MODEL_META",
    "PixArtSigmaBackend",
]
