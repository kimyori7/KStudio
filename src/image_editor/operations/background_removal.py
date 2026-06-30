"""BackgroundRemovalCommand — rembg 기반 배경 제거 (마스크 추가)."""
from __future__ import annotations
import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QUndoCommand

from ..layer_model import LayerStack
from ..layers.image_layer import ImageLayer

_log = logging.getLogger(__name__)

_truststore_injected = False


def _ensure_truststore() -> None:
    """rembg 모델 다운로드(pooch/HTTPS)가 기업 프록시 등의 TLS 인터셉트나 설치본(.exe)의
    certifi 경로 문제로 CERTIFICATE_VERIFY_FAILED 나지 않도록, OS(Windows) 인증서 저장소를
    쓰게 한다. yt-dlp 다운로드와 동일한 패턴 — 프로세스 전역·1회·신뢰 추가만(안전, pip 도 사용)."""
    global _truststore_injected
    if _truststore_injected:
        return
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        _log.debug("truststore inject 건너뜀 (rembg)", exc_info=True)
    finally:
        _truststore_injected = True   # 실패해도 매번 재시도하지 않음


def _default_remove_bg(image: QImage, *, model_name: str = "u2net") -> QImage:
    """rembg 호출 → 알파 마스크 (greyscale) 반환.

    model_name 으로 rembg 모델을 선택 (u2net / isnet-general-use / birefnet-general 등).
    첫 사용 시 ~/.u2net/ 등에 모델이 다운로드된다 (rembg 가 자체 처리).
    예외 시 호출자가 try/except 로 잡음.
    """
    from PIL import Image
    from rembg import new_session, remove

    _ensure_truststore()   # 모델 다운로드 전 OS 인증서 저장소 활성화 (기업 프록시/frozen 대비)
    # QImage → PIL → rembg → PIL(RGBA) → mask QImage(Grayscale8)
    src = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = src.bits()
    pil_in = Image.frombytes("RGBA", (src.width(), src.height()),
                             bytes(ptr), "raw", "RGBA")
    session = new_session(model_name)
    pil_out = remove(pil_in, session=session).convert("RGBA")
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
            # 실패 원인을 app.log 에 남긴다 — 그동안 다이얼로그로만 떠 추적이 안 됐음.
            _log.exception("배경 제거(rembg) 실패: %s", e)
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
        *,
        model_name: str = "u2net",
    ) -> None:
        super().__init__("배경 제거")
        self._stack = stack
        self._layer_id = layer_id
        # remove_bg_fn 이 주어지면(테스트용) model_name 은 무시된다.
        if remove_bg_fn is not None:
            self._fn: Callable[[QImage], QImage] = remove_bg_fn
        else:
            self._fn = lambda img, m=model_name: _default_remove_bg(img, model_name=m)
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
