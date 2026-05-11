"""디자인 mockup — 타이포 위계 + 여백 ("고급스러움") 비교.

색은 IMAGE_PALETTE 그대로. 왼쪽=현재 KStudio (조밀·전부 10pt 동일),
오른쪽=다듬은 (6단계 타이포 + 넉넉한 여백 + section header + primary CTA).
색 변화는 0 — 순수하게 *타이포 위계와 공간 운용* 만의 효과를 보기 위함.

실행:
    .venv\\Scripts\\python.exe tools\\design_mockup_typography.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# tools/ 에서 직접 실행해도 import 되도록.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from screen_recorder.ui.tokens import IMAGE_PALETTE


P = IMAGE_PALETTE   # 두 카드 동일 팔레트


# ----- "현재" 카드: 지금 KStudio 가 가진 조밀한 룩 -----
def build_qss_current() -> str:
    return f"""
    QFrame#card {{
        background-color: {P["bg"]};
        border: 1px solid {P["border_strong"]};
        border-radius: 6px;
    }}
    QLabel {{
        color: {P["text"]};
        background: transparent;
        font-size: 10pt;
    }}
    QLineEdit {{
        background: {P["surface_input"]};
        color: {P["text"]};
        border: 1px solid {P["border"]};
        border-radius: 4px;
        padding: 5px 8px;
        min-height: 20px;
        font-size: 10pt;
    }}
    QLineEdit:focus {{ border: 1px solid {P["primary"]}; }}
    QPushButton {{
        background: {P["button_bg"]};
        color: {P["text"]};
        border: 1px solid {P["border_strong"]};
        border-radius: 4px;
        padding: 5px 12px;
        min-height: 22px;
        font-size: 10pt;
    }}
    QPushButton:hover {{
        background: {P["surface_hover"]};
        border: 1px solid {P["primary"]};
    }}
    QListWidget {{
        background: {P["surface"]};
        border: 1px solid {P["border"]};
        border-radius: 4px;
        outline: 0;
        padding: 4px 0;
    }}
    QListWidget::item {{
        padding: 6px 10px;
        color: {P["text_sub"]};
        border-left: 3px solid transparent;
    }}
    QListWidget::item:selected {{
        background: {P["surface_hover"]};
        color: {P["text"]};
        border-left: 3px solid {P["primary"]};
        font-weight: 600;
    }}
    """


# ----- "다듬은" 카드: 타이포 6단계 + 8px 그리드 여백 -----
def build_qss_refined() -> str:
    return f"""
    QFrame#card {{
        background-color: {P["bg"]};
        border: 1px solid {P["border_strong"]};
        border-radius: 10px;
    }}
    QLabel {{
        color: {P["text"]};
        background: transparent;
        font-size: 13px;
    }}
    QLabel[role="display"] {{
        color: {P["text_pure"]};
        font-size: 22px;
        font-weight: 700;
    }}
    QLabel[role="subtitle"] {{
        color: {P["text_sub"]};
        font-size: 13px;
    }}
    QLabel[role="section"] {{
        color: {P["text_dim"]};
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel[role="value"] {{
        color: {P["text"]};
        font-size: 13px;
        font-weight: 500;
    }}
    QLabel[role="caption"] {{
        color: {P["text_dim"]};
        font-size: 11px;
    }}
    QLineEdit {{
        background: {P["surface"]};
        color: {P["text"]};
        border: 1px solid {P["border"]};
        border-radius: 6px;
        padding: 9px 12px;
        min-height: 28px;
        font-size: 13px;
    }}
    QLineEdit:focus {{ border: 1px solid {P["primary"]}; }}
    QPushButton {{
        background: {P["button_bg"]};
        color: {P["text"]};
        border: 1px solid {P["border_strong"]};
        border-radius: 6px;
        padding: 10px 18px;
        min-height: 34px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {P["surface_hover"]};
        border: 1px solid {P["primary"]};
    }}
    QPushButton[role="primary"] {{
        background: {P["primary"]};
        color: {P["text_pure"]};
        border: 1px solid {P["primary"]};
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{
        background: {P["primary_hover"]};
        border: 1px solid {P["primary_hover"]};
    }}
    QListWidget {{
        background: transparent;
        border: none;
        outline: 0;
        padding: 0;
    }}
    QListWidget::item {{
        padding: 10px 14px;
        color: {P["text_sub"]};
        border-radius: 6px;
        margin: 2px 0;
        font-size: 13px;
    }}
    QListWidget::item:hover {{
        background: {P["surface_hover"]};
        color: {P["text"]};
    }}
    QListWidget::item:selected {{
        background: {P["surface_hover"]};
        color: {P["text"]};
        font-weight: 500;
    }}
    """


def _set_role(widget, role: str):
    widget.setProperty("role", role)


def build_card_current() -> QFrame:
    """현재 KStudio 룩 — 모든 텍스트 10pt, 패딩 좁음, section 헤더 없음."""
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(build_qss_current())

    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(8)

    title = QLabel("현재 — 조밀")
    layout.addWidget(title)

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

    layout.addWidget(QLabel("본문 — 한글 가독성을 확인하는 문장입니다."))
    layout.addWidget(QLabel("캡션 / 보조 정보 텍스트"))

    layout.addStretch()
    return card


def build_card_refined() -> QFrame:
    """다듬은 룩 — display/subtitle/section header/body/caption 5단계 + 여백."""
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(build_qss_refined())

    layout = QVBoxLayout(card)
    layout.setContentsMargins(28, 28, 28, 28)
    layout.setSpacing(6)

    # ===== 헤더 영역 =====
    title = QLabel("다듬은 — 위계 + 여백")
    _set_role(title, "display")
    layout.addWidget(title)

    subtitle = QLabel("화면 녹화 · 이미지 편집 · 영상 컷")
    _set_role(subtitle, "subtitle")
    layout.addWidget(subtitle)

    layout.addSpacing(24)

    # ===== 섹션 1 — Recent Files =====
    sec1 = QLabel("RECENT FILES")
    _set_role(sec1, "section")
    layout.addWidget(sec1)
    layout.addSpacing(4)

    recent = QListWidget()
    for fname in (
        "screenshot_2026-05-11.png",
        "demo_clip.mp4",
        "project_a.kstudio",
    ):
        recent.addItem(QListWidgetItem(fname))
    recent.setCurrentRow(1)
    recent.setMaximumHeight(150)
    layout.addWidget(recent)

    layout.addSpacing(20)

    # ===== 섹션 2 — Quick Actions =====
    sec2 = QLabel("QUICK ACTIONS")
    _set_role(sec2, "section")
    layout.addWidget(sec2)
    layout.addSpacing(8)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    btn_primary = QPushButton("녹화 시작")
    _set_role(btn_primary, "primary")
    btn_row.addWidget(btn_primary)
    btn_row.addWidget(QPushButton("편집"))
    btn_row.addWidget(QPushButton("내보내기"))
    layout.addLayout(btn_row)

    layout.addSpacing(20)

    # ===== 섹션 3 — Project Name =====
    sec3 = QLabel("PROJECT NAME")
    _set_role(sec3, "section")
    layout.addWidget(sec3)
    layout.addSpacing(6)
    layout.addWidget(QLineEdit("untitled"))

    layout.addStretch()

    cap = QLabel("마지막 저장 · 방금 전")
    _set_role(cap, "caption")
    layout.addWidget(cap)

    return card


def main() -> int:
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("KStudio Design — 타이포 위계 + 여백 비교 (색감 동일)")
    win.resize(1100, 760)
    win.setStyleSheet("QMainWindow { background: #08080A; }")

    central = QWidget()
    layout = QHBoxLayout(central)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(20)
    layout.addWidget(build_card_current())
    layout.addWidget(build_card_refined())

    win.setCentralWidget(central)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
