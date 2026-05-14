"""AutoEditWorker — analyzer 순차 실행 QThread.

UI thread 와는 Qt Signal 로만 통신. analyzer 가 raise 해도 다음 analyzer 계속
(graceful degradation — 한 알고리즘 실패해도 자동편집 전체 안 멈춤).
"""
from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .result import AutoEditResult
from .analyzers.base import Analyzer, AnalyzerCancelled


class AutoEditWorker(QThread):
    # (label, fraction 0~1) — 진행률 표시.
    progress_updated = Signal(str, float)
    # AutoEditResult + 실패한 analyzer 이름 리스트.
    result_ready = Signal(object, list)

    def __init__(
        self,
        *,
        media_path: Path,
        source_hash: str,
        whisper_model: str,
        analyzers: list[tuple[str, Analyzer]],
    ) -> None:
        super().__init__()
        self._media_path = media_path
        self._source_hash = source_hash
        self._whisper_model = whisper_model
        self._analyzers = analyzers
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def run(self) -> None:
        n = len(self._analyzers)
        result = AutoEditResult(source_hash=self._source_hash)
        failed: list[str] = []
        for i, (key, analyzer) in enumerate(self._analyzers):
            if self._is_cancelled():
                return
            label = f"{analyzer.name} ({i+1}/{n})"
            self.progress_updated.emit(label, i / max(n, 1))
            try:
                def _prog(frac: float, base=i, total=n):
                    self.progress_updated.emit(label, (base + frac) / total)
                payload = analyzer.analyze(
                    self._media_path,
                    progress=_prog,
                    is_cancelled=self._is_cancelled,
                )
                for k, v in payload.items():
                    setattr(result, k, v)
                result.analyzer_versions[key] = analyzer.version
            except AnalyzerCancelled:
                return
            except Exception:
                logging.exception("autoedit analyzer 실패: %s", key)
                failed.append(key)
        self.progress_updated.emit("완료", 1.0)
        self.result_ready.emit(result, failed)
