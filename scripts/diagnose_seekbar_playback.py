"""영상 탭 시크 바(재생 바) 가시성 진단 — 재생 모드 / 편집 모드 각각 grab → PNG.

회귀: 시크 바가 VideoTimeline 안에 있는데 편집 모드 OFF 시 타임라인 전체가 숨겨져
재생 모드에서 시크 바가 사라졌다. 이 스크립트는 두 모드를 PNG 로 떠서 육안 검증한다.

사용법:
    python scripts/diagnose_seekbar_playback.py
출력:
    scripts/_diag_seekbar_playback.png  (재생 모드 — 시크 바 보여야 함)
    scripts/_diag_seekbar_edit.png      (편집 모드 — 슬라이더+트랙+효과 줄 전부)
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

# 사용자 settings/사이드카 보호 — 절대 실제 폴더 안 건드림 (memory: dev run overwrites settings).
_tmp = tempfile.mkdtemp(prefix="kstudio_diag_")
os.environ.setdefault("KSTUDIO_SETTINGS_DIR", str(Path(_tmp) / "settings"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.core.settings import PlayerSettings  # noqa: E402
from screen_recorder.ui.video_tab import VideoTab  # noqa: E402


def _make_gif(path: Path) -> None:
    frames = [
        Image.new("RGB", (320, 180), color=(40, 90, 160)),
        Image.new("RGB", (320, 180), color=(160, 90, 40)),
    ]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True,
        append_images=[frames[1]], loop=0, duration=500,
    )
    path.write_bytes(buf.getvalue())


def _grab(tab: VideoTab, out: Path) -> None:
    pix = tab.grab()
    pix.save(str(out))
    print(f"  saved {out.name}  ({pix.width()}x{pix.height()})")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    sidecar_dir = Path(_tmp) / "sidecars"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    gif = Path(_tmp) / "diag.gif"
    _make_gif(gif)

    tab = VideoTab(
        path=gif, source_label="region", duration_ms=8000,
        player_settings=PlayerSettings(), sidecar_dir=sidecar_dir,
    )
    tab.resize(920, 660)
    tab.show()
    app.processEvents()
    app.processEvents()

    out_dir = ROOT / "scripts"
    print("재생 모드 (편집 OFF):")
    print(f"  timeline.isHidden()      = {tab.timeline.isHidden()}")
    print(f"  _top_scroll.isHidden()   = {tab.timeline._top_scroll.isHidden()}  (시크 바 컨테이너)")
    print(f"  _scroll.isHidden()       = {tab.timeline._scroll.isHidden()}  (효과 줄 컨테이너)")
    print(f"  effect_lanes.isHidden()  = {tab.timeline.effect_lanes.isHidden()}")
    _grab(tab, out_dir / "_diag_seekbar_playback.png")

    tab.set_edit_mode(True)
    app.processEvents()
    app.processEvents()
    print("편집 모드 (ON):")
    print(f"  timeline.isHidden()      = {tab.timeline.isHidden()}")
    print(f"  _top_scroll.isHidden()   = {tab.timeline._top_scroll.isHidden()}")
    print(f"  _scroll.isHidden()       = {tab.timeline._scroll.isHidden()}")
    print(f"  effect_lanes.isHidden()  = {tab.timeline.effect_lanes.isHidden()}")
    _grab(tab, out_dir / "_diag_seekbar_edit.png")

    tab.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    main()
