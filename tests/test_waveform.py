import numpy as np
from screen_recorder.encode.waveform import build_waveform_args, compute_peaks


def test_build_waveform_args_mono_pcm():
    argv = build_waveform_args(src="v.mp4", ffmpeg="ffmpeg", sample_rate=8000)
    assert argv[0] == "ffmpeg"
    assert "-vn" in argv and "-ac" in argv and "-f" in argv
    assert "s16le" in argv and "8000" in argv and argv[-1] == "-"


def test_compute_peaks_silence_is_flat():
    pcm = np.zeros(16000, dtype="<i2").tobytes()
    peaks = compute_peaks(pcm, bucket_count=10)
    assert len(peaks) == 10
    assert all(p == 0.0 for p in peaks)


def test_compute_peaks_loud_is_high():
    pcm = np.full(16000, 30000, dtype="<i2").tobytes()
    peaks = compute_peaks(pcm, bucket_count=10)
    assert all(0.8 < p <= 1.0 for p in peaks)   # 30000/32768 ≈ 0.915


def test_compute_peaks_half_loud_half_silent():
    a = np.full(8000, 30000, dtype="<i2")
    b = np.zeros(8000, dtype="<i2")
    pcm = np.concatenate([a, b]).tobytes()
    peaks = compute_peaks(pcm, bucket_count=10)
    assert peaks[0] > 0.8 and peaks[-1] == 0.0


def test_compute_peaks_empty_returns_zeros():
    assert compute_peaks(b"", bucket_count=5) == [0.0] * 5


def test_buckets_for_is_time_proportional():
    from screen_recorder.encode.waveform import buckets_for
    assert buckets_for(8000 * 60 * 30, 8000, 50) == 90000   # 30분 → 90000 (≈50/초)
    assert buckets_for(8000, 8000, 50) == 50                # 1초 → 50
    assert buckets_for(0, 8000, 50) == 1                    # 빈 입력 가드
