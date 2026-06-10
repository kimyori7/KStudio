"""wedge 된 cross-monitor 캡처를 stop+recreate 로 되살릴 수 있는가? (fix 타당성 검증)

freeze2 로 t≈36s 영구 freeze 재현됨(2-카메라 + libx264 부하 → DDA 스레드 deadlock).
이 스크립트는 같은 부하에서 standalone _run_multi 루프를 돌리며:
  - 초당 합성 프레임 해시로 staleness 감시
  - STALE_SECS(4s) 이상 안 바뀌면 → 카메라 rebuild(stop+release+create+start) 1회
  - stop() 이 wedge 된 스레드 join 에서 hang 하는지 별 스레드+timeout 으로 측정
  - rebuild 후 내용이 다시 바뀌는지(=복구) 관찰
부하 재현용 libx264(ultrafast) 인코더에 실제로 프레임을 흘려보낸다.

mode 인자: "multi"(기본) | "single"  (single = 한 output 안, 같은 부하 — 범위 대조군)
약 1.5분.
"""
from __future__ import annotations
import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
logging.basicConfig(level=logging.CRITICAL)  # dxcam 로그 침묵(콘솔 깔끔).

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

STALE_SECS = 4.0


def _hash(buf):
    return hashlib.md5(buf[::8, ::8].tobytes()).hexdigest()


def _open(tiles):
    cams = []
    for t in tiles:
        c = dxcam.create(device_idx=t.device_idx, output_idx=t.output_idx, output_color="BGRA")
        c.start(target_fps=30, region=t.region, video_mode=True)
        cams.append(c)
    return cams


def _stop_one(cam, timeout=3.0):
    """cam.stop()+release() 를 별 스레드에서 — wedge 시 hang 여부 측정."""
    done = threading.Event()
    def _k():
        try: cam.stop()
        except Exception: pass
        try: cam.release()
        except Exception: pass
        done.set()
    threading.Thread(target=_k, daemon=True).start()
    t0 = time.perf_counter()
    hung = not done.wait(timeout)
    return hung, time.perf_counter() - t0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "multi"
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

    if mode == "single":
        # output A 안에 완전히 들어가는 영역 (tile 1개) — 같은 부하로 대조.
        region = Rect(a.left + 200, top, 2000 // 2 * 2, (bot - top) // 2 * 2)
    else:
        region = Rect(a.left + 120, top, ((b.right - 120) - (a.left + 120)) // 2 * 2, (bot - top) // 2 * 2)

    tiles = plan_capture_tiles(region, outs)
    print(f"mode={mode} region={region.w}x{region.h} tiles={len(tiles)} "
          f"{[(t.output_idx, t.region) for t in tiles]}")

    # 움직이는 박스 — multi 는 양쪽, single 은 output A 쪽 하나.
    bw, bh = 360, 240
    boxes = [(a.left + 260, top + 40, bw, bh)]
    if mode != "single":
        boxes.append((seam + 40, top + 40, bw, bh))
    procs = [subprocess.Popen([sys.executable, "-c", _ANIM, *map(str, box)]) for box in boxes]
    time.sleep(2.0)

    out_path = os.path.join(tempfile.mkdtemp(prefix="recover_"), "rec.mp4")
    enc_argv = video_pipe_args(VideoSettings(fps=30, codec="h264", bitrate_kbps=8000), region.w, region.h, out_path)
    enc_argv[0] = ff
    enc = subprocess.Popen(enc_argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    cams = _open(tiles)
    ow, oh = region.w, region.h
    t0 = time.perf_counter()
    last_hash = None
    last_change = t0
    rebuilt_at = None
    resumed_after_rebuild = False
    froze_at = None
    print(f"[{mode}] 캡처 90s, STALE>{STALE_SECS}s 면 rebuild 1회...")
    while time.perf_counter() - t0 < 90:
        buf = np.zeros((oh, ow, 4), dtype=np.uint8)
        got = False
        for t, c in zip(tiles, cams):
            fr = c.grab()
            if fr is None:
                continue
            ph = min(fr.shape[0], t.h); pw = min(fr.shape[1], t.w)
            buf[t.dst_y:t.dst_y + ph, t.dst_x:t.dst_x + pw] = fr[:ph, :pw]
            got = True
        now = time.perf_counter()
        if got:
            try:
                enc.stdin.write(buf.tobytes())
            except (BrokenPipeError, OSError):
                pass
            h = _hash(buf)
            if h != last_hash:
                last_hash = h
                last_change = now
                if rebuilt_at is not None and now > rebuilt_at + 0.5:
                    resumed_after_rebuild = True
        # staleness 감시
        stale = now - last_change
        if stale > STALE_SECS and froze_at is None:
            froze_at = now - t0
            print(f"[{mode}] FREEZE 감지 t={froze_at:.1f}s (stale {stale:.1f}s) → rebuild 시도")
            hungs = []
            for c in cams:
                hung, dur = _stop_one(c)
                hungs.append((hung, round(dur, 2)))
            print(f"[{mode}]   stop() 결과 (hung, sec): {hungs}")
            try:
                cams = _open(tiles)
                print(f"[{mode}]   recreate+start OK")
            except Exception as e:
                print(f"[{mode}]   recreate FAILED: {e}")
                break
            rebuilt_at = time.perf_counter()
            last_change = rebuilt_at  # rebuild 후 다시 카운트
        time.sleep(1 / 30)

    try:
        enc.stdin.close(); enc.wait(timeout=20)
    except Exception:
        pass
    for c in cams:
        _stop_one(c)
    for p in procs:
        try: p.terminate()
        except Exception: pass

    print(f"\n[{mode}] === 결과 ===")
    print(f"  froze_at = {froze_at}")
    print(f"  rebuilt  = {rebuilt_at is not None}")
    print(f"  rebuild 후 내용 다시 변함(복구) = {resumed_after_rebuild}")
    # freezedetect
    import re
    r = subprocess.run([ff, "-i", out_path, "-vf", "freezedetect=n=-60dB:d=2",
                        "-map", "0:v:0", "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(m.group(1)) for line in r.stderr.splitlines()
              if (m := re.search(r"freeze_start: ([\d.]+)", line))]
    ends = [float(m.group(1)) for line in r.stderr.splitlines()
            if (m := re.search(r"freeze_end: ([\d.]+)", line))]
    print(f"  freezedetect: segments={len(starts)} "
          f"final_runs_to_EOF={len(starts) > len(ends)} "
          f"last_start={starts[-1] if starts else None}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
