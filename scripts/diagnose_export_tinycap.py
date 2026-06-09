"""discriminator: 캡션 동인이 '프레임 크기'인가? render_caption_png 를 작은 PNG 로
몽키패치하고 실제 사이드카(speed + 느린 concat) 그대로 full 재측정.

peak 이 9.3GB → bounded 로 무너지면 = 프레임 크기가 레버 → bbox 크롭이 정답.
안 무너지면 = 다른 버퍼(packet queue/decode) → bbox 크롭은 또 헛다리.
"""
from __future__ import annotations
import copy, os, re, subprocess, sys, tempfile, threading, time, json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
_app = QApplication.instance() or QApplication([])

SRC = Path(r"E:\KStudio_Image\Video\rec_20260609_164813.mp4")
from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects.sidecar_store import SidecarStore
from screen_recorder.encode import export_pipeline as ep
from screen_recorder.services.media_probe import probe_video_size

_FRAME_RE = re.compile(rb"frame=\s*(\d+)")


def _run(argv, abort_gb=8.0, abort_s=25.0):
    import psutil
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    ps = psutil.Process(proc.pid); t0 = time.monotonic()
    peak = [0.0]; last = [0]; verdict = ["완료"]
    def reader():
        for raw in proc.stderr:
            m = _FRAME_RE.search(raw)
            if m: last[0] = int(m.group(1))
    threading.Thread(target=reader, daemon=True).start()
    while proc.poll() is None:
        try:
            rss = ps.memory_info().rss
            for c in ps.children(recursive=True):
                try: rss += c.memory_info().rss
                except psutil.Error: pass
            peak[0] = max(peak[0], rss)
        except psutil.Error: break
        if rss > abort_gb*1e9: verdict[0]="8GB중단"; proc.kill(); break
        if time.monotonic()-t0 > abort_s: verdict[0]="25s중단"; proc.kill(); break
        time.sleep(0.5)
    return round(peak[0]/1e9,2), last[0], verdict[0]


def main():
    ffmpeg = find_ffmpeg()
    sidecar = SidecarStore(Path(r"E:\KStudio_Image\Video\sidecars")).load_for(SRC)
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe")
    r = subprocess.run([str(ffprobe),"-v","error","-show_entries","format=duration",
                        "-of","json",str(SRC)], capture_output=True, text=True)
    dur = int(float(json.loads(r.stdout or "{}").get("format",{}).get("duration",0) or 0)*1000)
    sw, sh = probe_video_size(str(SRC))

    # render_caption_png 를 작은 PNG 로 교체 (실제 사이드카는 그대로).
    def tiny_cap(cap, *, surface_w, surface_h, dst, sample_ms=None):
        img = QImage(64, 64, QImage.Format_RGBA8888)
        img.fill(QColor(255, 255, 0, 200))
        img.save(str(dst), "PNG")
    ep.render_caption_png = tiny_cap

    sc = copy.deepcopy(sidecar)
    out = Path(tempfile.mkdtemp(prefix="tinycap_")) / "out.mp4"
    argv, pngs = ep.build_export_args(
        sidecar=sc, src_path=SRC, dst_path=out,
        main_duration_ms=dur, surface_w=sw, surface_h=sh, ffmpeg_path=ffmpeg,
    )
    print("full_TINYCAP (캡션 PNG 만 64x64 로):")
    peak, frame, v = _run(argv)
    print(f"  peak={peak}GB frame={frame} {v}")
    print(f"\n비교: full(전체화면 캡션)=9.3GB폭증.  이번이 <3GB 면 = 프레임 크기가 레버.")
    for p in pngs:
        try: Path(p).unlink(missing_ok=True)
        except OSError: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
