"""진단: MarkdownTab 상단 툴바가 폰트 컨트롤 추가 후에도 안 비좁은지 PNG 로 확인.

뷰 버튼 3개 + 편집[A−][A+] + 미리보기[A−][A+] + ↺기본 + 라벨 2개 = 다소 빽빽.
정상 너비에서 겹침/넘침 없는지 눈으로 확인 (사용자 UI-진단 규칙).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("KSTUDIO_DISABLE_WEBENGINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.ui import theme  # noqa: E402
from screen_recorder.ui.markdown_tab import MarkdownTab, ViewMode  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "diag_markdown_font"
OUT.mkdir(exist_ok=True)


def grab(tab: MarkdownTab, name: str, width: int) -> None:
    tab.resize(width, 360)
    tab.show()
    QApplication.processEvents()
    tab.grab().save(str(OUT / f"{name}.png"))
    tab.hide()


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply_theme(app, "video")

    for mode, tag in ((ViewMode.SPLIT, "split"),
                      (ViewMode.EDITOR, "editor"),
                      (ViewMode.PREVIEW, "preview")):
        tab = MarkdownTab.from_blank()
        tab.editor.setPlainText("# 제목\n본문 줄 1\n본문 줄 2")
        tab.set_view_mode(mode)
        grab(tab, f"toolbar_{tag}_900", 900)   # 일반 너비
    # 좁은 너비에서 겹침 확인
    narrow = MarkdownTab.from_blank()
    narrow.set_view_mode(ViewMode.SPLIT)
    grab(narrow, "toolbar_split_560", 560)

    print(f"PNG 저장: {OUT}")


if __name__ == "__main__":
    main()
