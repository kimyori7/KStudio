"""rect_overlay_geometry — 순수 기하 (Qt 비의존).

사각형 overlay 조작의 계산을 단위테스트 가능한 순수 함수로 분리.
- 모서리 리사이즈: 잡은 모서리만 이동, 대각 반대편 고정, 자유 종횡비.
- 본체 이동: 평행이동, 벽에 닿으면 크기 보존하며 멈춤.
"""
import pytest

from screen_recorder.ui.video.rect_overlay_geometry import (
    normalize, corner_points, resize_corner, move_rect,
)


def test_normalize_min_max():
    # 뒤집힌 입력도 (left, top, right, bottom) 로 정규화.
    assert normalize(0.6, 0.7, 0.2, 0.3) == pytest.approx((0.2, 0.3, 0.6, 0.7))


def test_corner_points():
    cp = corner_points(0.2, 0.3, 0.6, 0.7)
    assert cp["tl"] == pytest.approx((0.2, 0.3))
    assert cp["tr"] == pytest.approx((0.6, 0.3))
    assert cp["bl"] == pytest.approx((0.2, 0.7))
    assert cp["br"] == pytest.approx((0.6, 0.7))


def test_resize_corner_br_keeps_tl_fixed():
    new = resize_corner("br", 0.2, 0.3, 0.6, 0.7, 0.8, 0.9)
    cp = corner_points(*new)
    assert cp["tl"] == pytest.approx((0.2, 0.3))   # 대각 고정
    assert cp["br"] == pytest.approx((0.8, 0.9))   # 잡은 모서리 이동


def test_resize_corner_tl_keeps_br_fixed():
    new = resize_corner("tl", 0.2, 0.3, 0.6, 0.7, 0.1, 0.15)
    cp = corner_points(*new)
    assert cp["br"] == pytest.approx((0.6, 0.7))
    assert cp["tl"] == pytest.approx((0.1, 0.15))


def test_resize_corner_tr_keeps_bl_fixed():
    new = resize_corner("tr", 0.2, 0.3, 0.6, 0.7, 0.9, 0.1)
    cp = corner_points(*new)
    assert cp["bl"] == pytest.approx((0.2, 0.7))
    assert cp["tr"] == pytest.approx((0.9, 0.1))


def test_resize_corner_bl_keeps_tr_fixed():
    new = resize_corner("bl", 0.2, 0.3, 0.6, 0.7, 0.05, 0.95)
    cp = corner_points(*new)
    assert cp["tr"] == pytest.approx((0.6, 0.3))
    assert cp["bl"] == pytest.approx((0.05, 0.95))


def test_resize_corner_clamps_to_unit():
    new = resize_corner("br", 0.2, 0.3, 0.6, 0.7, 1.5, 1.5)
    cp = corner_points(*new)
    assert cp["br"] == pytest.approx((1.0, 1.0))
    new2 = resize_corner("tl", 0.2, 0.3, 0.6, 0.7, -0.5, -0.5)
    cp2 = corner_points(*new2)
    assert cp2["tl"] == pytest.approx((0.0, 0.0))


def test_move_rect_translates_both():
    new = move_rect(0.2, 0.3, 0.6, 0.7, 0.1, 0.1)
    assert normalize(*new) == pytest.approx((0.3, 0.4, 0.7, 0.8))


def test_move_rect_clamps_preserving_size():
    # width=height=0.4. +0.5 이동 → 우/하 벽에 닿아 크기 유지하며 멈춤.
    new = move_rect(0.2, 0.3, 0.6, 0.7, 0.5, 0.5)
    left, top, right, bottom = normalize(*new)
    assert (left, top, right, bottom) == pytest.approx((0.6, 0.6, 1.0, 1.0))


def test_move_rect_clamps_left_top():
    new = move_rect(0.2, 0.3, 0.6, 0.7, -0.5, -0.5)
    left, top, right, bottom = normalize(*new)
    assert (left, top, right, bottom) == pytest.approx((0.0, 0.0, 0.4, 0.4))
