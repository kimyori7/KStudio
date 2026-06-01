"""진단: DIFF 뷰의 줄/글자 색이 다크(document) 테마 배경 위에서 실제로 구분되는지 확인.

배경(2026-05-29): DIFF 색은 spec 에서 "구현 시 스크린샷으로 대비 확인" 으로 미뤘다.
added/deleted/changed 줄 색 + 변경 글자 오버레이가 어두운 pane 배경 위에서 눈에 보이는지,
FullWidthSelection 이 줄 전체를 칠하는지 PNG 로 검증한다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("KSTUDIO_DISABLE_WEBENGINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.ui import theme  # noqa: E402
from screen_recorder.ui.markdown.diff_view import DiffView  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "diag_diff_colors"
OUT.mkdir(exist_ok=True)

LEFT = "keep 같은 줄1\nonly-left 삭제될 줄(빨강)\nkeep 같은 줄2\ncat\nkeep 같은 줄3"
RIGHT = "keep 같은 줄1\nkeep 같은 줄2\ncot\nkeep 같은 줄3\nonly-right 추가된 줄(초록)"


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply_theme(app, "document")    # 프로덕션처럼 다크 amber 테마 적용

    v = DiffView()
    v.left.setPlainText(LEFT)
    v.right.setPlainText(RIGHT)
    v._recompute()
    v.resize(760, 200)
    v.show()
    QApplication.processEvents()
    out = OUT / "diff_colors.png"
    v.grab().save(str(out))
    print(f"left marks: {[(m.line, m.kind) for m in __import__('screen_recorder.ui.markdown.diff_view', fromlist=['compute_diff']).compute_diff(LEFT, RIGHT)[0].lines]}")
    print(f"PNG: {out}")


if __name__ == "__main__":
    main()
