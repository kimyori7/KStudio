"""VideoTab 오픈 latency + 5배속 + 백그라운드 인덱싱 경합 자동 측정.

목적:
    - 사용자 보고 "영상 모드 클릭 후 한참 / 영상 클릭해도 한참 / 5배속도 느림"
    - 의심 1: EditController.__init__ 의 hash 계산 (1MB read + SHA1) 이 main thread 차단
    - 의심 2: 백그라운드 인덱싱 (duration_probe + thumbnail) 이 재생과 경합

측정:
    A. cold: 단일 mp4 → EditController 생성 시간
    B. warm: 같은 파일 두 번째 → 캐시 효과
    C. concurrent: 5배속 재생 중에 다른 N 개 파일 인덱싱 시뮬레이션 (ffprobe + ffmpeg
       subprocess 를 max_workers=2,1 풀로 띄움) → 프레임 도착률 / paint latency 변화
"""
from __future__ import annotations
import os
import sys
import time
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PySide6.QtCore import QUrl, QTimer, Qt, QDateTime
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QImage

from screen_recorder.ui.video.player_widget import _VideoSurface
from screen_recorder.ui.video.edit_controller import EditController
from screen_recorder.core.ffmpeg_check import find_ffmpeg


def _make_test_video(ffmpeg: Path, out: Path, seconds: int = 30,
                     size: str = "1280x720") -> None:
    subprocess.run(
        [str(ffmpeg), "-y", "-loglevel", "error",
         "-f", "lavfi",
         "-i", f"smptebars=size={size}:rate=30:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
         "-t", str(seconds), str(out)],
        check=True,
    )


def main():
    ffmpeg_p = find_ffmpeg()
    if not ffmpeg_p or not Path(ffmpeg_p).exists():
        print("ERROR: ffmpeg not found")
        return 2
    ffmpeg = Path(ffmpeg_p)

    # 5 개 영상 — 인덱싱 경합 시뮬레이션.
    tmpdir = Path(tempfile.gettempdir()) / "kstudio_perf_tab_test"
    tmpdir.mkdir(exist_ok=True)
    sidecar_dir = tmpdir / "sidecars"
    sidecar_dir.mkdir(exist_ok=True)

    videos: list[Path] = []
    # 1080p 30s mp4 — 사용자 실제 녹화와 비슷한 사이즈.
    for i in range(5):
        v = tmpdir / f"clip_{i:02d}_1080p.mp4"
        if not v.exists():
            print(f"[setup] generating {v.name}")
            _make_test_video(ffmpeg, v, seconds=30, size="1920x1080")
        videos.append(v)
    sizes = [v.stat().st_size / 1024 / 1024 for v in videos]
    print(f"[setup] file sizes: {[f'{s:.1f}MB' for s in sizes]}")

    app = QApplication(sys.argv)

    # === A: cold EditController 생성 시간 ===
    print("\n=== A: cold EditController.__init__ latency ===")
    for v in videos[:3]:
        t0 = time.perf_counter()
        ec = EditController(v, sidecar_dir)
        dt = (time.perf_counter() - t0) * 1000
        print(f"  {v.name}  {dt:6.1f} ms")
        ec.deleteLater()

    # === B: warm — 같은 파일 다시 ===
    print("\n=== B: warm EditController (OS file cache) ===")
    for v in videos[:3]:
        t0 = time.perf_counter()
        ec = EditController(v, sidecar_dir)
        dt = (time.perf_counter() - t0) * 1000
        print(f"  {v.name}  {dt:6.1f} ms")
        ec.deleteLater()

    # === C: 5배속 재생 중 인덱싱 경합 ===
    print("\n=== C: 5x playback + background indexing simulation ===")

    # 대상 영상.
    target = videos[0]
    win = QMainWindow()
    surface = _VideoSurface()
    win.setCentralWidget(surface)
    win.resize(1280, 720)
    win.show()

    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setMuted(True)
    player.setAudioOutput(audio)
    player.setVideoSink(surface.video_sink)
    player.setSource(QUrl.fromLocalFile(str(target)))
    player.setPlaybackRate(5.0)

    def _loop(status):
        if status == QMediaPlayer.EndOfMedia:
            player.setPosition(0)
            player.play()
    player.mediaStatusChanged.connect(_loop)

    # ffmpeg/ffprobe 경합 시뮬 — 다른 영상들 duration/thumbnail 추출.
    dur_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="DurationProbe")
    thumb_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ThumbnailExtract")
    ffprobe = ffmpeg.parent / "ffprobe.exe"

    def _probe_duration(v: Path):
        try:
            subprocess.run(
                [str(ffprobe), "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(v)],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    def _extract_thumb(v: Path):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = Path(f.name)
        try:
            subprocess.run(
                [str(ffmpeg), "-y", "-loglevel", "error",
                 "-i", str(v), "-frames:v", "1", str(tmp)],
                check=True, capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        finally:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass

    # 측정.
    frame_counter = {"n": 0}
    surface.video_sink.videoFrameChanged.connect(
        lambda _f: frame_counter.__setitem__("n", frame_counter["n"] + 1)
    )

    last_tick = {"t": QDateTime.currentMSecsSinceEpoch()}
    samples = []
    samples_taken = 0
    indexing_phase = {"on": False}

    def _start_indexing():
        """T=10s 에서 인덱싱 시작 — 5배속 한창 돌아가는 중."""
        print("\n  [t=10s] >>> START background indexing of 4 other videos")
        for v in videos[1:]:
            dur_pool.submit(_probe_duration, v)
        for v in videos[1:]:
            thumb_pool.submit(_extract_thumb, v)
        indexing_phase["on"] = True

    def _sample():
        nonlocal samples_taken
        now_ms = QDateTime.currentMSecsSinceEpoch()
        latency = (now_ms - last_tick["t"]) - 2000
        last_tick["t"] = now_ms
        n = frame_counter["n"]
        frame_counter["n"] = 0
        samples.append((samples_taken, n, latency, indexing_phase["on"]))
        phase = "INDEX" if indexing_phase["on"] else "play "
        print(f"  [{phase}] dump#{samples_taken:2d}  frames_2s={n:4d}  "
              f"timer_skew={latency:+5d}ms")
        samples_taken += 1
        if samples_taken >= 15:   # 30초 측정
            _summarize()
            dur_pool.shutdown(wait=False)
            thumb_pool.shutdown(wait=False)
            app.quit()

    def _summarize():
        print("\n=== SUMMARY ===")
        play_samples = [s for s in samples if not s[3]]
        idx_samples = [s for s in samples if s[3]]
        def avg(xs, i): return sum(s[i] for s in xs) / max(1, len(xs))
        if play_samples:
            print(f"  PLAY ONLY:  avg frames/2s={avg(play_samples,1):5.1f}  "
                  f"avg skew={avg(play_samples,2):+5.1f}ms  max skew="
                  f"{max(s[2] for s in play_samples):+5d}ms")
        if idx_samples:
            print(f"  PLAY+IDX:   avg frames/2s={avg(idx_samples,1):5.1f}  "
                  f"avg skew={avg(idx_samples,2):+5.1f}ms  max skew="
                  f"{max(s[2] for s in idx_samples):+5d}ms")
        if play_samples and idx_samples:
            drop_pct = (avg(play_samples,1) - avg(idx_samples,1)) / avg(play_samples,1) * 100
            print(f"\n  frame rate drop during indexing: {drop_pct:+.1f}%")

    timer = QTimer()
    timer.setInterval(2000)
    timer.timeout.connect(_sample)
    timer.start()

    QTimer.singleShot(10_000, _start_indexing)
    QTimer.singleShot(35_000, app.quit)   # 안전장치

    player.play()
    print("  (5x playback start, indexing starts at t=10s)\n")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
