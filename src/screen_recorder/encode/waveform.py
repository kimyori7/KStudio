"""오디오 파형 — ffmpeg 로 모노 PCM 추출 + peak 배열 계산 (순수, Qt 없음).

파형 레인이 그릴 데이터. 원본별 1회 계산해 캐시(services/waveform_service.py).
peak 배열은 고정 bucket_count 해상도 → 레인 폭/줌과 무관, paint 시 bucket→pixel 매핑.
"""
from __future__ import annotations
from pathlib import Path

import numpy as np


def build_waveform_args(*, src, ffmpeg, sample_rate: int = 8000) -> list[str]:
    """src 의 오디오를 모노 16-bit PCM 으로 stdout 에 디코드하는 ffmpeg argv.

    8000Hz 모노면 분 단위 영상도 가볍다 (1분 ≈ 0.96MB). 파형엔 충분한 해상도.
    """
    return [
        str(ffmpeg), "-v", "error",
        "-i", str(src),
        "-vn", "-ac", "1", "-ar", str(int(sample_rate)),
        "-f", "s16le", "-",
    ]


def compute_peaks(pcm: bytes, *, bucket_count: int) -> list[float]:
    """16-bit little-endian PCM → bucket_count 개 peak (각 0.0~1.0).

    각 bucket = 균등 분할 구간의 |샘플| 최댓값 / 32768. 빈 입력은 0 배열.
    """
    if bucket_count <= 0:
        return []
    samples = np.frombuffer(pcm, dtype="<i2")
    if samples.size == 0:
        return [0.0] * bucket_count
    abs_s = np.abs(samples.astype(np.float32))
    chunks = np.array_split(abs_s, bucket_count)
    peaks: list[float] = []
    for c in chunks:
        v = float(c.max()) / 32768.0 if c.size else 0.0
        peaks.append(min(1.0, max(0.0, v)))
    return peaks


def buckets_for(n_samples: int, sample_rate: int, buckets_per_sec: int = 50) -> int:
    """디코드된 샘플 수 → 총 bucket 수 (시간 비례, ≈buckets_per_sec/초).

    ⚠ 고정 총 bucket 금지: 긴 원본을 짧게 자른 슬라이스가 몇 bucket 으로 뭉개져
    평평한 블록이 되는 것 방지. 30분@8000Hz → 90000 bucket → 5초 슬라이스도
    ≈250 bucket 유지. WaveformJob 이 디코드 후 이 함수로 bucket_count 결정.
    """
    if sample_rate <= 0:
        return 1
    return max(1, int(n_samples) * int(buckets_per_sec) // int(sample_rate))
