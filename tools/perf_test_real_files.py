"""사용자 실제 파일로 5배속 + EditController 초기화 latency 측정.

사용:
    python -u tools/perf_test_real_files.py

대상:
    C:\\Users\\kimyori\\KStudio\\Video\\발표용\\기획서 제작_시작.mp4 (202MB)
"""
from __future__ import annotations
import os
import sys
import time
import tempfile
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PySide6.QtCore import QUrl, QTimer, Qt, QDateTime
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from screen_recorder.ui.video.player_widget import _VideoSurface
from screen_recorder.ui.video.edit_controller import EditController
from screen_recorder.effects.sidecar_store import compute_video_hash


def main():
    target_dir = Path(r"C:\Users\me\KStudio\Video\발표용")
    if not target_dir.exists():
        print(f"ERROR: target dir not found: {target_dir}")
        return 2
    mp4s = sorted([p for p in target_dir.iterdir() if p.suffix.lower() == ".mp4"],
                  key=lambda p: -p.stat().st_size)
    if not mp4s:
        print("ERROR: no mp4 in target dir")
        return 2
    target = mp4s[0]
    size_mb = target.stat().st_size / 1024 / 1024
    print(f"target = {target.name}  ({size_mb:.1f} MB)")

    sidecar_dir = Path(tempfile.gettempdir()) / "kstudio_perf_real_sidecars"
    sidecar_dir.mkdir(exist_ok=True)

    app = QApplication(sys.argv)

    # === A: hash compute time alone ===
    print("\n=== A: compute_video_hash (1MB read + SHA1) ===")
    for i in range(3):
        t0 = time.perf_counter()
        h = compute_video_hash(target)
        dt = (time.perf_counter() - t0) * 1000
        cache_state = "cold" if i == 0 else "warm"
        print(f"  {cache_state:5s}  {dt:6.1f} ms  hash={h[:12]}...")

    # === B: EditController.__init__ (cold) ===
    print("\n=== B: EditController.__init__ ===")
    for i in range(3):
        t0 = time.perf_counter()
        ec = EditController(target, sidecar_dir)
        dt = (time.perf_counter() - t0) * 1000
        cache_state = "cold" if i == 0 else "warm"
        print(f"  {cache_state:5s}  {dt:6.1f} ms")
        ec.deleteLater()

    # === C: 5x playback with real file ===
    print("\n=== C: 5x playback on real 202MB file ===")

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

    frame_counter = {"n": 0}
    surface.video_sink.videoFrameChanged.connect(
        lambda _f: frame_counter.__setitem__("n", frame_counter["n"] + 1)
    )

    last_tick = {"t": QDateTime.currentMSecsSinceEpoch()}
    samples = []
    samples_taken = 0

    def _sample():
        nonlocal samples_taken
        now_ms = QDateTime.currentMSecsSinceEpoch()
        latency = (now_ms - last_tick["t"]) - 2000
        last_tick["t"] = now_ms
        n = frame_counter["n"]
        frame_counter["n"] = 0
        samples.append((n, latency))
        print(f"  dump#{samples_taken:2d}  frames_2s={n:4d}  "
              f"timer_skew={latency:+5d}ms")
        samples_taken += 1
        if samples_taken >= 15:   # 30s 측정
            _summarize()
            app.quit()

    def _summarize():
        print("\n=== SUMMARY (5x on 202MB real file) ===")
        max_skew = max(s[1] for s in samples)
        avg_skew = sum(s[1] for s in samples) / len(samples)
        avg_fps = sum(s[0] for s in samples) / (len(samples) * 2)
        print(f"  avg frames/sec = {avg_fps:.1f}")
        print(f"  max timer skew = {max_skew}ms")
        print(f"  avg timer skew = {avg_skew:.1f}ms")
        print(f"  freezes detected (>1s skew): {sum(1 for s in samples if s[1] > 1000)}")
        print(f"  big freezes (>3s skew):     {sum(1 for s in samples if s[1] > 3000)}")

    timer = QTimer()
    timer.setInterval(2000)
    timer.timeout.connect(_sample)
    timer.start()

    QTimer.singleShot(45_000, app.quit)
    player.play()
    print("  (5x playback start)\n")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
