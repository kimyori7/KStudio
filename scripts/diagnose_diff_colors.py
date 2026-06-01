"""진단: DIFF 뷰의 줄/글자 색 + 가운데 개요 띠(overview ruler)가 다크(document)
테마 배경 위에서 실제로 구분되는지 PNG 로 확인.

배경(2026-05-29): DIFF 색은 spec 에서 "구현 시 스크린샷으로 대비 확인" 으로 미뤘다.
배경(2026-06-01): 개요 띠 추가 — 줄 배경(옅은)색은 16px 폭 띠에서 안 보이므로 진한
*_tick 색을 별도로 둔다. 띠 폭에서 빨강/초록/호박이 또렷이 구분되는지가 핵심(gating).

- diff_colors.png: 전체 뷰(좌/우 패널 + 가운데 띠) — 띠가 문서 전체 분포를 보여주는지.
- diff_overview_bar.png: 띠만 가로로 확대(8배) — 눈금 색이 띠 폭에서 보이는지 확대 검증.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("KSTUDIO_DISABLE_WEBENGINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.ui import theme  # noqa: E402
from screen_recorder.ui.markdown.diff_view import DiffView, compute_diff  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "diag_diff_colors"
OUT.mkdir(exist_ok=True)

# 분포가 보이도록 위/중간/아래에 차이를 흩뿌린 긴 두 문서.
_COMMON = [f"공통 줄 {i}" for i in range(40)]
LEFT_LINES = list(_COMMON)
RIGHT_LINES = list(_COMMON)
# 위쪽: 왼쪽에만 있는 줄 3개(삭제=빨강) — 줄 2~4.
LEFT_LINES[2:2] = ["삭제될 줄 A", "삭제될 줄 B", "삭제될 줄 C"]
# 중간: 한 줄 변경(호박 + 글자) — 줄 ~20.
LEFT_LINES[22] = "중간 cat 줄"
RIGHT_LINES[19] = "중간 cot 줄"
# 아래: 오른쪽에만 추가(초록) — 끝부분.
RIGHT_LINES += ["추가된 줄 X", "추가된 줄 Y"]

LEFT = "\n".join(LEFT_LINES)
RIGHT = "\n".join(RIGHT_LINES)


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply_theme(app, "document")    # 프로덕션처럼 다크 amber 테마 적용

    v = DiffView()
    v.left.setPlainText(LEFT)
    v.right.setPlainText(RIGHT)
    v._recompute()
    v.resize(760, 460)
    v.show()
    QApplication.processEvents()

    full = OUT / "diff_colors.png"
    v.grab().save(str(full))

    # 띠만 가로 8배 확대 → 16px 폭에서 색이 보이는지 또렷이 검증.
    bar_pix = v.overview.grab()
    zoom = bar_pix.scaled(bar_pix.width() * 8, bar_pix.height(),
                          Qt.IgnoreAspectRatio, Qt.FastTransformation)
    bar = OUT / "diff_overview_bar.png"
    zoom.save(str(bar))

    lm, rm = compute_diff(LEFT, RIGHT)
    print(f"left line marks : {[(m.line, m.kind) for m in lm.lines]}")
    print(f"right line marks: {[(m.line, m.kind) for m in rm.lines]}")
    print(f"PNG: {full}")
    print(f"PNG: {bar}")


if __name__ == "__main__":
    main()
