"""BackgroundRemovalCommand — rembg 기반 배경 제거 (마스크 추가)."""
from __future__ import annotations
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QUndoCommand

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer


def _default_remove_bg(image: QImage) -> QImage:
    """rembg 호출 → 알파 마스크 (greyscale) 반환.
    예외 시 호출자가 try/except 로 잡음.
    """
    from PIL import Image
    import io
    from rembg import remove

    # QImage → PIL → rembg → PIL(RGBA) → mask QImage(Grayscale8)
    src = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = src.bits()
    pil_in = Image.frombytes("RGBA", (src.width(), src.height()),
                             bytes(ptr), "raw", "RGBA")
    pil_out = remove(pil_in).convert("RGBA")
    alpha = pil_out.split()[-1]   # alpha 채널만 추출
    raw = alpha.tobytes()
    mask = QImage(raw, alpha.width, alpha.height, alpha.width,
                  QImage.Format_Grayscale8).copy()
    return mask


class _Worker(QRunnable):
    def __init__(self, image: QImage, fn: Callable[[QImage], QImage], cb: Callable):
        super().__init__()
        self._image = image
        self._fn = fn
        self._cb = cb

    def run(self) -> None:
        try:
            mask = self._fn(self._image)
            self._cb(mask, None)
        except Exception as e:
            self._cb(None, e)


class _Emitter(QObject):
    finished = Signal(bool)            # success
    failed = Signal(str)


class BackgroundRemovalCommand(QUndoCommand):
    def __init__(
        self,
        stack: LayerStack,
        layer_id: int,
        remove_bg_fn: Optional[Callable[[QImage], QImage]] = None,
    ) -> None:
        super().__init__("배경 제거")
        self._stack = stack
        self._layer_id = layer_id
        self._fn = remove_bg_fn or _default_remove_bg
        self._mask: Optional[QImage] = None
        self._prev_mask: Optional[QImage] = None
        self._emitter = _Emitter()
        self.finished = self._emitter.finished
        self.failed = self._emitter.failed

    def run_sync(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        assert isinstance(layer, ImageLayer)
        self._mask = self._fn(layer.composed_pixmap())

    def run_async(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        assert isinstance(layer, ImageLayer)
        worker = _Worker(layer.composed_pixmap(), self._fn, self._on_done)
        QThreadPool.globalInstance().start(worker)

    def _on_done(self, mask: Optional[QImage], err: Optional[Exception]) -> None:
        if err is not None:
            self._emitter.failed.emit(str(err))
            self._emitter.finished.emit(False)
            return
        self._mask = mask
        self._emitter.finished.emit(True)

    def redo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer) or self._mask is None:
            return
        self._prev_mask = layer.mask
        layer.mask = self._mask
        self._stack.layers_changed.emit()

    def undo(self) -> None:
        layer = self._stack.get_layer(self._layer_id)
        if not isinstance(layer, ImageLayer):
            return
        layer.mask = self._prev_mask
        self._stack.layers_changed.emit()
