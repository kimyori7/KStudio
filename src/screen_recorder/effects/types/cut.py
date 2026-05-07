"""CutEffect — 구간 삭제 (옵션 없음)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from ..model import Effect


@dataclass(kw_only=True)
class CutEffect(Effect):
    type: Literal["cut"] = "cut"
