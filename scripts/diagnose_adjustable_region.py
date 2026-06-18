"""영역 테두리(AdjustableRegionBorder) 시각 진단.

꺽쇠 제거 후 깔끔한 사각형 테두리인지, ✕/⏹ 버튼이 우상단 코너를 비웠는지,
대기/녹화 × video/gif 4상태를 PNG로 떠서 눈으로 확인.

출력: logs/_adjregion_*.png  (logs 는 gitignore)
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

os.environ.setdefault("KSTUDIO_SETTINGS_DIR", str(Path(os.environ["TEMP"]) / "kstudio_diag"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from screen_recorder.ui.overlay.adjustable_region import AdjustableRegionBorder  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "logs"
OUT.mkdir(exist_ok=True)


def grab_on_gray(w) -> QPixmap:
    """투명 배경이 보이도록 중간 회색 위에 위젯을 합성."""
    raw = w.grab()
    bg = QPixmap(raw.size())
    bg.fill(QColor("#808080"))
    p = QPainter(bg)
    p.drawPixmap(0, 0, raw)
    p.end()
    return bg


def main() -> None:
    app = QApplication.instance() or QApplication([])
    for mode in ("video", "gif"):
        for state in ("standby", "recording"):
            w = AdjustableRegionBorder((100, 100, 380, 260), mode=mode)
            if state == "recording":
                w.start_recording()
            w.resize(380, 260)
            w.show()
            app.processEvents()
            out = OUT / f"_adjregion_{mode}_{state}.png"
            grab_on_gray(w).save(str(out))
            print("wrote", out)
            w.stop()
    app.processEvents()


if __name__ == "__main__":
    main()
