"""QComboBox 펼침 화살표 진단 — border-삼각형(before) vs chevron PNG(after).

사용자 보고: "시스템 따라가기/1.0× 오른쪽 아이콘이 네모처럼 보인다 → SVG로 그려줘".
이 스크립트는 같은 콤보를 두 QSS(폴백 삼각형 / 새 chevron)로 렌더해 한 PNG 로 비교.
출력: logs/combobox_arrow_diag.png (+ 화살표 영역 4× 확대).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402
from PySide6.QtGui import QPixmap, QPainter  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from screen_recorder.ui import theme  # noqa: E402
from screen_recorder.ui.tokens import PALETTES  # noqa: E402


def _make_combo() -> QComboBox:
    c = QComboBox()
    c.addItems(["시스템 기본 따라가기", "1.0×", "Realtek Speakers"])
    c.setFixedSize(220, 36)
    return c


def _grab(qss: str) -> QPixmap:
    c = _make_combo()
    c.setStyleSheet(qss)
    c.ensurePolished()
    c.show()
    QApplication.processEvents()
    pm = c.grab()
    c.hide()
    return pm


def _zoom_right(pm: QPixmap, factor: int = 4, width: int = 44) -> QPixmap:
    """오른쪽 화살표 영역만 잘라 factor 배 확대."""
    crop = pm.copy(pm.width() - width, 0, width, pm.height())
    return crop.scaled(width * factor, pm.height() * factor,
                       Qt.IgnoreAspectRatio, Qt.FastTransformation)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    palette = PALETTES["video"]
    arrow_path = theme._chevron_arrow_png(palette.get("text_sub", ""))
    print(f"chevron PNG path = {arrow_path}")
    print(f"  exists = {arrow_path and os.path.exists(arrow_path)}")

    before = _grab(theme.build_qss(palette, None))          # border 삼각형(폴백)
    after = _grab(theme.build_qss(palette, arrow_path))     # chevron PNG

    bz = _zoom_right(before)
    az = _zoom_right(after)

    pad = 12
    w = max(before.width(), after.width()) + bz.width() + pad * 3
    h = before.height() + after.height() + pad * 3
    canvas = QPixmap(w, h)
    canvas.fill(Qt.black)
    pnt = QPainter(canvas)
    pnt.drawPixmap(pad, pad, before)
    pnt.drawPixmap(pad, pad + before.height() + pad, after)
    pnt.drawPixmap(pad + max(before.width(), after.width()) + pad, pad, bz)
    pnt.drawPixmap(pad + max(before.width(), after.width()) + pad,
                   pad + before.height() + pad, az)
    pnt.end()

    out_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "combobox_arrow_diag.png")
    canvas.save(out, "PNG")
    print(f"saved {os.path.abspath(out)}")
    print("위 = before(border 삼각형), 아래 = after(chevron PNG). 오른쪽 = 화살표 4× 확대.")


if __name__ == "__main__":
    main()
