"""VideoTab 생성 latency 측정 — 모드 전환 시 사용자가 보는 지연의 원인.

사용:
    python -u tools/perf_test_tab_creation.py
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QMainWindow

from screen_recorder.ui.video_tab import VideoTab
from screen_recorder.core.settings import PlayerSettings


def main():
    target_dir = Path(r"C:\Users\me\KStudio\Video\발표용")
    mp4s = sorted([p for p in target_dir.iterdir() if p.suffix.lower() == ".mp4"],
                  key=lambda p: -p.stat().st_size)
    if not mp4s:
        print("no mp4")
        return 2

    app = QApplication(sys.argv)

    # 4 개 영상에 대해 cold/warm VideoTab 생성 측정.
    for target in mp4s[:4]:
        size = target.stat().st_size / 1024 / 1024
        print(f"\n=== {target.name} ({size:.0f}MB) ===")
        for i in range(2):
            t0 = time.perf_counter()
            tab = VideoTab(
                path=target,
                source_label="test",
                duration_ms=0,
                player_settings=PlayerSettings(),
            )
            dt = (time.perf_counter() - t0) * 1000
            phase = "cold" if i == 0 else "warm"
            print(f"  {phase}  {dt:6.1f} ms")
            tab.deleteLater()

    return 0


if __name__ == "__main__":
    sys.exit(main())
