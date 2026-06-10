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
