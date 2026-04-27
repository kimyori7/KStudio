"""앱 전체에 적용되는 다크 테마 QSS."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication


_QSS = """
/* ----- 기본 ----- */
QMainWindow, QWidget {
    background-color: #1F2125;
    color: #E8E8EA;
    font-family: "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    font-size: 10pt;
}

QMessageBox {
    background-color: #252830;
}

/* ----- 사이드바 (QListWidget) ----- */
QListWidget {
    background-color: #17191D;
    border: none;
    outline: 0;
    padding: 6px 0;
}
QListWidget::item {
    padding: 10px 14px;
    border-left: 3px solid transparent;
    color: #A0A4AB;
    margin: 1px 0;
}
QListWidget::item:hover {
    background-color: #23262D;
    color: #E8E8EA;
}
QListWidget::item:selected {
    background-color: #23262D;
    color: #FFFFFF;
    border-left: 3px solid #4FC3F7;
    font-weight: 600;
}

/* ----- 패널 영역 ----- */
QStackedWidget > QWidget {
    background-color: #1F2125;
}

/* ----- 입력 위젯 ----- */
QLineEdit, QSpinBox, QComboBox, QKeySequenceEdit {
    background-color: #2A2E36;
    border: 1px solid #3C414B;
    border-radius: 4px;
    padding: 5px 8px;
    color: #E8E8EA;
    selection-background-color: #4FC3F7;
    selection-color: #1F2125;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {
    border: 1px solid #4FC3F7;
}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QKeySequenceEdit:disabled {
    color: #6A6E78;
    background-color: #23252B;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #A0A4AB;
}
QComboBox QAbstractItemView {
    background-color: #2A2E36;
    color: #E8E8EA;
    selection-background-color: #2D5DA8;
    border: 1px solid #3C414B;
    outline: 0;
}
QSpinBox::up-button, QSpinBox::down-button { width: 16px; }

/* ----- 버튼 ----- */
QPushButton {
    background-color: #3A3F4B;
    border: 1px solid #4A4F5B;
    border-radius: 4px;
    padding: 6px 14px;
    color: #E8E8EA;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #4A4F5B;
    border: 1px solid #5A5F6B;
}
QPushButton:pressed {
    background-color: #2A2D34;
}
QPushButton:disabled {
    background-color: #23252B;
    color: #6A6E78;
    border: 1px solid #2D3037;
}

/* ----- 라디오 / 체크박스 ----- */
QRadioButton, QCheckBox {
    color: #E8E8EA;
    spacing: 8px;
}
QRadioButton:disabled, QCheckBox:disabled {
    color: #6A6E78;
}

QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 9px;
    border: 2px solid #6A6E78;
    background-color: #2A2E36;
}
QRadioButton::indicator:hover {
    border: 2px solid #A0A4AB;
}
QRadioButton::indicator:checked {
    border: 2px solid #4FC3F7;
    background-color: #4FC3F7;
}
QRadioButton::indicator:disabled {
    border: 2px solid #3C414B;
    background-color: #23252B;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid #6A6E78;
    background-color: #2A2E36;
}
QCheckBox::indicator:hover {
    border: 1px solid #A0A4AB;
}
QCheckBox::indicator:checked {
    border: 1px solid #4FC3F7;
    background-color: #4FC3F7;
}
QCheckBox::indicator:disabled {
    border: 1px solid #3C414B;
    background-color: #23252B;
}

/* ----- 라벨 ----- */
QLabel {
    color: #E8E8EA;
    background: transparent;
}

/* ----- 슬라이더 ----- */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background: #3C414B;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #4FC3F7;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #FFFFFF;
    border: 2px solid #4FC3F7;
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}

/* ----- 테이블 ----- */
QTableWidget {
    background-color: #17191D;
    alternate-background-color: #1B1E23;
    gridline-color: #2A2D34;
    selection-background-color: #2D5DA8;
    selection-color: #FFFFFF;
    border: 1px solid #2A2D34;
    border-radius: 4px;
}
QTableWidget::item {
    padding: 4px 6px;
}
QHeaderView::section {
    background-color: #23262D;
    color: #C8CCD3;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #2A2D34;
    border-bottom: 1px solid #2A2D34;
    font-weight: bold;
}

/* ----- 스크롤바 ----- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3C414B;
    min-height: 24px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #4A4F5B;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #3C414B;
    min-width: 24px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: #4A4F5B;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ----- 툴팁 ----- */
QToolTip {
    background-color: #2A2E36;
    color: #E8E8EA;
    border: 1px solid #3C414B;
    padding: 4px 6px;
    border-radius: 3px;
}

/* ----- 툴바 / 툴버튼 (저장/도구/Undo 등) ----- */
QToolBar {
    background-color: #1F2125;
    border: none;
    spacing: 2px;
    padding: 2px;
}
QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 4px 8px;
    color: #E8E8EA;
}
QToolButton:hover {
    background-color: #3A3F4B;
    border: 1px solid #5A5F6B;
}
QToolButton:pressed {
    background-color: #2A2D34;
}
QToolButton:checked {
    background-color: #2D5DA8;
    border: 1px solid #4FC3F7;
    color: #FFFFFF;
    font-weight: bold;
}
QToolBar::separator {
    background-color: #3C414B;
    width: 1px;
    margin: 4px 4px;
}

/* ----- 메뉴 (트레이/우클릭) ----- */
QMenu {
    background-color: #23262D;
    border: 1px solid #3C414B;
    color: #E8E8EA;
    padding: 4px 0;
}
QMenu::item {
    padding: 6px 18px;
}
QMenu::item:selected {
    background-color: #2D5DA8;
}
QMenu::separator {
    height: 1px;
    background-color: #3C414B;
    margin: 4px 6px;
}
"""


def apply_theme(app: QApplication) -> None:
    """QApplication 인스턴스에 다크 테마 적용."""
    app.setStyleSheet(_QSS)
