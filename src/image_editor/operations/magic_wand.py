"""MagicWandCommand — 클릭 픽셀 색 + 허용 범위 (tolerance) 기준 BFS flood-fill,
선택된 영역을 ImageLayer.mask 에서 0(=transparent)으로 빼는 undo-able 커맨드.

기존 마스크가 있으면 그 위에 빼기 연산. 없으면 전체 white(=opaque) 마스크로 시작.
"""
from __future__ import annotations
from collections import deque
from typing import Optional

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QUndoCommand

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer


def compute_magic_wand_mask(
    pixmap: QImage,
    current_mask: Optional[QImage],
    start_x: int,
    start_y: int,
    tolerance: int,
) -> QImage:
    """클릭 픽셀과 비슷한 색 영역을 BFS 로 찾아 마스크에서 빼기.

    반환: Format_Grayscale8 의 새 마스크 QImage.
    영향 영역의 bounding rect 가 필요하면 `compute_magic_wand_mask_with_rect` 사용.
    """
    new_mask, _ = compute_magic_wand_mask_with_rect(
        pixmap, current_mask, start_x, start_y, tolerance,
    )
    return new_mask


def compute_magic_wand_mask_with_rect(
    pixmap: QImage,
    current_mask: Optional[QImage],
    start_x: int,
    start_y: int,
    tolerance: int,
) -> tuple[QImage, Optional[QRect]]:
    """`compute_magic_wand_mask` + 영향 픽셀의 bounding rect 반환 (marching ants 용).

    rect 는 layer-local 좌표. 영향 픽셀이 없으면 None.
    """
    src = pixmap.convertToFormat(QImage.Format_ARGB32)
    w, h = src.width(), src.height()
    if not (0 <= start_x < w and 0 <= start_y < h):
        # 범위 밖 — 변경 없음
        if current_mask is not None and current_mask.size() == QSize(w, h):
            return current_mask.copy(), None
        m = QImage(w, h, QImage.Format_Grayscale8)
        m.fill(255)
        return m, None

    # 시작 색
    sc = src.pixel(start_x, start_y)
    sr, sg, sb = (sc >> 16) & 0xFF, (sc >> 8) & 0xFF, sc & 0xFF
    tol_sq = max(0, tolerance) ** 2 * 3

    # 결과 마스크 초기화
    if current_mask is not None and current_mask.size() == QSize(w, h):
        new_mask = current_mask.convertToFormat(QImage.Format_Grayscale8).copy()
    else:
        new_mask = QImage(w, h, QImage.Format_Grayscale8)
        new_mask.fill(255)

    # BFS — 단순 Python 루프 (1080p 이내 스크린샷 기준 충분)
    visited = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()
    q.append((start_x, start_y))
    min_x = w
    min_y = h
    max_x = -1
    max_y = -1
    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h:
            continue
        idx = y * w + x
        if visited[idx]:
            continue
        c = src.pixel(x, y)
        r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
        if (r - sr) ** 2 + (g - sg) ** 2 + (b - sb) ** 2 > tol_sq:
            continue
        visited[idx] = 1
        new_mask.setPixel(x, y, 0)   # transparent
        if x < min_x:
            min_x = x
        if y < min_y:
            min_y = y
        if x > max_x:
            max_x = x
        if y > max_y:
            max_y = y
        q.append((x + 1, y))
        q.append((x - 1, y))
        q.append((x, y + 1))
        q.append((x, y - 1))
    if max_x < min_x or max_y < min_y:
        return new_mask, None
    affected = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
    return new_mask, affected


class MagicWandCommand(QUndoCommand):
    """클릭 위치 기준 flood-fill 로 마스크에서 영역을 빼는 undo 커맨드."""

    def __init__(
        self,
        stack: LayerStack,
        layer_id: int,
        start_x: int,
        start_y: int,
        tolerance: int,
    ) -> None:
        super().__init__("마술봉")
        self._stack = stack
        self._layer_id = layer_id
        self._x = start_x
        self._y = start_y
        self._tolerance = tolerance
        self._new_mask: Optional[QImage] = None
        self._prev_mask: Optional[QImage] = None
        self._affected_local: Optional[QRect] = None
        self._computed = False

    def _compute_if_needed(self) -> None:
        if self._computed:
            return
        layer = self._stack.get_layer(self._layer_id)
        assert isinstance(layer, ImageLayer)
        self._new_mask, self._affected_local = compute_magic_wand_mask_with_rect(
            layer.pixmap, layer.mask, self._x, self._y, self._tolerance,
        )
        self._computed = True

    def affected_layer_rect(self) -> Optional[QRect]:
        """선택된 픽셀들의 bounding rect (layer-local 좌표). 없으면 None.

        redo 직후 호출하면 의미 있음 (compute 결과가 캐시됨).
        """
        return None if self._affected_local is None else QRect(self._affected_local)

    def redo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        self._compute_if_needed()
        if self._new_mask is None:
            return
        self._prev_mask = layer.mask
        layer.mask = self._new_mask
        self._stack.layers_changed.emit()

    def undo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        layer.mask = self._prev_mask
        self._stack.layers_changed.emit()
