"""디자인 mockup — Premiere 스타일 적용 후 비교.

사용자 참고: Adobe Premiere Pro 스크린샷.
핵심 변화 3가지를 동시 적용:
  1) 푸른 기 제거 — 단일 무채색 다크 (#1A1A1A 베이스)
  2) 버튼 평탄화 — 보더/배경 제거, hover 때만 미세
  3) 액센트 절제 — UI 크롬에 색 없음, 셀렉션만 미세
+ 모서리 거의 직각 (2px), 1px 미세 보더, 콘텐츠 영역 강조.

실행:
    .venv\\Scripts\\python.exe tools\\design_mockup_premiere.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)


# ===== 현재 KStudio 톤 (재현용) =====
CURRENT = {
    "bg":            "#1F2125",
    "surface":       "#17191D",
    "surface_hover": "#23262D",
    "border":        "#3C414B",
    "border_strong": "#4A5060",
    "text":          "#E8E8EA",
    "text_sub":      "#A0A4AB",
    "text_dim":      "#6A6E78",
    "primary":       "#4FC3F7",   # 시안 액센트
    "button_bg":     "#3A3F4B",
}


# ===== Premiere 스타일 (스크린샷 분석 기반) =====
# 푸른 기 제거된 무채색 회색만. 액센트 거의 없음 — 셀렉션도 회색 한 톤 차이.
PREMIERE = {
    "bg":            "#1A1A1A",   # 거의 단일 다크
    "surface":       "#232323",
    "surface_hover": "#2D2D2D",
    "border":        "#262626",   # 거의 보이지 않는 보더
    "border_strong": "#383838",   # 패널 분할선
    "text":          "#C8C8C8",   # 순백 아닌 약간 회색
    "text_sub":      "#909090",
    "text_dim":      "#6B6B6B",
    "primary":       "#5A8AC8",   # Premiere 의 선택색 — 차분한 블루, 거의 회색
    "button_bg":     "transparent",   # 버튼 배경 없음
}


def build_qss_current(p: dict) -> str:
    """현재 KStudio 톤 재현 — 버튼·라운드·액센트 모두 있음."""
    return f"""
    QFrame#card {{
        background-color: {p["bg"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 6px;
    }}
    QLabel {{
        color: {p["text"]};
        background: transparent;
        font-size: 10pt;
    }}
    QLineEdit {{
        background: {p["surface"]};
        color: {p["text"]};
        border: 1px solid {p["border"]};
        border-radius: 4px;
        padding: 5px 8px;
        min-height: 20px;
    }}
    QLineEdit:focus {{ border: 1px solid {p["primary"]}; }}
    QPushButton {{
        background: {p["button_bg"]};
        color: {p["text"]};
        border: 1px solid {p["border"]};
        border-radius: 4px;
        padding: 5px 12px;
        min-height: 22px;
    }}
    QPushButton:hover {{
        background: {p["surface_hover"]};
        border: 1px solid {p["primary"]};
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
    QListWidget::item:selected {{
        background: {p["surface_hover"]};
        color: {p["text"]};
        border-left: 3px solid {p["primary"]};
        font-weight: 600;
    }}
    """


def build_qss_premiere(p: dict) -> str:
    """Premiere 톤 — 무채색·직각 유지. 버튼은 살짝 보이게 (border + 미세 bg)."""
    return f"""
    QFrame#card {{
        background-color: {p["bg"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 2px;
    }}
    QLabel {{
        color: {p["text"]};
        background: transparent;
        font-size: 10pt;
    }}
    QLabel[role="section"] {{
        color: {p["text_dim"]};
        font-size: 10pt;
        padding: 4px 8px;
        background: {p["surface"]};
        border-bottom: 1px solid {p["border_strong"]};
    }}
    QLabel[role="caption"] {{
        color: {p["text_dim"]};
        font-size: 9pt;
    }}
    QLineEdit {{
        background: {p["bg"]};
        color: {p["text"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 2px;
        padding: 4px 8px;
        min-height: 20px;
    }}
    QLineEdit:focus {{ border: 1px solid {p["primary"]}; }}
    /* 기본 버튼 — surface 와 같은 미세 fill + border_strong 1px 보더로 살짝 보이게. */
    QPushButton {{
        background: {p["surface"]};
        color: {p["text"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 2px;
        padding: 6px 14px;
        min-height: 26px;
    }}
    QPushButton:hover {{
        background: {p["surface_hover"]};
        border: 1px solid {p["text_dim"]};
    }}
    QPushButton:pressed {{
        background: {p["bg"]};
    }}
    /* primary CTA — 강조해야 할 단 하나의 액션. 채워진 차분 블루. */
    QPushButton[role="primary"] {{
        background: {p["primary"]};
        color: #FFFFFF;
        border: 1px solid {p["primary"]};
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{
        background: #6BA0E0;
        border: 1px solid #6BA0E0;
    }}
    /* 사이드바 — 보더 없음, 액센트 바 없음, 셀렉션은 한 톤 진하게만 */
    QListWidget {{
        background: {p["surface"]};
        border: none;
        outline: 0;
        padding: 2px 0;
    }}
    QListWidget::item {{
        padding: 5px 12px;
        color: {p["text_sub"]};
    }}
    QListWidget::item:hover {{
        background: {p["surface_hover"]};
        color: {p["text"]};
    }}
    QListWidget::item:selected {{
        background: {p["surface_hover"]};
        color: {p["text"]};
    }}
    """


def build_card_current() -> QFrame:
    """현재 KStudio 룩 재현."""
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(build_qss_current(CURRENT))

    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(8)

    layout.addWidget(QLabel("현재 KStudio"))

    sidebar = QListWidget()
    for label in ("스크린샷", "영상 편집", "환경 설정"):
        sidebar.addItem(QListWidgetItem(label))
    sidebar.setCurrentRow(1)
    sidebar.setMaximumHeight(96)
    layout.addWidget(sidebar)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(6)
    for label in ("녹화", "편집", "내보내기"):
        btn_row.addWidget(QPushButton(label))
    layout.addLayout(btn_row)

    layout.addWidget(QLabel("Project Name"))
    layout.addWidget(QLineEdit("untitled"))

    layout.addStretch()

    cap = QLabel("• 버튼이 명확한 '버튼' 으로 보임\n• 시안 액센트 곳곳에\n• 4px 라운드, 보더 명확")
    layout.addWidget(cap)
    return card


def build_card_premiere() -> QFrame:
    """Premiere 톤 적용."""
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(build_qss_premiere(PREMIERE))

    layout = QVBoxLayout(card)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    # 섹션 헤더 — Premiere 스타일 (작은 회색 띠)
    sec_top = QLabel("  PROJECT  ")
    sec_top.setProperty("role", "section")
    layout.addWidget(sec_top)

    # 본문 영역
    body = QWidget()
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(0, 8, 0, 8)
    body_lay.setSpacing(0)

    sidebar = QListWidget()
    for label in ("스크린샷", "영상 편집", "환경 설정"):
        sidebar.addItem(QListWidgetItem(label))
    sidebar.setCurrentRow(1)
    sidebar.setMaximumHeight(100)
    body_lay.addWidget(sidebar)

    layout.addWidget(body)

    # ACTIONS 섹션 헤더
    sec_act = QLabel("  ACTIONS  ")
    sec_act.setProperty("role", "section")
    layout.addWidget(sec_act)

    # 액션 영역 — primary 1개 + 보조 버튼들
    act = QWidget()
    act_lay = QVBoxLayout(act)
    act_lay.setContentsMargins(8, 8, 8, 8)
    act_lay.setSpacing(6)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(6)
    btn_primary = QPushButton("녹화 시작")
    btn_primary.setProperty("role", "primary")
    btn_row.addWidget(btn_primary)
    btn_row.addWidget(QPushButton("편집"))
    btn_row.addWidget(QPushButton("내보내기"))
    act_lay.addLayout(btn_row)

    layout.addWidget(act)

    # PROPERTIES 섹션
    sec_props = QLabel("  PROPERTIES  ")
    sec_props.setProperty("role", "section")
    layout.addWidget(sec_props)

    props = QWidget()
    props_lay = QVBoxLayout(props)
    props_lay.setContentsMargins(8, 8, 8, 8)
    props_lay.setSpacing(6)

    name_row = QHBoxLayout()
    name_row.addWidget(QLabel("Project Name"))
    name_row.addStretch()
    name_row.addWidget(QLineEdit("untitled"))
    props_lay.addLayout(name_row)

    layout.addWidget(props)
    layout.addStretch()

    # 캡션
    cap_wrap = QWidget()
    cap_lay = QVBoxLayout(cap_wrap)
    cap_lay.setContentsMargins(8, 8, 8, 8)
    cap = QLabel("• 버튼: 미세 fill + 1px 보더로 살짝 보이게\n• 강조할 액션 1개 만 채운 primary 버튼\n• 액센트 색 절제, 직각, 푸른 기 0")
    cap.setProperty("role", "caption")
    cap_lay.addWidget(cap)
    layout.addWidget(cap_wrap)

    return card


def main() -> int:
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("KStudio Design — Premiere 스타일 비교")
    win.resize(1100, 720)
    win.setStyleSheet("QMainWindow { background: #0A0A0A; }")

    central = QWidget()
    layout = QHBoxLayout(central)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(20)
    layout.addWidget(build_card_current())
    layout.addWidget(build_card_premiere())

    win.setCentralWidget(central)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
