"""미니 컨트롤(녹화 중 우하단) 버튼 아이콘 진단.

옛 유니코드 글리프(⏸ ⏹ ✕) 를 SVG 아이콘으로 바꾼 뒤, 실제 테마(apply_theme)
적용 상태에서:
  1) 세 아이콘(pause/stop/x) 이 어두운 배경 위에 보이는가(대비),
  2) stop 의 fill="currentColor" 가 검정이 아니라 테마색으로 차는가,
  3) disabled 변형이 회색으로 떨어지는가(채움 포함),
  4) circle-record(같은 wrapper 의 currentColor fill) 가 회귀 없이 색을 따라가는가
를 PNG 로 굽고 평균색을 출력해 눈+수치로 확인한다.

출력: logs/_diag_out/mini_control_icons.png  (+ 콘솔에 픽셀 통계)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# dev 실행이 사용자 settings 를 덮지 않게 격리 (메모리 규칙).
os.environ.setdefault("KSTUDIO_SETTINGS_DIR", str(Path(__file__).resolve().parent.parent / "logs" / "_diag_settings"))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import QSize

from screen_recorder.ui.theme import apply_theme
from screen_recorder.ui import icons
from screen_recorder.ui.overlay.mini_control import MiniControl

OUT_DIR = Path(__file__).resolve().parent.parent / "logs" / "_diag_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _avg_nontransparent(img: QImage) -> tuple[int, int, int, int, int]:
    """알파>0 픽셀의 평균 RGB + 불투명 픽셀 수 반환."""
    img = img.convertToFormat(QImage.Format_ARGB32)
    r = g = b = n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            px = img.pixelColor(x, y)
            if px.alpha() > 10:
                r += px.red(); g += px.green(); b += px.blue(); n += 1
    if n == 0:
        return (0, 0, 0, 0, 0)
    return (r // n, g // n, b // n, n, img.width() * img.height())


def _icon_to_image(name: str, color=None, size=24) -> QImage:
    pm = icons._render_pixmap(name, size, color or icons.COLOR_BASE)
    return pm.toImage()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "video")

    # --- 1) 개별 아이콘 통계 (검정 fill 회귀 탐지) ---
    print("=== icon avg RGB (non-transparent px) ===")
    for name, color, label in [
        ("pause", None, "pause base"),
        ("stop", None, "stop base (fill=currentColor)"),
        ("stop", icons.COLOR_DISABLED, "stop disabled"),
        ("x", None, "x base"),
        ("circle-record", None, "circle-record base (regression check)"),
    ]:
        rr, gg, bb, n, total = _avg_nontransparent(_icon_to_image(name, color))
        verdict = ""
        if name == "stop" and color is None:
            verdict = "  <-- 검정(0,0,0)이면 currentColor 미해석 = stroke-only 로 폴백 필요"
        print(f"  {label:38s} rgb=({rr:3d},{gg:3d},{bb:3d}) px={n}/{total}{verdict}")

    # --- 2) 실제 MiniControl 렌더 (테마 적용, Normal + Disabled 한 줄씩) ---
    container = QWidget()
    v = QVBoxLayout(container)

    mc_normal = MiniControl()
    v.addWidget(QLabel("MiniControl — normal"))
    v.addWidget(mc_normal)

    # disabled 버전: 같은 위젯을 복제하기 어려우니 버튼만 비활성으로 한 벌 더.
    row = QWidget()
    h = QHBoxLayout(row)
    h.addWidget(QLabel("disabled:"))
    for name in ("pause", "stop", "x"):
        b = QPushButton()
        b.setIcon(icons.load_icon(name, size=18))
        b.setIconSize(QSize(18, 18))
        b.setFixedWidth(32)
        b.setEnabled(False)
        h.addWidget(b)
    v.addWidget(row)

    container.resize(360, 160)
    container.show()
    app.processEvents()

    pm = QPixmap(container.size())
    container.render(pm)
    out = OUT_DIR / "mini_control_icons.png"
    pm.save(str(out), "PNG")
    print(f"\nsaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
