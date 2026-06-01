"""새 스크롤바(미니멀 pill) 검증 — 실제 앱처럼 전역 테마 + 에디터 font-only sheet.

video/image/document 세 모드에서 에디터 스크롤바를 렌더 → 우측 스트립 6배 확대.
QSS 파싱 경고(있다면)는 stderr 로 나온다.  python scripts/diagnose_scrollbar_after.py
"""
import os
import sys
import threading

os.environ.setdefault("KSTUDIO_SETTINGS_DIR", os.path.join(os.environ["TEMP"], "kstudio_sb_probe"))
os.environ.setdefault("KSTUDIO_DISABLE_WEBENGINE", "1")
threading.Timer(15.0, lambda: os._exit(3)).start()

from PySide6.QtCore import QTimer, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QFont
from PySide6.QtWidgets import QApplication

from screen_recorder.ui.theme import apply_theme

app = QApplication([])

from screen_recorder.ui.markdown.editor import MarkdownEditor

CONTENT = "\n".join(f"line {i} 상태 매핑 텍스트 padding xxxxxxxxxx" for i in range(1, 60))

# 실제 앱처럼 child 위젯으로 렌더(splitter 안의 자식). top-level 창으로 띄우면
# 가로 스크롤바 자리에 Windows 네이티브 focus-edge 파란선 아티팩트가 끼므로 컨테이너로 감싼다.
from PySide6.QtWidgets import QWidget, QVBoxLayout
_host = QWidget()
_lay = QVBoxLayout(_host)
_lay.setContentsMargins(8, 8, 8, 8)
ed = MarkdownEditor()
ed.setPlainText(CONTENT)
ed.set_font_point_size(11)   # 실제 앱이 항상 호출하는 경로 (font-only per-widget sheet)
_lay.addWidget(ed)
_host.resize(340, 300)
_host.show()
ed.verticalScrollBar().setValue(14)

MODES = ["video", "image", "document"]
STRIP_W = 22
ZOOM = 6


def cap():
    strips = []
    for mode in MODES:
        apply_theme(app, mode)
        app.processEvents()
        img = ed.grab().toImage()
        # 핸들 색 샘플 (1/3 높이, 우측)
        y = img.height() // 3
        sample = None
        for x in range(img.width() - 16, img.width()):
            c = img.pixelColor(x, y)
            if c.red() + c.green() + c.blue() > (15 + 17 + 21) + 30:
                sample = (x, c.red(), c.green(), c.blue()); break
        strip = img.copy(QRect(img.width() - STRIP_W, 0, STRIP_W, min(280, img.height())))
        strips.append((f"{mode}  handle={sample}", strip))

    lab_h = 30; gap = 16; cell_h = 280
    W = len(strips) * (STRIP_W * ZOOM + gap) + gap
    H = lab_h + cell_h * ZOOM + gap * 2
    canvas = QImage(W, H, QImage.Format_RGB32); canvas.fill(QColor("#101216"))
    p = QPainter(canvas); p.setPen(QColor("#FFFFFF"))
    f = QFont("Consolas"); f.setPointSize(9); p.setFont(f)
    for i, (label, strip) in enumerate(strips):
        big = strip.scaled(STRIP_W * ZOOM, strip.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        x = gap + i * (STRIP_W * ZOOM + gap)
        p.drawText(QRect(x, 4, STRIP_W * ZOOM + gap, lab_h), Qt.AlignLeft | Qt.AlignTop, label)
        p.drawImage(x, lab_h + gap, big)
    p.end()
    out = os.path.join(os.environ["TEMP"], "scrollbar_after.png")
    canvas.save(out)
    print("WROTE", out)
    sys.stdout.flush()
    os._exit(0)


QTimer.singleShot(500, cap)
app.exec()
