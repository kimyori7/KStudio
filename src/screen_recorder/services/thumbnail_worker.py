"""ThumbnailService — Lane 의 썸네일 요청을 QThreadPool 로 비동기 실행 + 시그널.

필름스트립용 다중 슬롯 — 같은 segment_id 안에서 ms 가 다른 여러 요청을 동시에 처리.
Dedup 키도 (segment_id, ms) — 한 segment 의 같은 시점은 1개만 dispatch.
"""
from __future__ import annotations
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .thumbnail_extractor import ThumbnailExtractor


@dataclass(frozen=True)
class ThumbnailRequest:
    segment_id: str
    src: str
    ms: int


class _Runnable(QRunnable):
    """ThumbnailExtractor.extract_sync 를 QThreadPool 에서 실행 후 service 에 결과 전달."""

    def __init__(self, service: "ThumbnailService", req: ThumbnailRequest) -> None:
        super().__init__()
        self._svc = service
        self._req = req

    def run(self) -> None:   # type: ignore[override]
        img = self._svc._extractor.extract_sync(self._req.src, self._req.ms)
        if img is not None:
            self._svc.thumbnail_ready.emit(
                self._req.segment_id, int(self._req.ms), img,
            )
        self._svc._on_done(self._req.segment_id, self._req.ms)


class ThumbnailService(QObject):
    """ThumbnailExtractor 를 Qt 비동기 인터페이스로 감싼다.

    Dedup 키 = (segment_id, ms) — 같은 시점 여러 번 요청해도 1개만 dispatch.
    """
    thumbnail_ready = Signal(str, int, object)   # (segment_id, ms, QImage)

    def __init__(self, extractor: ThumbnailExtractor) -> None:
        super().__init__()
        self._extractor = extractor
        self._pending: set[tuple[str, int]] = set()

    def request(self, req: ThumbnailRequest) -> None:
        """캐시 히트면 즉시 시그널 emit, 미스면 worker 디스패치."""
        cached, was = self._extractor.get_or_none(req.src, req.ms)
        if was and cached is not None:
            self.thumbnail_ready.emit(req.segment_id, int(req.ms), cached)
            return
        key = (req.segment_id, int(req.ms))
        if key in self._pending:
            return
        self._pending.add(key)
        runnable = _Runnable(self, req)
        QThreadPool.globalInstance().start(runnable)

    def _on_done(self, segment_id: str, ms: int) -> None:
        self._pending.discard((segment_id, int(ms)))
