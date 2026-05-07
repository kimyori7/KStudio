"""effects.timeline — 결합 시간축 매핑 helper.

CutEffect 들의 in_ms/out_ms (A 자르기) + src_in_ms/src_out_ms (B 트림) 으로부터
결합 시간축의 segment 리스트를 만든다. UI 의존 없음.

용어:
- main: 원본 영상 (CutEffect 의 source 가 아닌 원래 영상)
- insert: CutEffect 의 src 가 가리키는 B 영상 (effect 마다 다른 파일)
- combined ms: 결합 영상의 시간축 ms (자르기 적용 + B 추가 후)
- source ms: main 또는 insert 영상 자체의 ms
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional

from .types.cut import CutEffect


@dataclass(frozen=True)
class TimelineSegment:
    """결합 시간축의 한 구간.

    - source="main" : 원본 영상의 일부. source_id=None.
    - source="insert" : CutEffect 의 B 영상. source_id=effect.id.
    """
    combined_start_ms: int
    combined_end_ms: int
    source: Literal["main", "insert"]
    source_id: Optional[str]
    source_start_ms: int
    source_end_ms: int


def build_combined_timeline(
    main_duration_ms: int,
    cuts: list[CutEffect],
) -> list[TimelineSegment]:
    """cuts 를 in_ms 기준 정렬·검증 후 결합 시간축 segment 리스트 반환.

    빈 main remainder (예: cut 끝 == 다음 cut 시작) 는 segment 로 추가하지 않는다.
    겹치는 cut 은 ValueError. main_duration_ms < 0 도 ValueError.
    """
    if main_duration_ms < 0:
        raise ValueError(f"main_duration_ms must be >= 0, got {main_duration_ms}")

    sorted_cuts = sorted(cuts, key=lambda c: c.in_ms)

    # 겹침 검증
    for i in range(1, len(sorted_cuts)):
        prev = sorted_cuts[i - 1]
        cur = sorted_cuts[i]
        if cur.in_ms < prev.out_ms:
            raise ValueError(
                f"CutEffect overlap: {prev.id} ({prev.in_ms}-{prev.out_ms}) "
                f"vs {cur.id} ({cur.in_ms}-{cur.out_ms})"
            )

    segments: list[TimelineSegment] = []
    combined_cursor = 0
    main_cursor = 0
    for cut in sorted_cuts:
        # 1) cut 직전까지의 main 구간
        if cut.in_ms > main_cursor:
            length = cut.in_ms - main_cursor
            segments.append(TimelineSegment(
                combined_start_ms=combined_cursor,
                combined_end_ms=combined_cursor + length,
                source="main",
                source_id=None,
                source_start_ms=main_cursor,
                source_end_ms=cut.in_ms,
            ))
            combined_cursor += length
        # 2) cut 의 B insert (있으면)
        ins_dur = cut.insert_duration_ms
        if cut.has_insert and ins_dur > 0:
            ins_end = cut.src_out_ms or cut.src_duration_ms
            segments.append(TimelineSegment(
                combined_start_ms=combined_cursor,
                combined_end_ms=combined_cursor + ins_dur,
                source="insert",
                source_id=cut.id,
                source_start_ms=cut.src_in_ms,
                source_end_ms=ins_end,
            ))
            combined_cursor += ins_dur
        # 3) main_cursor 를 cut 끝으로 진행
        main_cursor = cut.out_ms

    # 4) 마지막 cut 이후 main 잔여
    if main_cursor < main_duration_ms:
        length = main_duration_ms - main_cursor
        segments.append(TimelineSegment(
            combined_start_ms=combined_cursor,
            combined_end_ms=combined_cursor + length,
            source="main",
            source_id=None,
            source_start_ms=main_cursor,
            source_end_ms=main_duration_ms,
        ))

    return segments


def combined_to_source(
    t_combined_ms: int,
    segments: list[TimelineSegment],
) -> tuple[str, Optional[str], int]:
    """결합 시간축 ms → (source, source_id, source_ms).

    매칭은 'start <= t < end'. t == 결합 끝 ms 는 마지막 segment 의 끝점으로 clamp.
    음수 t 는 0 으로 clamp.
    빈 segments 는 ValueError.
    """
    if not segments:
        raise ValueError("empty segments")
    t = max(0, t_combined_ms)
    last = segments[-1]
    if t >= last.combined_end_ms:
        return last.source, last.source_id, last.source_end_ms
    for seg in segments:
        if seg.combined_start_ms <= t < seg.combined_end_ms:
            offset = t - seg.combined_start_ms
            return seg.source, seg.source_id, seg.source_start_ms + offset
    # 도달 불가 — segments 가 0 부터 last.end 까지 빈틈 없이 채운다는 invariant.
    raise ValueError(f"timeline gap at t={t}")


def source_to_combined(
    source: str,
    source_id: Optional[str],
    source_ms: int,
    segments: list[TimelineSegment],
) -> int:
    """source 의 ms → 결합 ms.

    같은 source/source_id 에 매칭되고 source_start_ms <= source_ms <= source_end_ms 인
    segment 를 찾는다. 없으면 ValueError ("no segment for ...").
    """
    for seg in segments:
        if seg.source != source:
            continue
        if seg.source_id != source_id:
            continue
        if seg.source_start_ms <= source_ms <= seg.source_end_ms:
            offset = source_ms - seg.source_start_ms
            return seg.combined_start_ms + offset
    raise ValueError(
        f"no segment for source={source!r} id={source_id!r} ms={source_ms}"
    )
