"""5배속 재생 중 백그라운드 인덱싱 (ffmpeg 첫 프레임 추출) 동시 진행 stutter 측정.

목적: 사용자 보고 "프리뷰 로딩 중 어플 자체가 엄청 버벅거려, 메인은 항상 매끄럽게
움직여야해" — 인덱싱이 재생을 방해하는지 객관적으로 검증.

대상: C:\\Users\\me\\KStudio\\Video\\samples\\ 안의 mp4 들 (실제 사용자 파일).
"""
from __future__ import annotations
import os
import sys
import time
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PySide6.QtCore import QUrl, QTimer, Qt, QDateTime
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QImage

from screen_recorder.ui.video.player_widget import _VideoSurface
from screen_recorder.core.ffmpeg_check import find_ffmpeg


def main():
    target_dir = Path(r"C:\Users\me\KStudio\Video\samples")
    mp4s = sorted([p for p in target_dir.iterdir() if p.suffix.lower() == ".mp4"],
                  key=lambda p: -p.stat().st_size)
    if not mp4s:
        print("no mp4")
        return 2
    play_target = mp4s[0]   # 192MB
    index_targets = mp4s[1:]   # 다른 mp4 들을 인덱싱
    size_mb = play_target.stat().st_size / 1024 / 1024
    print(f"playing: {play_target.name} ({size_mb:.0f}MB) at 5x")
    print(f"indexing: {len(index_targets)} other files in background")

    ffmpeg = Path(find_ffmpeg() or "")
    ffprobe = ffmpeg.parent / "ffprobe.exe"

    app = QApplication(sys.argv)

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
    player.setSource(QUrl.fromLocalFile(str(play_target)))
    player.setPlaybackRate(5.0)

    def _loop(status):
        if status == QMediaPlayer.EndOfMedia:
            player.setPosition(0)
            player.play()
    player.mediaStatusChanged.connect(_loop)

    # 인덱싱 워커 — duration probe (max=2) + thumbnail extract (max=1) 같이 띄움.
    dur_pool = ThreadPoolExecutor(max_workers=2)
    thumb_pool = ThreadPoolExecutor(max_workers=1)

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
                 "-i", str(v),
                 "-vf", "scale='min(256,iw)':-2",
                 "-frames:v", "1", str(tmp)],
                check=True, capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        finally:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass

    # 측정 (메인 스레드 응답성).
    last_tick = {"t": QDateTime.currentMSecsSinceEpoch()}
    samples = []
    samples_taken = 0
    phase = {"name": "PLAY-ONLY"}

    def _start_indexing():
        print("\n>>> [t=8s] START background indexing during playback")
        for v in index_targets:
            dur_pool.submit(_probe_duration, v)
        for v in index_targets:
            thumb_pool.submit(_extract_thumb, v)
        phase["name"] = "PLAY+IDX"

    def _sample():
        nonlocal samples_taken
        now_ms = QDateTime.currentMSecsSinceEpoch()
        skew = (now_ms - last_tick["t"]) - 1000
        last_tick["t"] = now_ms
        samples.append((phase["name"], skew))
        marker = "" if skew < 100 else f"  *** {skew}ms BLOCK"
        print(f"  [{phase['name']:9s}] dump#{samples_taken:2d}  "
              f"timer_skew={skew:+5d}ms{marker}")
        samples_taken += 1
        if samples_taken >= 30:   # 30s
            _summarize()
            dur_pool.shutdown(wait=False)
            thumb_pool.shutdown(wait=False)
            app.quit()

    def _summarize():
        play_only = [s for s in samples if s[0] == "PLAY-ONLY"]
        play_idx = [s for s in samples if s[0] == "PLAY+IDX"]
        def stats(xs):
            if not xs: return None
            skews = [s[1] for s in xs]
            return (max(skews), sum(skews)/len(skews),
                    sum(1 for s in skews if s > 100),
                    sum(1 for s in skews if s > 500))
        po = stats(play_only)
        pi = stats(play_idx)
        print("\n=== SUMMARY ===")
        if po:
            print(f"  PLAY-ONLY (n={len(play_only)}): max={po[0]}ms avg={po[1]:.1f}ms "
                  f">100ms={po[2]}  >500ms={po[3]}")
        if pi:
            print(f"  PLAY+IDX  (n={len(play_idx)}): max={pi[0]}ms avg={pi[1]:.1f}ms "
                  f">100ms={pi[2]}  >500ms={pi[3]}")
        if po and pi:
            print(f"\n  diff: max +{pi[0]-po[0]}ms  hits>100ms +{pi[2]-po[2]}")

    timer = QTimer()
    timer.setInterval(1000)   # 1초마다 측정 (작은 stutter 도 잡기 위해 빈도 ↑)
    timer.timeout.connect(_sample)
    timer.start()

    QTimer.singleShot(8_000, _start_indexing)
    QTimer.singleShot(40_000, app.quit)
    player.play()
    print("(5x playback start, indexing kicks in at t=8s)\n")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
