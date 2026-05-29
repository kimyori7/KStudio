"""문서(amber) vs 이미지(emerald) 액센트 비교 — checked 버튼/슬라이더로 시각 확인."""
import sys
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QSlider)
from PySide6.QtCore import Qt
from screen_recorder.ui.theme import build_qss
from screen_recorder.ui.tokens import PALETTES


def panel(name):
    w = QWidget()
    w.setStyleSheet(build_qss(PALETTES[name]))
    lay = QVBoxLayout(w)
    lay.addWidget(QLabel(f"  {name}  "))
    row = QHBoxLayout()
    b1 = QPushButton("문서"); b1.setCheckable(True); b1.setChecked(True)
    b2 = QPushButton("일반"); b2.setCheckable(True)
    row.addWidget(b1); row.addWidget(b2)
    lay.addLayout(row)
    s = QSlider(Qt.Horizontal); s.setValue(60)
    lay.addWidget(s)
    return w


app = QApplication(sys.argv)
host = QWidget()
hl = QHBoxLayout(host)
for n in ("image", "document"):
    hl.addWidget(panel(n))
host.resize(520, 160)
host.show()
app.processEvents()
host.grab().save("test_theme_compare.png")
print("saved test_theme_compare.png")
