"""진단: 전역 테마 QSS(QWidget{font}) 가 적용된 상태에서 편집기 폰트 크기를
바꾸는 올바른 방법 확인.

배경(2026-05-29): theme.build_qss 의 `QMainWindow, QWidget { font-size:10pt }` 는
QPlainTextEdit 에도 적용되고, QSS 폰트는 setFont() 를 덮어쓴다. 따라서 폰트 줌이
setFont 기반이면 프로덕션(테마 적용)에서 무효가 될 수 있다.

이 스크립트는 테마를 적용한 뒤 (A) setFont, (B) 위젯 setStyleSheet 두 방식으로
편집기 폰트를 키워 PNG 로 저장 → 실제로 글자가 커지는 방식이 무엇인지 눈으로 확인.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("KSTUDIO_DISABLE_WEBENGINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.ui import theme  # noqa: E402
from screen_recorder.ui.markdown.editor import MarkdownEditor  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "diag_markdown_font"
OUT.mkdir(exist_ok=True)
SAMPLE = "# 제목 1\n본문 한 줄\n```python\ndef f():\n    return 42\n```\n끝줄"


def grab(ed: MarkdownEditor, name: str, note: str) -> None:
    ed.setPlainText(SAMPLE)
    ed.resize(360, 220)
    ed.show()
    QApplication.processEvents()
    ed.grab().save(str(OUT / f"{name}.png"))
    resolved = ed.font()
    print(f"[{name}] {note}\n"
          f"    editor.font() = {resolved.family()} {resolved.pointSize()}pt")
    ed.hide()


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply_theme(app, "video")   # 프로덕션처럼 전역 QSS 적용

    # 기준: 아무것도 안 함 (테마 10pt 가 그대로 보일 것).
    base = MarkdownEditor()
    grab(base, "00_baseline", "테마만 적용 (기대: Segoe UI 10pt)")

    # A) setFont 24pt — QSS 가 덮어쓰면 무효.
    a = MarkdownEditor()
    f = a.font(); f.setFamily("Consolas"); f.setPointSize(24); a.setFont(f)
    grab(a, "10_setfont_24", "setFont(Consolas 24) — QSS 가 이기면 그대로 10pt 로 보임")

    # B) 위젯 setStyleSheet 24pt — 위젯별 규칙이 전역보다 우선.
    b = MarkdownEditor()
    fm = QFontMetrics(QFont("Consolas", 24))
    b.setTabStopDistance(4 * fm.horizontalAdvance(" "))
    b.setStyleSheet('QPlainTextEdit { font-family:"Consolas",monospace; font-size:24pt; }')
    grab(b, "20_stylesheet_24", "setStyleSheet 24pt — 글자가 실제로 커져야 정답")

    print(f"\nPNG 저장: {OUT}")


if __name__ == "__main__":
    main()
