"""디자인 색감 비교 mockup — 진짜 KStudio 코드는 안 건드리고 standalone.

여러 팔레트를 한 창에서 옆으로 비교한다. 마음에 드는 걸 고른 뒤 그 값을
실제 theme.py 에 반영하는 용도. 폰트는 시스템 기본 (Segoe UI/맑은 고딕).

실행:
    .venv\\Scripts\\python.exe tools\\design_mockup.py
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)


# ----- 팔레트 카탈로그 -----
# 공통 회색 베이스 (Mono 톤) — 액센트만 다르게.
_BASE = {
    "bg":            "#0F1115",
    "surface":       "#1A1D24",
    "surface_alt":   "#252932",
    "border":        "#2F343F",
    "border_strong": "#3F4554",
    "text":          "#E8EAED",
    "text_sub":      "#9CA3AF",
    "text_dim":      "#6B7280",
    "button_bg":     "#1A1D24",
}

PALETTES: dict[str, dict[str, str]] = {
    "Emerald 진한\n(neon 톤다운)": {
        # 직전 #34D399 가 너무 빛났음 → 한 스텝 어둡고 진한 emerald-500.
        **_BASE,
        "primary":       "#10B981",   # emerald-500
        "primary_hover": "#34D399",
        "selection":     "#065F46",   # emerald-800
    },
    "Sage 무광\n(저채도 자연톤)": {
        # 채도 낮춘 회녹색 — 차분, 잘 안 거슬림. 약초·세이지 톤.
        **_BASE,
        "primary":       "#86A678",
        "primary_hover": "#A3BF96",
        "selection":     "#4F6647",
    },
    "Teal 쿨톤\n(청록·professional)": {
        # 더 블루 쪽으로 — 더 차분하고 도구적인 인상.
        **_BASE,
        "primary":       "#14B8A6",   # teal-500
        "primary_hover": "#2DD4BF",   # teal-400
        "selection":     "#115E59",   # teal-800
    },
    "Forest 깊은\n(짙은 솔리드)": {
        # 진한 녹색 — 더 무게감 있고 어른스러운.
        **_BASE,
        "primary":       "#16A34A",   # green-600
        "primary_hover": "#22C55E",   # green-500
        "selection":     "#14532D",   # green-900
    },
}


def build_qss(p: dict[str, str]) -> str:
    """팔레트 dict 에서 QSS 문자열 생성 (widget-scoped)."""
    return f"""
    QFrame#paletteCard {{
        background-color: {p["bg"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 8px;
    }}
    QLabel {{
        color: {p["text"]};
        background: transparent;
    }}
    QLabel[role="title"] {{
        color: {p["text"]};
        font-weight: 700;
        font-size: 11pt;
    }}
    QLabel[role="muted"] {{
        color: {p["text_sub"]};
        font-size: 9pt;
    }}
    QLabel[role="caption"] {{
        color: {p["text_dim"]};
        font-size: 8pt;
    }}
    QLineEdit {{
        background: {p["surface"]};
        color: {p["text"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 4px;
        padding: 5px 8px;
        min-height: 20px;
        selection-background-color: {p["primary"]};
        selection-color: {p["bg"]};
    }}
    QLineEdit:focus {{
        border: 1px solid {p["primary"]};
    }}
    QPushButton {{
        background: {p["button_bg"]};
        color: {p["text"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 4px;
        padding: 5px 12px;
        min-height: 22px;
    }}
    QPushButton:hover {{
        background: {p["surface_alt"]};
        border: 1px solid {p["primary"]};
    }}
    QPushButton:checked {{
        background: {p["selection"]};
        border: 1px solid {p["primary"]};
        color: #FFFFFF;
        font-weight: 600;
    }}
    QPushButton:disabled {{
        background: {p["surface"]};
        color: {p["text_dim"]};
        border: 1px solid {p["border"]};
    }}
    QListWidget {{
        background: {p["surface"]};
        border: 1px solid {p["border"]};
        border-radius: 4px;
        outline: 0;
        padding: 4px 0;
    }}
    QListWidget::item {{
        padding: 6px 10px;
        color: {p["text_sub"]};
        border-left: 3px solid transparent;
    }}
    QListWidget::item:hover {{
        background: {p["surface_alt"]};
        color: {p["text"]};
    }}
    QListWidget::item:selected {{
        background: {p["surface_alt"]};
        color: {p["text"]};
        border-left: 3px solid {p["primary"]};
        font-weight: 600;
    }}
    """


def build_card(name: str, palette: dict[str, str]) -> QFrame:
    """한 팔레트에 대한 미리보기 카드."""
    card = QFrame()
    card.setObjectName("paletteCard")
    card.setStyleSheet(build_qss(palette))

    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)

    # 헤더
    title = QLabel(name)
    title.setProperty("role", "title")
    layout.addWidget(title)

    hex_info = QLabel(f'bg {palette["bg"]} · 액센트 {palette["primary"]}')
    hex_info.setProperty("role", "muted")
    layout.addWidget(hex_info)

    # 사이드바 모사
    sidebar = QListWidget()
    for label in ("스크린샷", "영상 편집", "환경 설정"):
        sidebar.addItem(QListWidgetItem(label))
    sidebar.setCurrentRow(1)
    sidebar.setMaximumHeight(110)
    layout.addWidget(sidebar)

    # 버튼 행 — normal / checked / disabled
    btn_row = QHBoxLayout()
    btn_row.setSpacing(6)
    btn_normal = QPushButton("녹화")
    btn_checked = QPushButton("편집")
    btn_checked.setCheckable(True)
    btn_checked.setChecked(True)
    btn_disabled = QPushButton("내보내기")
    btn_disabled.setEnabled(False)
    for b in (btn_normal, btn_checked, btn_disabled):
        btn_row.addWidget(b)
    layout.addLayout(btn_row)

    # 입력
    line = QLineEdit("프로젝트 이름")
    layout.addWidget(line)

    # 타이포그래피 미리보기
    body = QLabel("본문 — 한글 가독성을 확인하는 문장입니다.")
    layout.addWidget(body)
    cap = QLabel("캡션 / 보조 정보 텍스트")
    cap.setProperty("role", "caption")
    layout.addWidget(cap)

    layout.addStretch()
    return card


def main() -> int:
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("KStudio Design 색감 비교 — 마음에 드는 거 골라주세요")
    win.resize(1500, 620)
    win.setStyleSheet("QMainWindow { background: #08080A; } QLabel { color: #888; }")

    central = QWidget()
    layout = QHBoxLayout(central)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(12)
    for name, palette in PALETTES.items():
        layout.addWidget(build_card(name, palette))

    win.setCentralWidget(central)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
