"""유튜브 다운로드 요청 데이터 (순수)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    mode: Literal["video", "mp3"]
    out_dir: Path
    quality: str   # video: best|1080|720|480 / mp3: 320|256|192
