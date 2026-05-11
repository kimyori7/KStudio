"""5배속 재생 메모리 누수 / 메인 스레드 응답성 자동 재현 테스트.

실행:
    python -u tools/perf_test_playback.py

동작:
    1. 30초 검은 영상을 ffmpeg 로 생성 (luma 변동 있는 SMPTE bars 로 디코딩 부담 발생)
    2. QMediaPlayer + _VideoSurface 띄움
    3. playback rate = 5.0 으로 재생
    4. 5초마다 RSS / 메인 스레드 latency / 프레임 카운트 측정
    5. 60초 후 종료

기준:
    - PASS: RSS 가 마지막 30s 동안 +50MB 이내 (평탄)
    - FAIL: RSS 가 GB 단위 증가
"""
from __future__ import annotations
import os
import sys
import subprocess
import tempfile
import time
from pathlib import Path

# QT_MEDIA_BACKEND=ffmpeg 강제 (사용자 환경과 동일).
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PySide6.QtCore import QUrl, QTimer, Qt, QDateTime
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

# screen_recorder 의 surface 클래스 그대로 사용.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from screen_recorder.ui.video.player_widget import _VideoSurface
from screen_recorder.core.ffmpeg_check import find_ffmpeg


def _rss_mb() -> float:
    if sys.platform != "win32":
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes
        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        handle = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
            return 0.0
        return pmc.WorkingSetSize / 1024 / 1024
    except Exception:
        return 0.0


def _qimage_count() -> int:
    import gc
    return sum(1 for o in gc.get_objects() if type(o).__name__ == "QImage")


def _make_test_video(ffmpeg: Path, out: Path, seconds: int = 30) -> None:
    """SMPTE bars 30초 영상 (디코딩 부담 있도록 luma 변동 + libx264)."""
    subprocess.run(
        [str(ffmpeg), "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"smptebars=size=1280x720:rate=30:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
         "-t", str(seconds), str(out)],
        check=True,
    )


def main():
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(ffmpeg).exists():
        print("ERROR: ffmpeg not found")
        return 2

    tmp = Path(tempfile.gettempdir()) / "kstudio_perf_test_30s.mp4"
    if not tmp.exists():
        print(f"[setup] generating test video at {tmp}")
        _make_test_video(Path(ffmpeg), tmp, seconds=30)
    else:
        print(f"[setup] reusing test video at {tmp}")

    app = QApplication(sys.argv)

    win = QMainWindow()
    surface = _VideoSurface()
    win.setCentralWidget(surface)
    win.resize(1280, 720)
    win.show()

    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setMuted(True)  # 사용자 음향 환경 영향 제거
    player.setAudioOutput(audio)
    player.setVideoSink(surface.video_sink)
    player.setSource(QUrl.fromLocalFile(str(tmp)))
    player.setPlaybackRate(5.0)

    # 영상 끝나면 처음부터 다시 (60s 측정 위해 loop).
    def _on_status(status):
        if status == QMediaPlayer.EndOfMedia:
            player.setPosition(0)
            player.play()
    player.mediaStatusChanged.connect(_on_status)

    # 측정.
    samples: list[tuple[float, float, int, int, int]] = []
    # (wall_s, rss_mb, qimage_count, frame_count, dump_latency_ms)
    frame_counter = {"n": 0}
    last_tick = {"t": QDateTime.currentMSecsSinceEpoch()}

    # 프레임 카운터.
    def _count_frame(_frame):
        frame_counter["n"] += 1
    surface.video_sink.videoFrameChanged.connect(_count_frame)

    t0 = time.monotonic()
    samples_taken = 0

    def _sample():
        nonlocal samples_taken
        now_ms = QDateTime.currentMSecsSinceEpoch()
        # latency: 5초 타이머가 실제 얼마나 늦게 fired 되는지.
        expected_dt = 5000
        actual_dt = now_ms - last_tick["t"]
        latency = actual_dt - expected_dt
        last_tick["t"] = now_ms

        wall = time.monotonic() - t0
        rss = _rss_mb()
        qi = _qimage_count()
        n = frame_counter["n"]
        frame_counter["n"] = 0

        samples.append((wall, rss, qi, n, latency))
        print(
            f"[t={wall:6.1f}s] rss={rss:7.1f}MB qimage={qi:4d} "
            f"frames_5s={n:5d} timer_latency={latency:+5d}ms"
        )
        samples_taken += 1
        if samples_taken >= 13:   # ~60s 측정 (첫 dump 는 t=5s)
            _summarize()
            app.quit()

    def _summarize():
        print("\n=== SUMMARY ===")
        if not samples:
            print("no samples")
            return
        rss_start = samples[0][1] if samples else 0
        rss_end = samples[-1][1] if samples else 0
        rss_peak = max(s[1] for s in samples)
        qi_max = max(s[2] for s in samples)
        max_latency = max(s[4] for s in samples)
        avg_fps = sum(s[3] for s in samples) / max(1, len(samples) * 5)
        print(f"RSS start={rss_start:.1f}MB  end={rss_end:.1f}MB  peak={rss_peak:.1f}MB  "
              f"delta={rss_end - rss_start:+.1f}MB")
        print(f"QImage max={qi_max}")
        print(f"avg frames/sec={avg_fps:.1f}")
        print(f"max timer latency={max_latency}ms (>500ms = main thread blocked)")
        leak = rss_end - rss_start > 500
        freeze = max_latency > 1000
        print(f"\n  RSS LEAK (>500MB grow): {'FAIL' if leak else 'PASS'}")
        print(f"  MAIN THREAD FREEZE (>1s timer skew): {'FAIL' if freeze else 'PASS'}")

    timer = QTimer()
    timer.setInterval(5000)
    timer.timeout.connect(_sample)
    timer.start()

    # 안전장치 — 90초 후 자동 종료.
    QTimer.singleShot(90_000, app.quit)

    player.play()
    print(f"[playback] 5x playback start - measuring 60s")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
