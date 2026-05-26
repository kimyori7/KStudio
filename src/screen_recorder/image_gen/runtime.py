"""ImageGenRuntime — UI 측 핸들. QThread worker + Signal 어댑터.

[agent/runtime.py] 와 달리 asyncio 안 씀 — 이미지 생성은 단일 작업 단위 (1 prompt → 1
image) + step 콜백만 있으면 충분해 그냥 QThread 가 generate() 동기 호출하고 Signal emit.

수명주기:
- 한 번에 하나의 generation 만 — 진행 중에 generate() 또 부르면 무시.
- cancel() 은 backend.request_cancel() 호출 + UI 는 worker 끝까지 대기 (즉시 다음 step 경계).
- close() 는 worker join + backend.close() (VRAM 해제).
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .backend import ImageGenBackend
from .pixart_sigma_backend import PixArtSigmaBackend

_log = logging.getLogger(__name__)


class _GenWorker(QThread):
    """단일 generation 을 동기 실행하는 QThread.

    step 콜백은 worker 스레드에서 호출 — emit 만 하면 Qt 가 queued connection 으로
    UI 스레드에 마샬링.
    """

    started_sig = Signal()
    step_sig = Signal(int, int)              # (current 1-based, total)
    image_sig = Signal(str)                  # 결과 png 경로
    failed_sig = Signal(str)
    cancelled_sig = Signal()
    load_started_sig = Signal()
    load_finished_sig = Signal()

    def __init__(
        self,
        backend: ImageGenBackend,
        prompt: str,
        params: dict[str, Any],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._prompt = prompt
        self._params = dict(params)

    def run(self) -> None:
        try:
            if not self._backend.is_loaded():
                self.load_started_sig.emit()
                self._backend.load()
                self.load_finished_sig.emit()

            self.started_sig.emit()

            def _step_cb(current: int, total: int) -> None:
                self.step_sig.emit(current, total)

            path = self._backend.generate(
                self._prompt,
                step_cb=_step_cb,
                **self._params,
            )
            self.image_sig.emit(str(path))
        except InterruptedError:
            _log.info("_GenWorker: cancelled")
            self.cancelled_sig.emit()
        except Exception as exc:
            _log.exception("_GenWorker: generate 실패")
            self.failed_sig.emit(str(exc))


class ImageGenRuntime(QObject):
    """ChatPanel 패턴을 따른 UI 핸들 — Signal 만 노출, worker 스레드 숨김."""

    # 사용자에게 노출되는 시그널.
    load_started = Signal()                  # 모델 로드 시작 (콜드 부팅 시)
    load_finished = Signal()                 # 모델 로드 완료
    generation_started = Signal()            # generate 호출 직후
    step_progress = Signal(int, int)         # (current 1-based, total)
    image_ready = Signal(str)                # 결과 png 경로 (문자열)
    generation_failed = Signal(str)
    generation_cancelled = Signal()

    def __init__(
        self,
        backend: Optional[ImageGenBackend] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend or PixArtSigmaBackend()
        self._worker: Optional[_GenWorker] = None
        # 진행 상태 — generate 호출 직후 True, 결과 emit 후 False.
        self._busy = False
        # close() 가 worker join 못해 hang 안 되게 — 최대 대기 시간.
        self._close_join_ms = 500

    # ---- 상태 조회 ----
    def is_busy(self) -> bool:
        return self._busy

    def is_model_loaded(self) -> bool:
        return self._backend.is_loaded()

    # ---- 작업 트리거 ----
    def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 20,
        guidance_scale: float = 4.5,
        seed: Optional[int] = None,
    ) -> bool:
        """generate 시작. 이미 진행 중이면 False, 시작했으면 True."""
        if self._busy:
            _log.info("ImageGenRuntime.generate: 이미 진행 중 — 무시")
            return False
        if not prompt or not prompt.strip():
            self.generation_failed.emit("프롬프트가 비어있습니다")
            return False

        self._busy = True
        params = {
            "width": int(width),
            "height": int(height),
            "num_inference_steps": int(num_inference_steps),
            "guidance_scale": float(guidance_scale),
            "seed": None if seed is None or seed < 0 else int(seed),
        }
        worker = _GenWorker(self._backend, prompt, params, parent=self)
        worker.load_started_sig.connect(self.load_started)
        worker.load_finished_sig.connect(self.load_finished)
        worker.started_sig.connect(self.generation_started)
        worker.step_sig.connect(self.step_progress)
        worker.image_sig.connect(self._on_image_ready)
        worker.failed_sig.connect(self._on_failed)
        worker.cancelled_sig.connect(self._on_cancelled)
        # worker 가 종료되면 정리 — Qt finished 시그널.
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()
        return True

    def cancel(self) -> None:
        """다음 step 경계에서 generate 중단 요청. UI 가 호출."""
        if not self._busy:
            return
        try:
            self._backend.request_cancel()
        except Exception:
            _log.exception("backend.request_cancel raised — 무시")

    def close(self) -> None:
        """앱 종료 hook — cancel 요청 + worker join (짧게) + backend.close().

        worker 가 forward pass 중간이면 한 step (~1초) 까지 기다림. 그 이상 hang
        하지 않도록 _close_join_ms 로 제한.
        """
        if self._worker is not None:
            try:
                self._backend.request_cancel()
            except Exception:
                pass
            try:
                # 최대 _close_join_ms 만 기다림. timeout 시 daemon 으로 두고 진행.
                self._worker.wait(self._close_join_ms)
            except Exception:
                pass
            self._worker = None
        try:
            self._backend.close()
        except Exception:
            _log.exception("backend.close raised — 무시")
        self._busy = False

    # ---- worker 종료 처리 ----
    def _on_image_ready(self, path: str) -> None:
        self.image_ready.emit(path)

    def _on_failed(self, msg: str) -> None:
        self.generation_failed.emit(msg)

    def _on_cancelled(self) -> None:
        self.generation_cancelled.emit()

    def _on_worker_finished(self) -> None:
        self._busy = False
        # worker 인스턴스 정리는 다음 generate 호출 시 새 worker 로 덮어쓰기 때 자동.
