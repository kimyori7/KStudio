"""CutEffect — A 의 [in_ms, out_ms] 구간 자르기 + 옵션으로 그 자리에 B 영상 끼워넣기.

- in_ms == out_ms : splice point (자르기 없음, 그 시점에 B 삽입 자리)
- in_ms <  out_ms : 구간 자르기 (옵션으로 B 끼워넣기)
- src 가 빈 문자열이면 단순 자르기 (B 없음)

베이스 Effect 의 __post_init__ 은 out_ms > in_ms 를 강제하므로,
CutEffect 는 super().__post_init__() 을 호출하지 않고 자체 검증한다.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from ..model import Effect


_VALID_SCALE = {"fit", "fill", "stretch"}


@dataclass(kw_only=True)
class CutEffect(Effect):
    type: Literal["cut"] = "cut"

    src: str = ""
    src_in_ms: int = 0
    src_out_ms: int = 0
    src_duration_ms: int = 0
    scale_mode: str = "fit"

    def __post_init__(self) -> None:
        if self.in_ms < 0:
            raise ValueError(f"in_ms must be >= 0, got {self.in_ms}")
        if self.out_ms < self.in_ms:
            raise ValueError(
                f"out_ms must be >= in_ms (got in_ms={self.in_ms}, out_ms={self.out_ms})"
            )
        if self.scale_mode not in _VALID_SCALE:
            raise ValueError(
                f"scale_mode must be one of {sorted(_VALID_SCALE)}, got {self.scale_mode!r}"
            )
        if self.src_in_ms < 0:
            raise ValueError(f"src_in_ms must be >= 0, got {self.src_in_ms}")
        if self.src_out_ms < 0:
            raise ValueError(f"src_out_ms must be >= 0, got {self.src_out_ms}")
        if 0 < self.src_out_ms <= self.src_in_ms:
            raise ValueError(
                f"src_out_ms must be > src_in_ms (got src_in_ms={self.src_in_ms}, "
                f"src_out_ms={self.src_out_ms}); use 0 for 'until end'"
            )

    @property
    def is_splice(self) -> bool:
        return self.in_ms == self.out_ms

    @property
    def has_insert(self) -> bool:
        return bool(self.src)

    @property
    def insert_duration_ms(self) -> int:
        """B 가 결과 영상에서 차지하는 길이.

        src 가 비어있으면 0. src_out_ms == 0 이면 src_duration_ms 까지 사용.

        주의: src 가 채워졌지만 src_out_ms 와 src_duration_ms 가 모두 0 이면
        반환값 0 은 'zero-length' 가 아닌 '아직 길이 미상' 을 의미한다.
        UI 흐름은 src 지정 직후 ffprobe 로 src_duration_ms 를 채우므로 이 상태는
        보통 영상 효과를 처음 추가하고 ffprobe 가 끝나기 전 일시적으로만 발생.
        """
        if not self.has_insert:
            return 0
        end = self.src_out_ms or self.src_duration_ms
        return max(0, end - self.src_in_ms)
