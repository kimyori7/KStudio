"""영상 효과 도메인 코어 — UI 의존 없음. 사이드카 모델·우선순위·undo.

주요 export:
- Effect, EffectList — 베이스 모델
- Sidecar, Trim — 사이드카 데이터
- save_atomic, load — 사이드카 파일 I/O
- SidecarStore, compute_video_hash, default_sidecar_dir — 폴더 관리
- History — Undo/Redo
- sort_for_render, RENDER_ORDER — 합성 우선순위
- overlaps_existing — 같은 종류 시간 겹침 검사
- EFFECT_CLASSES, effect_class_for — 종류 dispatch
"""
from .model import Effect, EffectList
from .sidecar import Sidecar, Trim, save_atomic, load
from .sidecar_store import SidecarStore, compute_video_hash, default_sidecar_dir
from .history import History
from .priority import sort_for_render, RENDER_ORDER
from .overlap import overlaps_existing
from .types import EFFECT_CLASSES, effect_class_for

__all__ = [
    "Effect", "EffectList",
    "Sidecar", "Trim", "save_atomic", "load",
    "SidecarStore", "compute_video_hash", "default_sidecar_dir",
    "History",
    "sort_for_render", "RENDER_ORDER",
    "overlaps_existing",
    "EFFECT_CLASSES", "effect_class_for",
]
