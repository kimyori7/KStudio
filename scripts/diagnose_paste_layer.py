"""붙여넣기 시각 검증 — 흰 캔버스에 빨강 20x20 을 붙여넣고 composite 결과를 PNG 로 저장.

좌측 상단 20x20 이 빨강, 나머지가 흰색이면 붙여넣기 + 렌더 경로 정상.
"""
import os
import sys
import tempfile

os.environ.setdefault("KSTUDIO_SETTINGS_DIR", tempfile.mkdtemp(prefix="kstudio_diag_"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _solid(w, h, color):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(color))
    return img


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from screen_recorder.ui.edit_tab import EditTab

    tab = EditTab.from_blank(QSize(60, 40), fill_white=True)
    tab.paste_image(_solid(20, 20, "red"))

    out = tab.image()  # canvas.composite()
    path = os.path.join(os.path.dirname(__file__), "..", "diag_paste_layer.png")
    out.save(path, "PNG")

    # 픽셀 샘플 콘솔 출력
    tl = out.pixelColor(5, 5).name()
    br = out.pixelColor(50, 35).name()
    print(f"saved {path}  size={out.width()}x{out.height()}")
    print(f"top-left(5,5)={tl}  (expect red #ff0000)")
    print(f"bottom-right(50,35)={br}  (expect white #ffffff)")


if __name__ == "__main__":
    main()
