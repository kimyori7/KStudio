"""사각형 overlay 조작의 순수 기하 (Qt 비의존, 정규화 0~1 좌표).

사각형은 (start, end) 대각 두 점으로 저장. 그리기·hit-test 는 min/max 로
사각형을 만들어 비반전. 모서리 리사이즈는 잡은 모서리만 이동하고 대각 반대편을
고정(자유 종횡비). 본체 이동은 평행이동하되 벽에 닿으면 크기를 보존하며 멈춘다.

반환값은 모두 (sx, sy, ex, ey) 4-튜플 — overlay 가 RectEffect.start/end 로 반영.
"""
from __future__ import annotations


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def normalize(sx: float, sy: float, ex: float, ey: float):
    """(sx,sy,ex,ey) → (left, top, right, bottom) = min/max."""
    return (min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey))


def corner_points(sx: float, sy: float, ex: float, ey: float):
    """네 시각적 모서리 좌표 — min/max 기준 tl/tr/bl/br."""
    left, top, right, bottom = normalize(sx, sy, ex, ey)
    return {
        "tl": (left, top),
        "tr": (right, top),
        "bl": (left, bottom),
        "br": (right, bottom),
    }


# 잡은 모서리 → 고정될 대각 반대편 모서리.
_OPPOSITE = {"tl": "br", "br": "tl", "tr": "bl", "bl": "tr"}


def resize_corner(corner: str, sx: float, sy: float, ex: float, ey: float,
                  nx: float, ny: float):
    """`corner` 모서리를 (nx, ny) 로 이동, 대각 반대편은 고정. 자유 종횡비.

    반환 (sx', sy', ex', ey') = (고정 anchor 점, 끌린 점). 단위 [0,1] 클램프.
    렌더러가 min/max 로 정규화하므로 끌린 점이 anchor 너머로 가도 비반전.
    """
    cps = corner_points(sx, sy, ex, ey)
    anchor = cps[_OPPOSITE[corner]]
    nx = _clamp01(nx)
    ny = _clamp01(ny)
    return (anchor[0], anchor[1], nx, ny)


def move_rect(sx: float, sy: float, ex: float, ey: float,
              dnx: float, dny: float):
    """사각형 전체를 (dnx, dny) 만큼 평행이동. 벽에 닿으면 크기 보존하며 멈춤."""
    left, top, right, bottom = normalize(sx, sy, ex, ey)
    width = right - left
    height = bottom - top
    # 이동 후 left/top 을 [0, 1-size] 로 클램프 → 실제 적용된 delta 추출.
    new_left = max(0.0, min(1.0 - width, left + dnx))
    new_top = max(0.0, min(1.0 - height, top + dny))
    dnx_eff = new_left - left
    dny_eff = new_top - top
    return (sx + dnx_eff, sy + dny_eff, ex + dnx_eff, ey + dny_eff)
