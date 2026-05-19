"""AutoEditCoordinator — UI 와 worker 사이 마샬링.

VideoTab 의 🪄 버튼 → coordinator.run() → 캐시 확인 → 없으면 worker 시작
→ 진행률 dialog → 완료 시 result_ready emit.
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from .worker import AutoEditWorker
from .cache import build_key, load, save

if TYPE_CHECKING:
    from .analyzers.base import Analyzer


class AutoEditCoordinator(QObject):
    """버튼 클릭 → 분석 → result emit. 진행률 dialog 는 UI 측에서 wire."""

    progress_updated = Signal(str, float)
    result_ready = Signal(object, list)         # (AutoEditResult, failed_names)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._analyzers: list[tuple[str, "Analyzer"]] = []
        self._worker: AutoEditWorker | None = None

    def set_analyzers(self, analyzers: list[tuple[str, "Analyzer"]]) -> None:
        self._analyzers = analyzers

    def run(
        self,
        *,
        media_path: Path,
        source_hash: str,
        whisper_model: str,
        cache_dir: Path,
    ) -> None:
        # 캐시 hit 즉시 emit.
        versions = {k: a.version for k, a in self._analyzers}
        key = build_key(
            source_hash=source_hash,
            whisper_model=whisper_model,
            analyzer_versions=versions,
        )
        cached = load(cache_dir, key)
        if cached is not None:
            self.result_ready.emit(cached, [])
            return

        # miss → worker 시작.
        self._worker = AutoEditWorker(
            media_path=media_path,
            source_hash=source_hash,
            whisper_model=whisper_model,
            analyzers=self._analyzers,
        )
        self._worker.progress_updated.connect(self.progress_updated.emit)
        self._worker.result_ready.connect(
            lambda r, failed: self._on_worker_done(r, failed, cache_dir, key)
        )
        self._worker.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self.cancelled.emit()

    def _on_worker_done(self, result, failed, cache_dir: Path, key: str) -> None:
        try:
            save(cache_dir, key, result)
        except OSError:
            pass
        self.result_ready.emit(result, failed)
