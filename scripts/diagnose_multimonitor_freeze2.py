"""두 모니터 영역 녹화 freeze 재현 — 프로덕션 파이프라인 그대로 + libx264 부하.

v1(diagnose_multimonitor_freeze.py)은 idle 데스크톱에서 2-카메라 grab 만 75s 돌렸고
얼지 않았다. 실제 녹화는 (1) 무거운 libx264(ultrafast) 인코더가 CPU 를 점유하고
(2) 사용자가 양 모니터를 실제로 쓰는 상태였다. 이 스크립트는 (1)을 더해 **진짜
VideoCaptureThread + VideoEncoder**(production _run_multi 그대로)로 cross-monitor
영역을 ~90초 녹화한 뒤, 결과 mp4 를 freezedetect 로 검사한다.

움직이는 빨간 박스 2개(모니터당 1개)로 화면 변화를 보장. 약 1.5분.
사용법: python scripts/diagnose_multimonitor_freeze2.py
"""
from __future__ import annotations
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

_LOG = os.path.join(os.path.dirname(__file__), "_freeze_diag2_dxcam.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(_LOG, mode="w", encoding="utf-8")],
)
logging.getLogger("dxcam").setLevel(logging.DEBUG)

from screen_recorder.core.ffmpeg_check import find_ffmpeg  # noqa: E402
from screen_recorder.core.settings import VideoSettings, SoundSettings  # noqa: E402
from screen_recorder.capture.targets import Rect, RegionTarget  # noqa: E402
from screen_recorder.capture.video import (  # noqa: E402
    VideoCaptureThread, plan_capture_tiles, resolve_output_rects,
)
from screen_recorder.encode.video_encoder import VideoEncoder  # noqa: E402

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


def freezedetect(ff: str, src: str) -> None:
    r = subprocess.run([ff, "-i", src, "-vf", "freezedetect=n=-60dB:d=2",
                        "-map", "0:v:0", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts, ends = [], []
    for line in r.stderr.splitlines():
        m = re.search(r"freeze_start: ([\d.]+)", line)
        e = re.search(r"freeze_end: ([\d.]+)", line)
        if m: starts.append(float(m.group(1)))
        if e: ends.append(float(e.group(1)))
    print(f"  freeze segments: {len(starts)}")
    if starts:
        print(f"  first freeze_start={starts[0]:.1f}s  last_start={starts[-1]:.1f}s "
              f"last_end={ends[-1] if ends else None}")
        if len(starts) > len(ends):
            print(f"  >>> FINAL FREEZE runs to EOF, begins at {starts[-1]:.1f}s "
                  f"= PERMANENT FREEZE reproduced")
        else:
            print("  >>> no unterminated final freeze (recovered each time)")
    else:
        print("  >>> NO freeze detected - stayed live whole recording")


def main() -> int:
    ff = str(find_ffmpeg())
    outs = resolve_output_rects()
    print("outputs:", [(o.output_idx, o.left, o.right) for o in outs])
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
    region = Rect(a.left + 120, top, (b.right - 120) - (a.left + 120), bot - top)
    if region.w % 2: region = Rect(region.x, region.y, region.w - 1, region.h)
    if region.h % 2: region = Rect(region.x, region.y, region.w, region.h - 1)

    tiles = plan_capture_tiles(region, outs)
    print(f"region={region.w}x{region.h} tiles={len(tiles)} "
          f"{[(t.output_idx, t.region) for t in tiles]}")
    if len(tiles) < 2:
        print("멀티 tile 분해 실패."); return 1

    bw, bh = 360, 240
    procs = []
    for box in ((seam - bw - 40, top + 40, bw, bh), (seam + 40, top + 40, bw, bh)):
        procs.append(subprocess.Popen([sys.executable, "-c", _ANIM, *map(str, box)]))
    time.sleep(2.0)

    out_path = os.path.join(tempfile.mkdtemp(prefix="freeze2_"), "rec.mp4")
    vset = VideoSettings(container="mp4", codec="h264", fps=30,
                         scale_percent=100, bitrate_kbps=8000)
    sset = SoundSettings(system_audio_enabled=False)
    q: queue.Queue = queue.Queue(maxsize=120)
    target = RegionTarget(region)
    cap = VideoCaptureThread(target, 30, q)
    enc = VideoEncoder(vset, sset, region.w, region.h, find_ffmpeg(), out_path, q)
    print("녹화 90초 (production VideoCaptureThread + libx264 ultrafast)...")
    enc.start(); cap.start()
    try:
        time.sleep(90)
    finally:
        cap.stop()
        cap.join(timeout=10)
        q.put(None)
        enc.join(timeout=30)
        for p in procs:
            try: p.terminate()
            except Exception: pass
    print(f"capture dropped={cap.dropped_count} enc.error={enc.error}")
    print(f"output: {out_path}  size={os.path.getsize(out_path) if os.path.exists(out_path) else 'MISSING'}")
    print("freezedetect 결과:")
    if os.path.exists(out_path):
        freezedetect(ff, out_path)
        # 출력 길이 ≈ 캡처 벽시계(90s) 여야 함 (CFR -r fps 라 프레임 수 부족하면 빨라짐).
        pb = os.path.join(os.path.dirname(ff), "ffprobe.exe")
        d = subprocess.run([pb, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=np=1:nk=1", out_path], capture_output=True, text=True)
        try:
            dur = float(d.stdout.strip())
        except ValueError:
            dur = -1.0
        ok = abs(dur - 90) <= 90 * 0.03
        print(f"  duration={dur:.1f}s (기대 ≈90s)  →  {'PASS' if ok else 'FAIL (길이 어긋남)'}")
    print(f"dxcam DEBUG 로그: {_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
