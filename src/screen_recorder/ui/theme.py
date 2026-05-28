"""앱 전체에 적용되는 다크 테마 QSS — 모드별 팔레트.

tokens.PALETTES 에서 "video" / "image" 팔레트를 골라 f-string 으로 QSS 빌드.
폰트는 시스템 폰트(Segoe UI / 맑은 고딕 / Apple SD Gothic Neo) 유지 — 추가 폰트 번들 없음.

mode_controller 의 mode_changed 시그널에 main_window 가 연결돼 있으며,
모드 전환 시 apply_theme(app, "video"|"image") 가 재호출된다.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from screen_recorder.ui.tokens import PALETTES, VIDEO_PALETTE


def build_qss(p: dict[str, str]) -> str:
    """팔레트 dict 에서 전체 QSS 문자열 생성."""
    return f"""
/* ----- 기본 ----- */
QMainWindow, QWidget {{
    background-color: {p["bg"]};
    color: {p["text"]};
    font-family: "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    font-size: 10pt;
}}

QMessageBox {{
    background-color: {p["surface_msg"]};
}}

/* ----- 사이드바 (QListWidget) ----- */
QListWidget {{
    background-color: {p["surface"]};
    border: none;
    outline: 0;
    padding: 6px 0;
}}
QListWidget::item {{
    padding: 10px 14px;
    border-left: 3px solid transparent;
    color: {p["text_sub"]};
    margin: 1px 0;
}}
QListWidget::item:hover {{
    background-color: {p["surface_hover"]};
    color: {p["text"]};
}}
QListWidget::item:selected {{
    background-color: {p["surface_hover"]};
    color: {p["text_pure"]};
    border-left: 3px solid {p["primary"]};
    font-weight: 600;
}}

/* ----- 패널 영역 ----- */
QStackedWidget > QWidget {{
    background-color: {p["bg"]};
}}

/* ----- Dock 위젯 ----- */
QDockWidget {{
    color: {p["text"]};
    font-weight: 600;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    /* 메인보다 진하게 — 패널 영역과 시각적으로 분리 */
    background-color: {p["surface_dock"]};
    padding: 6px 10px;
    border-bottom: 1px solid {p["border"]};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    text-align: left;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background-color: {p["border"]};
    border: 1px solid {p["border_strong"]};
    border-radius: 5px;
    padding: 2px;
    icon-size: 12px;
}}
QDockWidget::close-button:hover {{
    background-color: {p["danger"]};
    border: 1px solid {p["danger_hover"]};
}}
QDockWidget::float-button:hover {{
    background-color: {p["primary"]};
    border: 1px solid {p["primary_hover"]};
}}

/* ----- 입력 위젯 ----- */
QLineEdit, QSpinBox, QComboBox, QKeySequenceEdit {{
    background-color: {p["surface_input"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 5px 8px;
    color: {p["text"]};
    selection-background-color: {p["primary"]};
    selection-color: {p["bg"]};
    min-height: 20px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{
    border: 1px solid {p["primary"]};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QKeySequenceEdit:disabled {{
    color: {p["text_dim"]};
    background-color: {p["disabled_bg"]};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p["text_sub"]};
}}
QComboBox QAbstractItemView {{
    background-color: {p["surface_input"]};
    color: {p["text"]};
    selection-background-color: {p["selection_bg"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 2px;
    outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}

/* ----- 버튼 ----- */
QPushButton {{
    background-color: {p["button_bg"]};
    border: 1px solid {p["button_hover_bg"]};
    border-radius: 6px;
    padding: 6px 14px;
    color: {p["text"]};
    min-height: 22px;
    /* text-align: center 는 QPushButton 의 기본값이지만, 명시해 두면
       플랫폼별 차이 (특히 이모지 폰트 metric 비대칭) 가 두드러질 때 안전망 역할. */
    text-align: center;
}}
QPushButton:hover {{
    background-color: {p["button_hover_bg"]};
    border: 1px solid {p["button_hover_border"]};
}}
QPushButton:pressed {{
    background-color: {p["button_pressed_bg"]};
}}
QPushButton:checked {{
    background-color: {p["selection_bg"]};
    border: 1px solid {p["primary"]};
    color: {p["text_pure"]};
    font-weight: bold;
}}
QPushButton:disabled {{
    background-color: {p["disabled_bg"]};
    color: {p["text_dim"]};
    border: 1px solid {p["disabled_border"]};
}}

/* ----- 라디오 / 체크박스 ----- */
QRadioButton, QCheckBox {{
    color: {p["text"]};
    spacing: 8px;
}}
QRadioButton:disabled, QCheckBox:disabled {{
    color: {p["text_dim"]};
}}

QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 9px;
    border: 2px solid {p["text_dim"]};
    background-color: {p["surface_input"]};
}}
QRadioButton::indicator:hover {{
    border: 2px solid {p["text_sub"]};
}}
QRadioButton::indicator:checked {{
    border: 2px solid {p["primary"]};
    background-color: {p["primary"]};
}}
QRadioButton::indicator:disabled {{
    border: 2px solid {p["border"]};
    background-color: {p["disabled_bg"]};
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {p["text_dim"]};
    background-color: {p["surface_input"]};
}}
QCheckBox::indicator:hover {{
    border: 1px solid {p["text_sub"]};
}}
QCheckBox::indicator:checked {{
    border: 1px solid {p["primary"]};
    background-color: {p["primary"]};
}}
QCheckBox::indicator:disabled {{
    border: 1px solid {p["border"]};
    background-color: {p["disabled_bg"]};
}}

/* ----- 라벨 ----- */
QLabel {{
    color: {p["text"]};
    background: transparent;
}}

/* ----- 슬라이더 ----- */
QSlider::groove:horizontal {{
    border: none;
    height: 4px;
    background: {p["border"]};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {p["primary"]};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {p["text_pure"]};
    border: 2px solid {p["primary"]};
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}}

/* ----- 테이블 ----- */
QTableWidget {{
    background-color: {p["surface"]};
    alternate-background-color: {p["bg_table_alt"]};
    gridline-color: {p["border_dim"]};
    selection-background-color: {p["selection_bg"]};
    selection-color: {p["text_pure"]};
    border: 1px solid {p["border_dim"]};
    border-radius: 6px;
}}
QTableWidget::item {{
    padding: 4px 6px;
}}
QHeaderView::section {{
    background-color: {p["surface_hover"]};
    color: {p["text_header"]};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {p["border_dim"]};
    border-bottom: 1px solid {p["border_dim"]};
    font-weight: bold;
}}

/* ----- 스크롤바 ----- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p["border"]};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p["button_hover_bg"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p["border"]};
    min-width: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p["button_hover_bg"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ----- 툴팁 ----- */
QToolTip {{
    background-color: {p["surface_input"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    padding: 5px 8px;
    border-radius: 6px;
}}

/* ----- 툴바 / 툴버튼 ----- */
QToolBar {{
    background-color: {p["bg"]};
    border: none;
    spacing: 2px;
    padding: 2px;
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 8px;
    color: {p["text"]};
}}
QToolButton:hover {{
    background-color: {p["button_bg"]};
    border: 1px solid {p["button_hover_border"]};
}}
QToolButton:pressed {{
    background-color: {p["button_pressed_bg"]};
}}
QToolButton:checked {{
    background-color: {p["selection_bg"]};
    border: 1px solid {p["primary"]};
    color: {p["text_pure"]};
    font-weight: bold;
}}
QToolBar::separator {{
    background-color: {p["border_strong"]};
    width: 2px;
    margin: 6px 6px;
    border-radius: 1px;
}}

/* ----- 메뉴 바 ----- */
QMenuBar {{
    background-color: {p["bg"]};
    color: {p["text"]};
    padding: 2px 4px;
    border-bottom: 1px solid {p["border_dim"]};
}}
QMenuBar::item {{
    background-color: transparent;
    padding: 4px 10px;
    color: {p["text"]};
    border-radius: 5px;
}}
QMenuBar::item:selected {{
    background-color: {p["selection_bg"]};
    color: {p["text_pure"]};
}}
QMenuBar::item:pressed {{
    background-color: {p["selection_pressed"]};
}}

/* ----- 메뉴 ----- */
QMenu {{
    background-color: {p["surface_hover"]};
    border: 1px solid {p["border"]};
    border-radius: 8px;
    color: {p["text"]};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 4px;
    margin: 1px 2px;
}}
QMenu::item:selected {{
    background-color: {p["selection_bg"]};
}}
QMenu::separator {{
    height: 1px;
    background-color: {p["border"]};
    margin: 4px 6px;
}}

/* ----- 탭 위젯 ----- */
QTabWidget::pane {{
    border: 1px solid {p["border_dim"]};
    border-top-left-radius: 0;
    border-top-right-radius: 0;
    background: {p["bg"]};
}}
QTabBar::tab {{
    background: {p["surface"]};
    color: {p["text_sub"]};
    padding: 6px 14px;
    border: 1px solid {p["border_dim"]};
    border-bottom: none;
    /* 윗 모서리만 둥글게 — 아랫쪽은 pane 과 매끄럽게 이어지도록 직각 유지. */
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
    min-width: 60px;
}}
QTabBar::tab:selected {{
    background: {p["bg"]};
    color: {p["text_pure"]};
    border-bottom: 2px solid {p["primary"]};
}}
QTabBar::tab:hover {{
    background: {p["surface_hover"]};
    color: {p["text"]};
}}
QTabBar::tab:!selected {{
    /* 비선택 탭은 살짝 아래로 — 선택 탭이 살짝 솟은 듯한 입체감. */
    margin-top: 2px;
}}
QTabBar::close-button {{
    subcontrol-position: right;
    border-radius: 4px;
    padding: 2px;
}}
QTabBar::close-button:hover {{
    background: {p["surface_hover"]};
}}

/* ----- 스플리터 핸들 ----- */
QSplitter::handle {{
    background: {p["border_dim"]};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}
"""


def apply_theme(app: QApplication, palette_name: str = "video") -> None:
    """QApplication 에 모드별 테마 적용.

    palette_name 미지정 시 영상 모드(시안) 로 폴백 — 모드 시스템이 없는 컨텍스트
    (예: 일부 다이얼로그 단독 테스트) 에서도 안전한 기본값.
    """
    palette = PALETTES.get(palette_name, VIDEO_PALETTE)
    app.setStyleSheet(build_qss(palette))
