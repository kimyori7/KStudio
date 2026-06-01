"""라이브러리 문서 항목 들여쓰기 측정 — 실제 LibraryPanel + _TwoLineDelegate.

문서(.md)는 썸네일이 없어 아이콘(48px)이 안 그려지지만, delegate 가 아이콘 칸을
항상 예약 → 텍스트가 ~54px 오른쪽으로 밀림(빈 플레이스홀더). 이 들여쓰기를 측정.

각 행의 '내용이 시작되는 x'(배경과 다른 첫 픽셀)를 스캔해 텍스트가 어디서
시작하는지 객관 측정한다.  python scripts/diagnose_lib_doc_indent.py
"""
import os
import sys
import threading

os.environ.setdefault("KSTUDIO_SETTINGS_DIR", os.path.join(os.environ["TEMP"], "kstudio_lib_probe"))
os.environ.setdefault("KSTUDIO_DISABLE_WEBENGINE", "1")
threading.Timer(12.0, lambda: os._exit(3)).start()

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

from screen_recorder.ui.theme import apply_theme

app = QApplication([])
apply_theme(app)

from screen_recorder.ui.library_model import EntryKind, LibraryModel
from screen_recorder.ui.docks.library_panel import LibraryPanel

model = LibraryModel()
base = r"C:/work/internal-project\기획서"
# 이미지(썸네일 있음) — 비교용. 빨강 32px 썸네일.
thumb = QImage(48, 32, QImage.Format_RGB32)
thumb.fill(QColor("#c0392b"))
model.add(EntryKind.IMAGE, thumbnail=thumb, source_label="region",
          display_name="shot.png", path=Path(base) / "shot.png")
# 문서(썸네일 없음).
model.add(EntryKind.DOCUMENT, thumbnail=QImage(), source_label="doc",
          display_name="1. 긴 한글 이름 문서 예시.md", path=Path(base) / "1. 긴 한글 이름 문서 예시.md")
model.add(EntryKind.DOCUMENT, thumbnail=QImage(), source_label="doc",
          display_name="2. 두 번째 문서_1차_v2.md", path=Path(base) / "2. 두 번째 문서_1차_v2.md")

panel = LibraryPanel(model, mode_controller=None)   # None → 필터 없음, 전부 표시
panel.resize(240, 320)
panel.show()
lw = panel.list_widget


def cap():
    pix = lw.viewport().grab()
    img = pix.toImage()
    out_png = os.path.join(os.environ["TEMP"], "lib_doc_indent.png")
    pix.save(out_png)
    lines = [f"RENDER viewport {pix.width()}x{pix.height()}  png={out_png}"]
    for row in range(lw.count()):
        it = lw.item(row)
        r = lw.visualItemRect(it)
        kind = it.data(Qt.UserRole + 1)
        bg = img.pixelColor(r.left() + 2, r.top() + 2)
        leftmost = None
        for yy in range(max(r.top(), 0), min(r.bottom(), pix.height() - 1)):
            for xx in range(max(r.left(), 0), min(r.right(), pix.width() - 1)):
                c = img.pixelColor(xx, yy)
                if abs(c.red()-bg.red())+abs(c.green()-bg.green())+abs(c.blue()-bg.blue()) > 50:
                    if leftmost is None or xx < leftmost:
                        leftmost = xx
                    break
        ind = (leftmost - r.left()) if leftmost is not None else None
        lines.append(f"row{row} kind={getattr(kind,'name',kind)} "
                     f"rect_left={r.left()} rect_h={r.height()} "
                     f"content_left={leftmost} indent={ind}")
    out = os.path.join(os.environ["TEMP"], "lib_doc_indent.txt")
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    print("WROTE", out)
    sys.stdout.flush()
    os._exit(0)


QTimer.singleShot(500, cap)
app.exec()
