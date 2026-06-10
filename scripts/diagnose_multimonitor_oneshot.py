"""FIX 후보: 내부 캡처 스레드 없이 one-shot grab 으로 cross-monitor 합성 (deadlock 회피).

근본 원인 확정: 2개 output 의 dxcam 내부 캡처 스레드(start()+video_mode)가 부하 시
공유 D3D multithread lock 에서 deadlock. single-camera 는 같은 부하에도 멀쩡.
→ fix = start() 안 하고, **우리 단일 루프가 output 별로 순차 one-shot grab**.
   동시 D3D 접근이 없으니 deadlock 자체가 성립 안 함.

같은 libx264 부하로 90s 돌려 freeze 안 나는지 + 실효 fps 측정.
약 1.5분.
"""
from __future__ import annotations
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
logging.basicConfig(level=logging.CRITICAL)

import dxcam  # noqa: E402
from screen_recorder.core.ffmpeg_check import find_ffmpeg  # noqa: E402
from screen_recorder.core.settings import VideoSettings  # noqa: E402
from screen_recorder.core.ffmpeg_args import video_pipe_args  # noqa: E402
from screen_recorder.capture.targets import Rect  # noqa: E402
from screen_recorder.capture.video import plan_capture_tiles, resolve_output_rects  # noqa: E402

_ANIM = r"""
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QPainter, QColor
x, y, w, h = map(int, sys.argv[1:5])
app = QApplication([])
class A(QWidget):
    def __init__(s):
        super().__init__()
        s.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        s.setAttribute(Qt.WA_ShowWithoutActivating)
        s.setGeometry(x, y, w, h); s.t = 0
        tm = QTimer(s); tm.timeout.connect(s.tick); tm.start(16); s._tm = tm
    def tick(s):
        s.t = (s.t + 11) % max(1, s.width()); s.update()
    def paintEvent(s, e):
        p = QPainter(s); p.fillRect(s.rect(), QColor(12, 12, 12))
        p.fillRect(s.t, 0, 60, s.height(), QColor(255, 60, 60))
a = A(); a.show()
sys.exit(app.exec())
"""


def _hash(buf):
    return hashlib.md5(buf[::8, ::8].tobytes()).hexdigest()


def main() -> int:
    ff = str(find_ffmpeg())
    outs = resolve_output_rects()
    pair = None
    for a in outs:
        for b in outs:
            if (a.output_idx, a.device_idx) == (b.output_idx, b.device_idx):
                continue
            if a.right == b.left and min(a.bottom, b.bottom) - max(a.top, b.top) > 400:
                pair = (a, b); break
        if pair: break
    if not pair:
        print("좌우 인접 두 모니터 없음."); return 1
    a, b = pair
    seam = a.right
    top = max(a.top, b.top) + 80
    bot = min(a.bottom, b.bottom) - 80
    region = Rect(a.left + 120, top, ((b.right - 120) - (a.left + 120)) // 2 * 2, (bot - top) // 2 * 2)
    tiles = plan_capture_tiles(region, outs)
    print(f"region={region.w}x{region.h} tiles={len(tiles)} {[(t.output_idx, t.region) for t in tiles]}")

    bw, bh = 360, 240
    boxes = [(a.left + 260, top + 40, bw, bh), (seam + 40, top + 40, bw, bh)]
    procs = [subprocess.Popen([sys.executable, "-c", _ANIM, *map(str, box)]) for box in boxes]
    time.sleep(2.0)

    # one-shot 카메라 — start() 안 함(내부 스레드 없음).
    cams = [dxcam.create(device_idx=t.device_idx, output_idx=t.output_idx, output_color="BGRA")
            for t in tiles]

    out_path = os.path.join(tempfile.mkdtemp(prefix="oneshot_"), "rec.mp4")
    enc_argv = video_pipe_args(VideoSettings(fps=30, codec="h264", bitrate_kbps=8000), region.w, region.h, out_path)
    enc_argv[0] = ff
    enc = subprocess.Popen(enc_argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    ow, oh = region.w, region.h
    period = 1 / 30
    t0 = time.perf_counter()
    last_hash, last_change = None, t0
    froze_at = None
    frames = 0
    last_good = [None] * len(tiles)  # tile 별 최근 성공 프레임 (one-shot None 시 재사용)
    next_tick = t0
    while time.perf_counter() - t0 < 90:
        buf = np.zeros((oh, ow, 4), dtype=np.uint8)
        for i, (t, c) in enumerate(zip(tiles, cams)):
            fr = c.grab(region=t.region, new_frame_only=False)  # one-shot, 없으면 직전 캐시
            if fr is None:
                fr = last_good[i]
            else:
                last_good[i] = fr
            if fr is None:
                continue
            ph = min(fr.shape[0], t.h); pw = min(fr.shape[1], t.w)
            buf[t.dst_y:t.dst_y + ph, t.dst_x:t.dst_x + pw] = fr[:ph, :pw]
        try:
            enc.stdin.write(buf.tobytes()); frames += 1
        except (BrokenPipeError, OSError):
            pass
        now = time.perf_counter()
        h = _hash(buf)
        if h != last_hash:
            last_hash = h; last_change = now
        if now - last_change > 4.0 and froze_at is None:
            froze_at = now - t0
            print(f"FREEZE 감지 t={froze_at:.1f}s")
        next_tick += period
        sl = next_tick - time.perf_counter()
        if sl > 0:
            time.sleep(sl)
        else:
            next_tick = time.perf_counter()

    elapsed = time.perf_counter() - t0
    try:
        enc.stdin.close(); enc.wait(timeout=20)
    except Exception:
        pass
    for c in cams:
        try: c.release()
        except Exception: pass
    for p in procs:
        try: p.terminate()
        except Exception: pass

    print(f"\n=== one-shot 결과 ===")
    print(f"  frames={frames} elapsed={elapsed:.1f}s  실효fps={frames/elapsed:.1f}")
    print(f"  froze_at = {froze_at}")
    r = subprocess.run([ff, "-i", out_path, "-vf", "freezedetect=n=-60dB:d=2",
                        "-map", "0:v:0", "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(m.group(1)) for line in r.stderr.splitlines()
              if (m := re.search(r"freeze_start: ([\d.]+)", line))]
    ends = [float(m.group(1)) for line in r.stderr.splitlines()
            if (m := re.search(r"freeze_end: ([\d.]+)", line))]
    print(f"  freezedetect: segments={len(starts)} final_runs_to_EOF={len(starts) > len(ends)} "
          f"last_start={starts[-1] if starts else None}")
    print(f"  → {'PASS (freeze 없음)' if not (len(starts) > len(ends)) else 'FAIL (영구 freeze)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
