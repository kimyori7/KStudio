"""SelectionOverlay — 캔버스 위에 떠 있는 marching-ants 사각형.

EditTab 의 selection 상태(`Optional[QRect]`)를 시각화한다. 같은 오버레이를
다음 두 가지에 함께 사용:

1. SelectionTool 로 드래그한 사각형 영역.
2. MagicWandCommand 가 막 제거한 픽셀들의 bounding rect (마술봉 marching ants).

애니메이션: QTimer 로 dash offset 을 주기적으로 바꿔 marching effect 발생.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import QObject, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene


_MARCH_INTERVAL_MS = 80
_DASH_PATTERN = [4.0, 4.0]
_PEN_WIDTH = 0  # cosmetic — zoom 무관 1px


class SelectionModel(QObject):
    """단일 사각형 selection 상태. EditTab 이 소유."""

    changed = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._rect: Optional[QRect] = None

    def rect(self) -> Optional[QRect]:
        return None if self._rect is None else QRect(self._rect)

    def has_selection(self) -> bool:
        return self._rect is not None and self._rect.width() > 0 and self._rect.height() > 0

    def set_rect(self, rect: Optional[QRect]) -> None:
        if rect is None:
            if self._rect is None:
                return
            self._rect = None
        else:
            r = QRect(rect).normalized()
            if r.width() <= 0 or r.height() <= 0:
                if self._rect is None:
                    return
                self._rect = None
            elif self._rect is not None and self._rect == r:
                return
            else:
                self._rect = r
        self.changed.emit()

    def clear(self) -> None:
        self.set_rect(None)


class SelectionOverlay(QObject):
    """장면 위에 marching-ants 사각형 한 개를 그린다 (단일 인스턴스).

    SelectionModel 변화에 따라 자동 갱신. 활성 시 QTimer 로 dash offset 진행.
    """

    def __init__(self, scene: QGraphicsScene, model: SelectionModel,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._scene = scene
        self._model = model
        self._item_white: Optional[QGraphicsRectItem] = None
        self._item_black: Optional[QGraphicsRectItem] = None
        self._dash_offset: float = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_MARCH_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._model.changed.connect(self._refresh)
        self._refresh()

    def _ensure_items(self) -> None:
        if self._item_white is None:
            white = QGraphicsRectItem()
            pen_w = QPen(QColor(255, 255, 255))
            pen_w.setWidth(_PEN_WIDTH)
            pen_w.setCosmetic(True)
            pen_w.setStyle(Qt.SolidLine)
            white.setPen(pen_w)
            white.setBrush(Qt.NoBrush)
            white.setZValue(99_999)
            self._item_white = white
            self._scene.addItem(white)
        if self._item_black is None:
            black = QGraphicsRectItem()
            pen_b = QPen(QColor(0, 0, 0))
            pen_b.setWidth(_PEN_WIDTH)
            pen_b.setCosmetic(True)
            pen_b.setStyle(Qt.CustomDashLine)
            pen_b.setDashPattern(_DASH_PATTERN)
            black.setPen(pen_b)
            black.setBrush(Qt.NoBrush)
            black.setZValue(100_000)
            self._item_black = black
            self._scene.addItem(black)

    def _remove_items(self) -> None:
        for it_attr in ("_item_white", "_item_black"):
            it = getattr(self, it_attr)
            if it is not None and it.scene() is self._scene:
                self._scene.removeItem(it)
            setattr(self, it_attr, None)

    def _refresh(self) -> None:
        rect = self._model.rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            self._remove_items()
            self._timer.stop()
            return
        self._ensure_items()
        rf = QRectF(rect)
        assert self._item_white is not None and self._item_black is not None
        self._item_white.setRect(rf)
        self._item_black.setRect(rf)
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        if self._item_black is None:
            return
        self._dash_offset = (self._dash_offset + 1.0) % (_DASH_PATTERN[0] + _DASH_PATTERN[1])
        pen = self._item_black.pen()
        pen.setDashOffset(self._dash_offset)
        self._item_black.setPen(pen)

    def detach(self) -> None:
        """해제 — scene 에서 아이템 제거 + 타이머 정지."""
        self._timer.stop()
        self._remove_items()
        try:
            self._model.changed.disconnect(self._refresh)
        except (TypeError, RuntimeError):
            pass
