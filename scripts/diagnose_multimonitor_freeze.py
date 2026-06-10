"""두 모니터에 걸친 영역 녹화가 ~50초 후 얼어붙는 현상의 원인 분리.

실제 녹화(rec_20260610_143742.mp4)는 t≈49.6s부터 영구 freeze(내용 정지),
frame_count 는 30fps 유지 → grab() 이 stale 프레임을 계속 반환. 가설: output 2개의
DDA(Desktop Duplication) 카메라 동시 가동이 stall.

이 스크립트가 직접 가른다:
  (A) MULTI  = plan_capture_tiles 로 2개 카메라 합성 (프로덕션 _run_multi 와 동일)
  (B) SINGLE = 한 output 안 1개 카메라
각각 ~75초 캡처하며 **초당 합성 프레임 해시**를 찍어, 내용이 언제부터 안 바뀌는지 비교.
SINGLE 도 같이 얼면 → multi 무관(일반 dxcam/video_mode 문제). MULTI 만 얼면 → 2-카메라 특이.

화면 변화를 보장하려고 작은 topmost 박스(빨간 막대가 움직임)를 각 모니터에 띄운다.
캡처 자체는 화면에 안 보이고, 박스 2개만 잠깐 보인다. 약 2.5분.
사용법: python scripts/diagnose_multimonitor_freeze.py
"""
from __future__ import annotations
import hashlib
import logging
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# dxcam DEBUG → 파일 (recovery/access-loss 이벤트 포착).
_LOG = os.path.join(os.path.dirname(__file__), "_freeze_diag_dxcam.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(_LOG, mode="w", encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
logging.getLogger("dxcam").setLevel(logging.DEBUG)

import dxcam  # noqa: E402
from screen_recorder.capture.targets import Rect  # noqa: E402
from screen_recorder.capture.video import (  # noqa: E402
    plan_capture_tiles, resolve_output_rects,
)

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


def _fhash(buf: np.ndarray) -> str:
    return hashlib.md5(buf[::8, ::8].tobytes()).hexdigest()


def run_capture(label: str, tiles, rect: Rect, secs: float) -> None:
    out_w, out_h = rect.w, rect.h
    cams = []
    for t in tiles:
        c = dxcam.create(device_idx=t.device_idx, output_idx=t.output_idx,
                         output_color="BGRA")
        c.start(target_fps=30, region=t.region, video_mode=True)
        cams.append(c)
    print(f"\n[{label}] cams={len(cams)} region={rect.w}x{rect.h} "
          f"tiles={[(t.output_idx, t.region) for t in tiles]} → {secs:.0f}s")
    t0 = time.perf_counter()
    sec_hash: dict[int, str] = {}
    none_cnt = [0] * len(tiles)
    frames = 0
    while time.perf_counter() - t0 < secs:
        buf = np.zeros((out_h, out_w, 4), dtype=np.uint8)
        got = False
        for i, (t, c) in enumerate(zip(tiles, cams)):
            fr = c.grab()
            if fr is None:
                none_cnt[i] += 1
                continue
            ph = min(fr.shape[0], t.h); pw = min(fr.shape[1], t.w)
            buf[t.dst_y:t.dst_y + ph, t.dst_x:t.dst_x + pw] = fr[:ph, :pw]
            got = True
        if got:
            frames += 1
            sec = int(time.perf_counter() - t0)
            sec_hash.setdefault(sec, _fhash(buf))
        time.sleep(1 / 30)
    for c in cams:
        try: c.stop()
        except Exception: pass
        try: c.release()
        except Exception: pass

    secs_sorted = sorted(sec_hash)
    last_change = 0
    for i in range(1, len(secs_sorted)):
        if sec_hash[secs_sorted[i]] != sec_hash[secs_sorted[i - 1]]:
            last_change = secs_sorted[i]
    distinct = len(set(sec_hash.values()))
    print(f"[{label}] frames={frames} grab_None_per_cam={none_cnt} "
          f"distinct_sec_hashes={distinct}/{len(sec_hash)}")
    print(f"[{label}] last_content_change at t={last_change}s "
          f"(capture ran {secs:.0f}s)  →  "
          f"{'FROZE' if last_change < secs - 8 else 'stayed live'}")


def main() -> int:
    outs = resolve_output_rects()
    print("outputs:", outs)
    # 좌우로 맞닿은 두 output 찾기 (a.right == b.left, 세로 겹침).
    pair = None
    for a in outs:
        for b in outs:
            if a.output_idx == b.output_idx and a.device_idx == b.device_idx:
                continue
            if a.right == b.left and min(a.bottom, b.bottom) - max(a.top, b.top) > 400:
                pair = (a, b); break
        if pair: break
    if not pair:
        print("좌우로 맞닿은 두 모니터를 못 찾음 — 멀티모니터 환경 필요.")
        return 1
    a, b = pair
    seam = a.right
    top = max(a.top, b.top) + 80
    bot = min(a.bottom, b.bottom) - 80
    # 큰 cross-monitor 영역 (사용자 케이스와 비슷하게 양쪽 모니터를 넓게).
    region = Rect(a.left + 120, top, (b.right - 120) - (a.left + 120), bot - top)

    # 움직이는 박스 2개 — output A 쪽(seam 왼쪽), output B 쪽(seam 오른쪽).
    bw, bh = 360, 240
    box_a = (seam - bw - 40, top + 40, bw, bh)
    box_b = (seam + 40, top + 40, bw, bh)
    procs = []
    for box in (box_a, box_b):
        procs.append(subprocess.Popen(
            [sys.executable, "-c", _ANIM, *map(str, box)]))
    time.sleep(2.0)  # 박스가 뜨고 그려질 시간.

    try:
        multi_tiles = plan_capture_tiles(region, outs)
        if len(multi_tiles) < 2:
            print("멀티 tile 분해 실패:", multi_tiles); return 1
        run_capture("MULTI ", multi_tiles, region, secs=75)

        # SINGLE: output A 안에서 box_a 를 포함하는 작은 영역 (tile 1개).
        s_rect = Rect(box_a[0] - 60, box_a[1] - 60, bw + 120, bh + 120)
        single_tiles = plan_capture_tiles(s_rect, outs)
        if len(single_tiles) != 1:
            print("SINGLE tile 수 예상밖:", single_tiles); return 1
        run_capture("SINGLE", single_tiles, s_rect, secs=75)
    finally:
        for p in procs:
            try: p.terminate()
            except Exception: pass
    print(f"\ndxcam DEBUG 로그: {_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
