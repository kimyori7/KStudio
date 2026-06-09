"""export OOM 요인 분리 — 실제 사이드카에서 효과를 하나씩 떼며 RSS 측정.

[0:v] fan-out 가설(틀림)·caption 가설(틀림) 이후. 진짜 build_export_args 로 실원본을
돌리되 effects 를 변형해 어느 요인이 버퍼링을 만드는지 본다.

variants:
  full        : 원본 사이드카 (speed + caption6 + 2seg track)  — baseline OOM
  no_speed    : SpeedEffect 제거 (caption + track 유지)
  no_caption  : CaptionEffect 전부 제거 (speed + track 유지)
  bare        : speed + caption 모두 제거 (track concat 만)

각 variant: RSS 0.5s 샘플 → peak, 8GB 또는 25s 에서 중단. peak < 3GB + frame 증가 =
bounded(정상). peak 폭증 + frame=0 = 그 요인이 버퍼링 동인.
"""
from __future__ import annotations
import copy
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

SRC = Path(r"E:\KStudio_Image\Video\rec_20260609_164813.mp4")

from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects.sidecar_store import SidecarStore
from screen_recorder.encode.export_pipeline import build_export_args
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.services.media_probe import probe_video_size

_FRAME_RE = re.compile(rb"frame=\s*(\d+)")
ABORT_GB = 8.0
ABORT_S = 25.0


def _probe_dur_ms(ffmpeg, src):
    import json
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe")
    r = subprocess.run([str(ffprobe), "-v", "error", "-show_entries",
                        "format=duration", "-of", "json", str(src)],
                       capture_output=True, text=True)
    return int(float(json.loads(r.stdout or "{}").get("format", {}).get("duration", 0) or 0) * 1000)


def _run(argv) -> dict:
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    import psutil
    ps = psutil.Process(proc.pid)
    t0 = time.monotonic()
    peak = [0.0]; last = [0]; verdict = ["완료"]

    def reader():
        assert proc.stderr is not None
        for raw in proc.stderr:
            m = _FRAME_RE.search(raw)
            if m:
                last[0] = int(m.group(1))
    threading.Thread(target=reader, daemon=True).start()

    while proc.poll() is None:
        try:
            rss = ps.memory_info().rss
            for c in ps.children(recursive=True):
                try: rss += c.memory_info().rss
                except psutil.Error: pass
            peak[0] = max(peak[0], rss)
        except psutil.Error:
            break
        el = time.monotonic() - t0
        if rss > ABORT_GB * 1e9:
            verdict[0] = f"{ABORT_GB}GB초과중단"; proc.kill(); break
        if el > ABORT_S:
            verdict[0] = f"{ABORT_S:.0f}s중단"; proc.kill(); break
        time.sleep(0.5)
    return {"peak_gb": round(peak[0] / 1e9, 2), "frame": last[0], "verdict": verdict[0]}


def main() -> int:
    ffmpeg = find_ffmpeg()
    sidecar = SidecarStore(Path(r"E:\KStudio_Image\Video\sidecars")).load_for(SRC)
    if sidecar is None:
        print("사이드카 없음"); return 1
    dur = _probe_dur_ms(ffmpeg, SRC)
    sw, sh = probe_video_size(str(SRC))

    def make(effects_filter):
        sc = copy.deepcopy(sidecar)
        sc.effects = [e for e in sc.effects if effects_filter(e)]
        return sc

    variants = {
        "full":       make(lambda e: True),
        "no_speed":   make(lambda e: not isinstance(e, SpeedEffect)),
        "no_caption": make(lambda e: not isinstance(e, CaptionEffect)),
        "bare":       make(lambda e: not isinstance(e, (SpeedEffect, CaptionEffect))),
    }

    rows = []
    for name, sc in variants.items():
        n_eff = [type(e).__name__ for e in sc.effects]
        out = Path(tempfile.mkdtemp(prefix=f"iso_{name}_")) / "out.mp4"
        argv, pngs = build_export_args(
            sidecar=sc, src_path=SRC, dst_path=out,
            main_duration_ms=dur, surface_w=sw, surface_h=sh, ffmpeg_path=ffmpeg,
        )
        print(f"\n>>> {name}: effects={n_eff}")
        r = _run(argv)
        print(f"    peak={r['peak_gb']}GB  frame={r['frame']}  {r['verdict']}")
        rows.append((name, r))
        for p in pngs:
            try: Path(p).unlink(missing_ok=True)
            except OSError: pass

    print("\n================ 요약 ================")
    print(f"{'variant':12} {'peak(GB)':>9} {'frame':>7}  결과")
    for name, r in rows:
        bounded = "BOUNDED✓" if r["peak_gb"] < 3.0 else "폭증✗"
        print(f"{name:12} {r['peak_gb']:>9} {r['frame']:>7}  {bounded} ({r['verdict']})")
    print("\nbounded 인 variant 가 제거한 효과 = 버퍼링 동인.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
