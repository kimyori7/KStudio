"""VideoSegment — 트랙의 한 클립.

비디오 트랙의 한 위치를 차지하는 영상/이미지/GIF 파일의 일부분. 트랙은 segment 의
순서 있는 리스트이고, 결합 시간축은 각 segment.duration_ms 의 누적합으로 만들어진다.

효과(캡션/줌/배속/곁들임) 는 Premiere-style 로 segment 의 자식으로 보유 — segment 가
재배치돼도 효과도 같이 따라 움직인다. effects 의 in_ms / out_ms 는 segment 안의
source 시간축 기준 (0 = segment 시작).
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Literal


_VALID_MEDIA = {"video", "image", "gif"}


@dataclass(kw_only=True)
class VideoSegment:
    """비디오 트랙의 한 클립 — 영상/이미지/GIF 파일의 일부분.

    - src: 절대 경로
    - src_in_ms / src_out_ms: source 시간축의 일부분
    - src_out_ms == 0 → source 끝까지 (영상 전체 사용)
    - media_kind == "image" → image_duration_ms 가 segment 길이
    - effects: segment-local 효과 리스트 (0 = segment 시작)
    - start_ms: 트랙(combined timeline) 상의 시작 위치. 자르기 + 자유 이동 + 갭(gap)
      지원을 위해 v3 부터 명시적으로 저장. 두 segment 가 같은 start_ms 를 가지면 안 되고
      서로 겹쳐서도 안 된다 (UI 가 clamp 책임).
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    src: str
    src_in_ms: int = 0
    src_out_ms: int = 0
    src_duration_ms: int = 0
    media_kind: Literal["video", "image", "gif"] = "video"
    image_duration_ms: int = 3000
    effects: list = field(default_factory=list)
    start_ms: int = 0

    def __post_init__(self) -> None:
        if self.media_kind not in _VALID_MEDIA:
            raise ValueError(
                f"media_kind must be one of {sorted(_VALID_MEDIA)}, got {self.media_kind!r}"
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
        if self.media_kind == "image" and self.image_duration_ms <= 0:
            raise ValueError(
                f"image segment requires image_duration_ms > 0, "
                f"got {self.image_duration_ms}"
            )
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be >= 0, got {self.start_ms}")

    @property
    def end_ms(self) -> int:
        """트랙상 종료 위치 (배타적). start_ms + duration_ms."""
        return self.start_ms + self.duration_ms

    @property
    def duration_ms(self) -> int:
        """이 segment 가 결과 영상에서 차지하는 길이 (ms)."""
        if self.media_kind == "image":
            return self.image_duration_ms
        if self.src_out_ms > 0:
            return self.src_out_ms - self.src_in_ms
        if self.src_duration_ms > 0:
            return self.src_duration_ms - self.src_in_ms
        return 0
