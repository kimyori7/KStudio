"""오디오 편집 순수 기하 — 트림/컷 ↔ ms/x, keep 구간. Qt 비의존(단위테스트 용이).

데이터 모델:
- 트림: (trim_in_ms, trim_out_ms). trim_out_ms == 0 → 끝까지.
- 컷: [(in_ms, out_ms), ...] — 정렬·비중첩 유지(_normalize 가 보장).
- x↔ms: body 폭/총길이 선형.
"""
from __future__ import annotations


def ms_to_x(ms: int, *, total_ms: int, width: int) -> int:
    if total_ms <= 0 or width <= 0:
        return 0
    return int(round(max(0, min(ms, total_ms)) * width / total_ms))


def x_to_ms(x: int, *, total_ms: int, width: int) -> int:
    if width <= 0 or total_ms <= 0:
        return 0
    return int(round(max(0, min(x, width)) * total_ms / width))


def _normalize(cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """정렬 + 겹치거나 맞닿은 구간 병합. 0폭 제거."""
    clean = sorted((min(a, b), max(a, b)) for a, b in cuts if a != b)
    out: list[tuple[int, int]] = []
    for s, e in clean:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def add_cut(cuts: list[tuple[int, int]], new: tuple[int, int]) -> list[tuple[int, int]]:
    """컷 구간 추가(역방향 드래그 정규화, 0폭 무시, 겹침 병합)."""
    s, e = min(new), max(new)
    if s == e:
        return _normalize(list(cuts))
    return _normalize(list(cuts) + [(s, e)])


def remove_cut_at(cuts: list[tuple[int, int]], ms: int) -> list[tuple[int, int]]:
    """ms 가 걸친 컷 구간을 제거(클릭으로 컷 취소)."""
    return [(s, e) for (s, e) in cuts if not (s <= ms <= e)]


def playback_skip_target(ms: int, keep: list[tuple[int, int]]) -> "int | None":
    """재생 중 ms 위치 처리 — 잘라낸(제거된) 구간을 건너뛰어 '이어붙은 것처럼' 들리게.

    반환:
    - None  → ms 가 살아있는(keep) 구간 안 → 그대로 재생.
    - -1    → 마지막 keep 끝을 지남 → 정지(끝).
    - n>=0  → ms 가 제거된 구간 → 다음 keep 시작 ms 로 점프.
    keep 는 정렬·비중첩(compute_audio_keep_intervals 산출) 가정.
    """
    if not keep:
        return None
    if ms >= keep[-1][1]:
        return -1
    for s, e in keep:
        if s <= ms < e:
            return None
        if ms < s:
            return s
    return None


def keep_intervals(*, trim_in_ms: int, trim_out_ms: int, total_ms: int,
                   cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """트림 [in,out] 범위에서 cuts 를 뺀 보존 구간. trim_out_ms==0 → total."""
    start = max(0, int(trim_in_ms))
    end = int(trim_out_ms) if trim_out_ms > 0 else int(total_ms)
    if total_ms > 0:
        end = min(end, total_ms)
    keep = [(start, end)] if end > start else []
    for c_s, c_e in _normalize(cuts):
        nxt: list[tuple[int, int]] = []
        for k_s, k_e in keep:
            if c_e <= k_s or c_s >= k_e:
                nxt.append((k_s, k_e))
                continue
            if c_s > k_s:
                nxt.append((k_s, c_s))
            if c_e < k_e:
                nxt.append((c_e, k_e))
        keep = nxt
    return keep
