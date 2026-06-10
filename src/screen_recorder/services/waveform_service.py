"""오디오 파형 생성(백그라운드) + 캐시. filmstrip/thumbnail 서비스와 같은 패턴.

WaveformJob: ffmpeg 로 PCM 디코드 → compute_peaks → finished(src, peaks).
WaveformService: (src, mtime) 캐시 + no-audio short-circuit + in-flight dedup.
"""
from __future__ import annotations
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..encode.waveform import build_waveform_args, buckets_for, compute_peaks
from .media_probe import has_audio_stream

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_log = logging.getLogger(__name__)


class WaveformJob(QObject):
    """src 의 오디오를 peak 배열로 비동기 추출."""

    finished = Signal(str, list)   # (src, peaks: list[float])
    error = Signal(str, str)       # (src, message)

    def __init__(self, *, ffmpeg_path, src,
                 buckets_per_sec: int = 50, sample_rate: int = 8000,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ffmpeg = Path(ffmpeg_path)
        self._src = str(src)
        # ⚠ 고정 총 bucket 수는 금물: 29분 원본을 5초로 자르면 슬라이스가 5~6 bucket
        # 으로 800px 에 늘어나 평평한 블록이 된다. bucket 밀도를 시간 비례(≈50/초)로
        # 잡아 어떤 슬라이스든 해상도 유지. _run 에서 디코드된 샘플 수로 계산한다.
        self._buckets_per_sec = max(1, int(buckets_per_sec))
        self._sample_rate = int(sample_rate)
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="WaveformJob")
        self._thread.start()

    def _run(self) -> None:
        # no-audio 판정을 워커 스레드에서 (UI 블로킹 방지). 소리 없으면 무거운
        # PCM decode 건너뛰고 빈 peaks emit — 레인이 '소리 없음' 표시.
        if not has_audio_stream(self._src):
            self.finished.emit(self._src, [])
            return
        argv = build_waveform_args(src=self._src, ffmpeg=self._ffmpeg,
                                   sample_rate=self._sample_rate)
        try:
            proc = subprocess.run(argv, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  creationflags=_NO_WINDOW, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.error.emit(self._src, f"ffmpeg 실행 실패: {e}")
            return
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace")[-200:].strip()
            self.error.emit(self._src, f"ffmpeg 실패: {err}")
            return
        try:
            pcm = proc.stdout
            n_samples = len(pcm) // 2   # 16-bit = 2 byte/sample
            bucket_count = buckets_for(n_samples, self._sample_rate,
                                       self._buckets_per_sec)
            peaks = compute_peaks(pcm, bucket_count=bucket_count)
        except Exception as e:   # noqa: BLE001 — 백그라운드 스레드, 죽지 않게
            _log.exception("compute_peaks crashed")
            self.error.emit(self._src, f"peak 계산 예외: {e}")
            return
        self.finished.emit(self._src, peaks)


class WaveformService(QObject):
    """(src, mtime) 캐시 + no-audio short-circuit + in-flight dedup.

    waveform_ready 의 peaks 가 [] 면 '소리 없음' (레인이 평평선 + '소리 없음' 표시).
    """

    waveform_ready = Signal(str, list)   # (src, peaks)

    def __init__(self, *, ffmpeg_path, buckets_per_sec: int = 50,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ffmpeg = ffmpeg_path
        self._buckets_per_sec = int(buckets_per_sec)
        self._cache: dict[tuple[str, float], list] = {}
        self._jobs: dict[str, WaveformJob] = {}   # in-flight: src → job (GC 방지)

    def _cache_key(self, src: str) -> tuple[str, float]:
        try:
            mtime = os.path.getmtime(src)
        except OSError:
            mtime = 0.0
        return (str(src), mtime)

    def request(self, src: str) -> None:
        if not src:
            return
        key = self._cache_key(src)
        if key in self._cache:
            self.waveform_ready.emit(src, self._cache[key])
            return
        if src in self._jobs:
            return   # 이미 진행 중
        job = WaveformJob(ffmpeg_path=self._ffmpeg, src=src,
                          buckets_per_sec=self._buckets_per_sec, parent=self)
        job.finished.connect(self._on_job_finished)
        job.error.connect(self._on_job_error)
        self._jobs[src] = job
        job.start()

    def _on_job_finished(self, src: str, peaks: list) -> None:
        self._cache[self._cache_key(src)] = peaks
        self._jobs.pop(src, None)
        self.waveform_ready.emit(src, peaks)

    def _on_job_error(self, src: str, message: str) -> None:
        _log.warning("waveform failed for %s: %s", src, message)
        self._cache[self._cache_key(src)] = []   # 실패 → 평평선 (재시도 폭주 방지)
        self._jobs.pop(src, None)
        self.waveform_ready.emit(src, [])
