"""MagicWandTool — 클릭한 색과 유사한 영역을 두 단계로 처리.

1단계 (클릭): 클릭 위치 기준 BFS 플러드-필을 계산한 뒤, 그 픽셀들을 캔버스 위에
           반투명 빨강 오버레이로 띄워 사용자가 미리 본다. 마스크 자체는 아직
           바꾸지 않음.
2단계 (Enter/Delete): commit_requested 시그널로 MainWindow 에 알림 → 그쪽에서
                      MagicWandApplyCommand 를 푸시해 마스크를 실제로 적용.
       (Esc): cancelled 시그널 — 보류 중인 미리보기를 폐기.
       (다른 곳 클릭): 새 위치로 재계산해 보류 미리보기 갱신.

이렇게 둘로 나눈 이유: 한 번 클릭으로 즉시 픽셀이 사라지면 사용자가 의도와 다른 영역을
선택해도 Ctrl+Z 로 되돌리기 전에 이미 마스크가 바뀐 상태가 됨 — "보고 결정" 흐름이 더
직관적.
"""
from __future__ import annotations
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer
from ..operations.magic_wand import compute_magic_wand_mask_with_rect
from .base import Tool


class _Emitter(QObject):
    # (layer_id, new_mask, affected_layer_rect)
    commit_requested = Signal(int, QImage, object)
    cancelled = Signal()
    # 미리보기 상태가 바뀌었음을 외부에 알리는 용도 (selection bbox 갱신 등).
    preview_changed = Signal(int, object)   # (layer_id, affected_layer_rect | None)


class MagicWandTool(Tool):
    name = "magic_wand"

    def __init__(self, stack: LayerStack, tolerance: int = 32) -> None:
        super().__init__()
        self._stack = stack
        self.tolerance = tolerance
        self._scene: Optional[QGraphicsScene] = None
        self._overlay_item: Optional[QGraphicsPixmapItem] = None
        self._pending_layer_id: Optional[int] = None
        self._pending_new_mask: Optional[QImage] = None
        self._pending_affected_local: Optional[QRect] = None
        self._emitter = _Emitter()
        self.commit_requested = self._emitter.commit_requested
        self.cancelled = self._emitter.cancelled
        self.preview_changed = self._emitter.preview_changed

    # --- Tool API ---
    def activated(self, scene: QGraphicsScene) -> None:
        self._scene = scene

    def deactivated(self, scene: QGraphicsScene) -> None:
        self._clear_pending(emit_preview_change=True)
        self._scene = None

    def has_pending(self) -> bool:
        return self._pending_new_mask is not None

    # --- Mouse / Key ---
    def mouse_press(self, scene: QGraphicsScene, scene_pos: QPointF) -> None:
        layer = self._stack.active_layer()
        if not isinstance(layer, ImageLayer):
            return
        lx = int(scene_pos.x() - layer.offset.x())
        ly = int(scene_pos.y() - layer.offset.y())
        old_mask = layer.mask
        # 크롭은 lazy(pixmap 원본 유지, offset/canvas_size 만 변경)이므로 flood-fill 을
        # 현재 캔버스 창 안으로 제한한다 — 잘려나간 테두리로 선택이 번지지 않도록.
        cs = self._stack.canvas_size
        bounds = QRect(
            -int(layer.offset.x()), -int(layer.offset.y()), cs.width(), cs.height()
        )
        new_mask, affected = compute_magic_wand_mask_with_rect(
            layer.pixmap, old_mask, lx, ly, self.tolerance, bounds=bounds,
        )
        if affected is None:
            # 클릭한 픽셀에서 아무 영역도 못 잡음 — 기존 보류는 유지.
            return
        self._pending_layer_id = layer.id
        # 확정(commit) 시엔 누적 마스크(new_mask) 를 그대로 적용 — 이전에 지운 영역이
        # 유지돼야 하므로. 단, 미리보기 오버레이는 이번 클릭으로 '새로' 선택된 픽셀만
        # 보여 줘야 한다 (이미 지운 영역이 새 선택에 함께 빨갛게 뜨던 버그 수정).
        self._pending_new_mask = new_mask
        self._pending_affected_local = affected
        self._render_overlay(layer, _delta_preview_mask(old_mask, new_mask))
        self._emitter.preview_changed.emit(layer.id, QRect(affected))

    def key_enter(self, scene: QGraphicsScene) -> None:
        self._commit()

    def key_delete(self, scene: QGraphicsScene) -> bool:
        # 보류 중인 미리보기가 있으면 Delete 도 확정으로 처리 — 사용자가 "지우기"
        # 의도로 누른 키이므로. 캔버스의 일반 selection 삭제로 흐르지 않도록 True 반환.
        if not self.has_pending():
            return False
        self._commit()
        return True

    def _commit(self) -> None:
        if not self.has_pending():
            return
        layer_id = int(self._pending_layer_id)
        mask = self._pending_new_mask
        affected = self._pending_affected_local
        # 시그널 emit 전에 미리보기는 정리 — MainWindow 의 명령 적용 후엔 더 안 보여도 됨.
        self._clear_pending(emit_preview_change=False)
        self._emitter.commit_requested.emit(
            layer_id, mask, QRect(affected) if affected is not None else None
        )

    def key_escape(self, scene: QGraphicsScene) -> None:
        if not self.has_pending():
            return
        self._clear_pending(emit_preview_change=True)
        self._emitter.cancelled.emit()

    # --- 내부 ---
    def _render_overlay(self, layer: ImageLayer, preview_mask: QImage) -> None:
        if self._scene is None:
            return
        if self._overlay_item is None:
            self._overlay_item = QGraphicsPixmapItem()
            self._overlay_item.setZValue(900_000)
            self._overlay_item.setAcceptedMouseButtons(Qt.NoButton)
            self._scene.addItem(self._overlay_item)
        preview = _build_preview_image(preview_mask)
        self._overlay_item.setPixmap(QPixmap.fromImage(preview))
        self._overlay_item.setPos(layer.offset)

    def _clear_pending(self, *, emit_preview_change: bool) -> None:
        if self._overlay_item is not None and self._scene is not None:
            if self._overlay_item.scene() is self._scene:
                self._scene.removeItem(self._overlay_item)
        self._overlay_item = None
        had_pending = self._pending_new_mask is not None
        layer_id = self._pending_layer_id
        self._pending_new_mask = None
        self._pending_affected_local = None
        self._pending_layer_id = None
        if had_pending and emit_preview_change and layer_id is not None:
            self._emitter.preview_changed.emit(layer_id, None)


def _delta_preview_mask(old_mask: Optional[QImage], new_mask: QImage) -> QImage:
    """이번 클릭으로 '새로' 선택된 픽셀만 0(=하이라이트) 으로 둔 미리보기용 마스크.

    new_mask 는 기존 마스크 위에 누적된 결과(0=선택). 그 중 기존 마스크에서 이미
    0 이던 픽셀(=이미 지운 영역)은 255 로 되돌려, 미리보기 오버레이가 이번에 새로
    선택된 영역만 빨갛게 칠하도록 한다. 마스크 자체(commit 대상)는 누적이 맞고,
    오버레이만 delta 로 보여 주는 것 — 이미 지운 영역이 새 선택에 함께 표시되던 버그 수정.

    old_mask 가 None 이거나 크기가 다르면 누적 분리가 불가능하므로 new_mask 전체를
    미리보기로 사용 (첫 클릭은 정확히 이번 선택 = 전체).
    """
    nm = new_mask.convertToFormat(QImage.Format_Grayscale8)
    w, h = nm.width(), nm.height()
    bpl = nm.bytesPerLine()
    new_arr = np.frombuffer(bytes(nm.constBits())[: bpl * h], dtype=np.uint8).reshape(
        h, bpl
    )[:, :w]
    if old_mask is None or old_mask.size() != nm.size():
        return nm.copy()
    om = old_mask.convertToFormat(QImage.Format_Grayscale8)
    obpl = om.bytesPerLine()
    old_arr = np.frombuffer(bytes(om.constBits())[: obpl * h], dtype=np.uint8).reshape(
        h, obpl
    )[:, :w]
    delta = new_arr.copy()
    # 기존에 이미 0(지움) 이던 픽셀은 미리보기에서 제외 → 255.
    delta[(new_arr == 0) & (old_arr == 0)] = 255
    out = QImage(delta.tobytes(), w, h, w, QImage.Format_Grayscale8)
    return out.copy()


def _build_preview_image(new_mask: QImage) -> QImage:
    """Grayscale8 마스크에서 0(=선택됨) 인 픽셀을 반투명 빨강으로 칠한 ARGB32 QImage 반환.

    numpy 로 한번에 처리해 1080p 마스크도 수십 ms 내에 끝나도록 한다.
    """
    m = new_mask.convertToFormat(QImage.Format_Grayscale8)
    w, h = m.width(), m.height()
    bpl = m.bytesPerLine()
    buf = bytes(m.constBits())[: bpl * h]
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpl)[:, :w]
    sel = (arr == 0)
    # ARGB32 는 little-endian 메모리에서 [B, G, R, A] 순.
    out_arr = np.zeros((h, w, 4), dtype=np.uint8)
    out_arr[sel] = [50, 50, 230, 130]   # 약간의 파란기 섞인 빨강, alpha 130
    out = QImage(out_arr.tobytes(), w, h, w * 4, QImage.Format_ARGB32)
    # numpy 버퍼는 함수 종료 후 GC 되므로 QImage.copy() 로 자체 복사 보장.
    return out.copy()
