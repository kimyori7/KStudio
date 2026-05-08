"""ThumbnailService — Lane 의 썸네일 요청을 QThreadPool 로 비동기 실행 + 시그널.

요청은 (segment_id, src, ms) — 캐시 히트면 즉시 동기 시그널, 미스면 QRunnable
디스패치 후 추출 완료 시 signal emit.
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
        # 시그널 발화는 service 가 (QObject 라 thread-safe).
        if img is not None:
            self._svc.thumbnail_ready.emit(self._req.segment_id, img)
        # pending 클리어 — 추출 성공/실패 무관.
        self._svc._on_done(self._req.segment_id)


class ThumbnailService(QObject):
    """ThumbnailExtractor 를 Qt 비동기 인터페이스로 감싼다.

    같은 segment_id 가 동시에 여러 번 요청되면 첫 번째만 디스패치 (dedupe).
    추출 실패 시 시그널 발화 안 함 (lane 이 그냥 placeholder 유지).
    """
    thumbnail_ready = Signal(str, object)   # segment_id, QImage

    def __init__(self, extractor: ThumbnailExtractor) -> None:
        super().__init__()
        self._extractor = extractor
        self._pending: set[str] = set()

    def request(self, req: ThumbnailRequest) -> None:
        """캐시 히트면 즉시 시그널 emit, 미스면 worker 디스패치."""
        cached, was = self._extractor.get_or_none(req.src, req.ms)
        if was and cached is not None:
            self.thumbnail_ready.emit(req.segment_id, cached)
            return
        if req.segment_id in self._pending:
            return
        self._pending.add(req.segment_id)
        runnable = _Runnable(self, req)
        QThreadPool.globalInstance().start(runnable)

    def _on_done(self, segment_id: str) -> None:
        self._pending.discard(segment_id)
