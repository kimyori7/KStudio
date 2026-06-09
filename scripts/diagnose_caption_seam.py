"""캡션이 세그먼트 경계를 넘을 때 이음매에서 깜빡이지 않는지 시각 검증 (짧은 합성).

2초 경계로 쪼개지는 2-세그먼트 트랙 + 1~3초 캡션(경계 1번 넘음). export 후 이음매
앞뒤(1.8/2.0/2.2s) 프레임을 뽑아 캡션이 **끊김 없이** 보이는지 확인. d=0 seam fade 가
프레임을 비우는 역효과(블랭크)가 없는지 검증.
"""
from __future__ import annotations
import os, subprocess, sys, tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects import Sidecar
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.types.caption import CaptionEffect, Fade, Position
from screen_recorder.encode.export_pipeline import build_export_args

W, H = 854, 480


def main():
    ffmpeg = find_ffmpeg()
    d = Path(tempfile.mkdtemp(prefix="capseam_"))
    src = d / "src.mp4"
    # 4초 testsrc — 경계가 잘 보이게.
    subprocess.run([str(ffmpeg), "-y", "-f", "lavfi",
                    "-i", f"testsrc=size={W}x{H}:rate=30:duration=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)],
                   check=True, capture_output=True)

    # 2초 경계로 쪼갠 2-세그먼트 트랙 (같은 src), 캡션 1~3초 (경계 넘음).
    track = [
        VideoSegment(src=str(src), src_in_ms=0, src_out_ms=2000, src_duration_ms=4000,
                     media_kind="video", start_ms=0),
        VideoSegment(src=str(src), src_in_ms=2000, src_out_ms=4000, src_duration_ms=4000,
                     media_kind="video", start_ms=2000),
    ]
    cap = CaptionEffect(in_ms=1000, out_ms=3000, text="SEAM TEST 경계테스트",
                        fade=Fade(in_ms=300, out_ms=300),
                        position=Position(anchor="middle-center"))
    sc = Sidecar(source_path=str(src), source_hash="h", video_track=track, effects=[cap])

    out = d / "out.mp4"
    argv, pngs = build_export_args(sidecar=sc, src_path=src, dst_path=out,
        main_duration_ms=4000, surface_w=W, surface_h=H, ffmpeg_path=ffmpeg)
    r = subprocess.run(argv, capture_output=True, timeout=120)
    if r.returncode != 0 or not out.exists():
        print("export 실패:", r.stderr.decode("utf-8", "replace")[-800:]); return 1

    # 이음매(2.0s) 앞뒤 프레임 추출 — 캡션이 끊김 없이 보여야.
    for ts in (1.80, 1.95, 2.00, 2.05, 2.20):
        fp = d / f"f_{int(ts*100):03d}.png"
        subprocess.run([str(ffmpeg), "-y", "-ss", f"{ts}", "-i", str(out),
                        "-frames:v", "1", str(fp)], capture_output=True)
        print(f"프레임 t={ts}s → {fp}")
    print(f"\n폴더: {d}")
    print("기대: 1.8~2.2s 모든 프레임에 캡션이 보임(이음매 2.0 에서 사라지면 안 됨).")
    for p in pngs:
        try: Path(p).unlink(missing_ok=True)
        except OSError: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
