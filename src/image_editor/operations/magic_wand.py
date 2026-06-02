"""MagicWandCommand — 클릭 픽셀 색 + 허용 범위 (tolerance) 기준 connected-component
flood-fill, 선택된 영역을 ImageLayer.mask 에서 0(=transparent)으로 빼는 undo-able 커맨드.

기존 마스크가 있으면 그 위에 빼기 연산. 없으면 전체 white(=opaque) 마스크로 시작.
"""
from __future__ import annotations
from typing import Optional

import numpy as np
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QUndoCommand
from scipy.ndimage import label as _ndi_label

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer


def compute_magic_wand_mask(
    pixmap: QImage,
    current_mask: Optional[QImage],
    start_x: int,
    start_y: int,
    tolerance: int,
    bounds: Optional[QRect] = None,
) -> QImage:
    """클릭 픽셀과 비슷한 색 영역을 BFS 로 찾아 마스크에서 빼기.

    반환: Format_Grayscale8 의 새 마스크 QImage.
    영향 영역의 bounding rect 가 필요하면 `compute_magic_wand_mask_with_rect` 사용.
    """
    new_mask, _ = compute_magic_wand_mask_with_rect(
        pixmap, current_mask, start_x, start_y, tolerance, bounds=bounds,
    )
    return new_mask


def compute_magic_wand_mask_with_rect(
    pixmap: QImage,
    current_mask: Optional[QImage],
    start_x: int,
    start_y: int,
    tolerance: int,
    bounds: Optional[QRect] = None,
) -> tuple[QImage, Optional[QRect]]:
    """`compute_magic_wand_mask` + 영향 픽셀의 bounding rect 반환 (marching ants 용).

    rect 는 layer-local 좌표. 영향 픽셀이 없으면 None.

    bounds (layer-local QRect) 를 주면 flood-fill 을 그 영역 안으로 제한한다.
    크롭은 lazy — pixmap 은 원본 크기 그대로이고 offset/canvas_size 만 바뀌므로, 캔버스
    밖(잘려나간 테두리) 픽셀이 색으로 연결돼 있어도 선택에 끌려들어오지 않도록 캔버스 창
    (= QRect(-offset, canvas_size)) 을 bounds 로 넘긴다. None 이면 pixmap 전체가 대상.
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

    # 결과 마스크 초기화 (벡터화된 마스크 갱신은 numpy 로 일괄 처리)
    if current_mask is not None and current_mask.size() == QSize(w, h):
        cur = current_mask.convertToFormat(QImage.Format_Grayscale8)
        cur_buf = np.frombuffer(cur.constBits(), dtype=np.uint8).reshape(
            h, cur.bytesPerLine()
        )[:, :w].copy()
    else:
        cur_buf = np.full((h, w), 255, dtype=np.uint8)

    # ARGB32 little-endian: 메모리 byte 순 = B,G,R,A → R=byte 2, G=byte 1, B=byte 0
    src_buf = np.frombuffer(src.constBits(), dtype=np.uint8).reshape(
        h, src.bytesPerLine()
    )[:, : w * 4].reshape(h, w, 4)
    r = src_buf[:, :, 2].astype(np.int32)
    g = src_buf[:, :, 1].astype(np.int32)
    b = src_buf[:, :, 0].astype(np.int32)
    sr, sg, sb = int(r[start_y, start_x]), int(g[start_y, start_x]), int(b[start_y, start_x])
    tol_sq = max(0, tolerance) ** 2 * 3
    similar = (r - sr) ** 2 + (g - sg) ** 2 + (b - sb) ** 2 <= tol_sq

    if bounds is not None:
        # 캔버스 창(layer-local) 밖 픽셀은 후보에서 제외 → connected-component 가 캔버스
        # 경계에서 멈춰 잘려나간 테두리로 번지지 않는다. (pixmap 범위로 클램프해 안전 인덱싱.)
        x0 = max(0, bounds.left())
        y0 = max(0, bounds.top())
        x1 = min(w, bounds.left() + bounds.width())
        y1 = min(h, bounds.top() + bounds.height())
        in_bounds = np.zeros((h, w), dtype=bool)
        if x1 > x0 and y1 > y0:
            in_bounds[y0:y1, x0:x1] = True
        similar = similar & in_bounds

    # connected-component 라벨링 후 시작 픽셀이 속한 컴포넌트만 추출 — BFS 와 동일
    # 동작이지만 C 구현이라 1080p 가 수십 ms.
    labels, _n = _ndi_label(similar)
    component_id = labels[start_y, start_x]
    if component_id == 0:
        # 시작 픽셀 자체가 임계 조건 밖 (방어적; 정상 흐름에서는 발생 안 함)
        new_mask = QImage(cur_buf.tobytes(), w, h, w, QImage.Format_Grayscale8).copy()
        return new_mask, None
    flood = labels == component_id
    cur_buf[flood] = 0

    new_mask = QImage(cur_buf.tobytes(), w, h, w, QImage.Format_Grayscale8).copy()

    ys, xs = np.where(flood)
    if ys.size == 0:
        return new_mask, None
    affected = QRect(
        int(xs.min()), int(ys.min()),
        int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1),
    )
    return new_mask, affected


class MagicWandApplyCommand(QUndoCommand):
    """미리 계산된 마스크를 ImageLayer.mask 로 교체하는 undo 커맨드.

    MagicWandTool 이 두 단계 (preview → confirm) 로 동작할 때 confirm 단계에서 사용.
    이미 새 마스크가 계산돼 있으므로 redo 시점에 다시 BFS 를 돌리지 않는다.
    """

    def __init__(self, stack: LayerStack, layer_id: int, new_mask: QImage,
                 *, text: str = "마술봉") -> None:
        super().__init__(text)
        self._stack = stack
        self._layer_id = layer_id
        self._new_mask = new_mask
        self._prev_mask: Optional[QImage] = None
        self._captured = False

    def redo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        if not self._captured:
            self._prev_mask = layer.mask
            self._captured = True
        layer.mask = self._new_mask
        self._stack.layers_changed.emit()

    def undo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        layer.mask = self._prev_mask
        self._stack.layers_changed.emit()


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
        # flood-fill 을 현재 캔버스 창(layer-local) 안으로 제한 — 크롭으로 잘려나간
        # 테두리(pixmap 에는 남아 있음)로 선택이 번지지 않도록.
        cs = self._stack.canvas_size
        bounds = QRect(
            -int(layer.offset.x()), -int(layer.offset.y()), cs.width(), cs.height()
        )
        self._new_mask, self._affected_local = compute_magic_wand_mask_with_rect(
            layer.pixmap, layer.mask, self._x, self._y, self._tolerance, bounds=bounds,
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
