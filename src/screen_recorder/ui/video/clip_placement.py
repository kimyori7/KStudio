"""클립을 트랙의 어느 위치에 놓을지 계산하는 순수 함수들 (Qt 의존 없음).

## 왜 별도 모듈인가

같은 규칙을 두 곳이 써야 한다 — EditController(실제 배치) 와 VideoTrackLane(드래그 중
미리보기). 한쪽에만 있으면 드래그 중 보이던 위치와 놓은 뒤 위치가 달라져, 클립이
손에서 튀는 것처럼 보인다.

## 배치 규칙

트랙은 start_ms 가 위치를 결정하고 클립 사이에 갭(빈칸)이 허용된다. 사용자가 클립을
끌어 놓으면:

1. **놓은 지점이 가리키는 빈칸을 고른다.** 후보는 클립과 클립 사이의 빈 구간 전부이며,
   맞닿아 붙어 있는 두 클립 사이의 폭 0 인 이음매도 후보에 포함된다 (그 자리에 끼워
   넣으려는 의도가 가장 흔하므로). 각 후보에 대해 "그 후보에 넣었을 때의 시작 위치" 를
   구하고, 놓은 지점에서 가장 가까운 후보를 고른다.
2. **빈칸이 클립보다 넓으면** 그 안에서 놓은 지점 그대로 둔다 — 자유 배치 유지.
3. **빈칸이 좁으면** 빈칸 시작에 놓고 **뒤 클립들을 부족한 만큼 오른쪽으로 민다.**
   미는 양은 모든 뒤 클립이 같아 서로의 간격은 그대로 유지된다.

3번이 이 모듈을 만든 이유다. 이전에는 좁은 빈칸에 놓으면 들어갈 자리를 못 찾아
트랙 맨 뒤로 보내 버렸다 (2026-08-19 사용자 보고: "빈칸 크기 작으면 맨뒤로 다시
날아가버리는데 비집고 들어가게 해줘").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class Placement:
    """배치 계획 — 클립을 어디에 놓고, 뒤 클립들을 얼마나 미는지.

    - start_ms: 클립이 놓일 트랙 위치
    - push_from_ms: start_ms 가 이 값 이상인 클립들이 밀림 대상
    - push_delta_ms: 미는 양. 0 이면 아무도 밀지 않는다 (빈칸에 그대로 들어감)
    """
    start_ms: int
    push_from_ms: int = 0
    push_delta_ms: int = 0

    @property
    def pushes(self) -> bool:
        return self.push_delta_ms > 0


def free_intervals(others: Iterable) -> list[tuple[int, Optional[int]]]:
    """클립들 사이의 빈 구간 목록. (lo, hi) 이며 마지막은 hi=None (트랙 끝 이후 무한).

    폭 0 인 구간(맞닿은 두 클립 사이, 0 에서 시작하는 첫 클립 앞)도 포함한다 — 이음매
    자체가 "여기 끼워 넣고 싶다" 는 유효한 목표점이기 때문. 겹친 클립이 있어도 cursor 가
    뒤로 가지 않아 구간이 음수 폭이 되지 않는다.
    """
    ivs: list[tuple[int, Optional[int]]] = []
    cursor = 0
    for s in sorted(others, key=lambda x: int(x.start_ms)):
        start = int(s.start_ms)
        if start >= cursor:
            ivs.append((cursor, start))
        cursor = max(cursor, int(s.end_ms))
    ivs.append((cursor, None))
    return ivs


def _placement_in(interval: tuple[int, Optional[int]], target: int,
                  dur: int) -> Placement:
    """한 빈 구간에 넣었을 때의 배치. 구간이 좁으면 밀기 양을 계산한다."""
    lo, hi = interval
    if hi is None:                      # 트랙 끝 이후 — 언제나 들어간다.
        return Placement(start_ms=max(target, lo))
    width = hi - lo
    if width >= dur:                    # 넉넉함 — 구간 안에서 놓은 지점 그대로.
        return Placement(start_ms=min(max(target, lo), hi - dur))
    # 좁음 — 구간 시작에 놓고 부족분만큼 뒤를 민다.
    return Placement(start_ms=lo, push_from_ms=hi, push_delta_ms=dur - width)


def plan_placement(others: Sequence, target_start_ms: int, duration_ms: int) -> Placement:
    """`others` 사이 어디에 길이 duration_ms 인 클립을 놓을지 계획한다.

    `others` 에는 옮기는 클립 자신을 넣지 말 것 — 자기가 비우는 자리도 후보가 되어야
    "살짝 끌었다 놓으면 제자리로" 가 자연스럽게 성립한다.

    각 요소는 start_ms / end_ms 를 가져야 한다 (VideoSegment).
    """
    target = max(0, int(target_start_ms))
    dur = max(0, int(duration_ms))
    ivs = free_intervals(others)
    if not ivs:
        return Placement(start_ms=target)
    best: Optional[Placement] = None
    best_key: Optional[tuple] = None
    for iv in ivs:
        cand = _placement_in(iv, target, dur)
        # 놓은 지점에서 가까운 것 우선. 거리가 같으면 밀지 않는 쪽, 그다음 앞쪽.
        key = (abs(cand.start_ms - target), cand.push_delta_ms, cand.start_ms)
        if best_key is None or key < best_key:
            best, best_key = cand, key
    assert best is not None
    return best


def apply_push(segments: Sequence, placement: Placement, *,
               exclude_id: Optional[str] = None) -> list[tuple[int, int]]:
    """밀림 대상 클립들의 (인덱스, 이동 후 start_ms) 목록. 밀 게 없으면 빈 리스트.

    exclude_id 는 지금 옮기는 중인 클립 — 이미 새 자리가 정해졌으므로 밀지 않는다.
    (왼쪽 빈칸으로 옮기는 경우 자신의 옛 위치가 밀림 범위 안에 들어올 수 있다.)
    """
    if not placement.pushes:
        return []
    out: list[tuple[int, int]] = []
    for i, s in enumerate(segments):
        if exclude_id is not None and getattr(s, "id", None) == exclude_id:
            continue
        if int(s.start_ms) >= placement.push_from_ms:
            out.append((i, int(s.start_ms) + placement.push_delta_ms))
    return out


@dataclass(frozen=True)
class MoveOutcome:
    """클립 이동 결과 — 호출자(UI)가 사용자에게 무슨 일이 있었는지 알리는 데 쓴다.

    밀기는 사용자가 지시하지 않은 다른 클립까지 움직이므로 조용히 넘기지 않는다.
    """
    moved: bool = False
    start_ms: int = 0
    pushed_count: int = 0
    push_delta_ms: int = 0

    def __bool__(self) -> bool:
        return self.moved


def placement_note(outcome: MoveOutcome, requested_ms: int) -> str:
    """배치 결과를 사용자에게 덧붙일 한 줄로. 알릴 게 없으면 빈 문자열.

    알리는 경우는 둘 —
    - 뒤 클립을 밀어 끼워 넣었다 (지시하지 않은 클립이 움직였다)
    - 놓은 지점과 실제 자리가 다르다 (가까운 빈칸으로 옮겨 붙었다)

    MoveOutcome 과 짝이라 같은 파일에 둔다. Qt 를 쓰지 않아 그대로 테스트할 수 있다.
    """
    if outcome.pushed_count > 0:
        return (f" — 뒤 클립 {outcome.pushed_count}개를 "
                f"{outcome.push_delta_ms / 1000:.1f}초 밀어 끼워 넣음")
    if outcome.start_ms != max(0, int(requested_ms)):
        return f" — 겹쳐서 {outcome.start_ms / 1000:.1f}초 자리로 이동"
    return ""
