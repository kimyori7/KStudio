"""auto-trim 아이콘을 PNG 로 렌더해 시각 확인 (UI 회의=진단 PNG 규칙)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor
from PySide6.QtCore import Qt

app = QGuiApplication.instance() or QGuiApplication(sys.argv)
from screen_recorder.ui.icons import load_icon, has_icon

assert has_icon("auto-trim"), "auto-trim 아이콘이 _PATHS 에 없음"

out = QImage(96, 96, QImage.Format_ARGB32)
out.fill(QColor("#23262E"))  # 팔레트 배경과 유사한 어두운 색
p = QPainter(out)
icon = load_icon("auto-trim", size=64)
icon.paint(p, 16, 16, 64, 64)
p.end()
dest = Path(__file__).resolve().parents[1] / "diag_auto_trim_icon.png"
out.save(str(dest))
print(f"saved {dest}")
