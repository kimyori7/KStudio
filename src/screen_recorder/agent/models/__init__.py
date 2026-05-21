"""모델 라이브러리 — 메타데이터 + 레지스트리 + 의존성 가드.

sub-plan 3 Phase 3a — built-in 4개 + check_runtime_available.
sub-plan 3 Phase 3b 가 ModelDownloadWindow 추가 예정.
sub-plan 4 가 user_models.json 머지 추가 예정.
"""
from .metadata import ModelMetadata
from .registry import ModelRegistry, check_runtime_available
from .cache import is_model_cached
from .downloader import ModelDownloadJob

__all__ = [
    "ModelMetadata", "ModelRegistry", "check_runtime_available",
    "is_model_cached", "ModelDownloadJob",
]
