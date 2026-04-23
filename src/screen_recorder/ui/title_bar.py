"""커스텀 타이틀바 — frameless 메인 윈도우용.

- 좌측: 앱 아이콘 + 제목
- 우측: 최소화 / 닫기 버튼
- 타이틀바 영역 드래그로 창 이동
- 더블클릭으로 최대화/복원 토글
"""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

from .app_icon import app_icon


_TITLEBAR_QSS = """
#CustomTitleBar {
    background-color: #17191D;
    border-bottom: 1px solid #2A2D34;
}
#TitleLabel {
    color: #E8E8EA;
    font-weight: 600;
    font-size: 10pt;
    padding-left: 8px;
}
QPushButton#TitleBtn {
    background-color: transparent;
    color: #C8CCD3;
    border: none;
    font-size: 11pt;
    padding: 0;
}
QPushButton#TitleBtn:hover {
    background-color: #2A2D34;
    color: #FFFFFF;
}
QPushButton#TitleBtn:pressed {
    background-color: #1A1C20;
}
QPushButton#TitleBtnClose {
    background-color: transparent;
    color: #C8CCD3;
    border: none;
    font-size: 11pt;
    padding: 0;
}
QPushButton#TitleBtnClose:hover {
    background-color: #E53935;
    color: #FFFFFF;
}
QPushButton#TitleBtnClose:pressed {
    background-color: #B71C1C;
}
"""


class CustomTitleBar(QWidget):
    minimize_clicked = Signal()
    close_clicked = Signal()

    HEIGHT = 32

    def __init__(self, title: str = "Screen Recorder"):
        super().__init__()
        self.setObjectName("CustomTitleBar")
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet(_TITLEBAR_QSS)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(0)

        # 아이콘
        icon_label = QLabel()
        pix = app_icon().pixmap(20, 20)
        if not pix.isNull():
            icon_label.setPixmap(pix)
        layout.addWidget(icon_label)

        # 제목
        self.title_label = QLabel(title)
        self.title_label.setObjectName("TitleLabel")
        layout.addWidget(self.title_label)

        layout.addStretch(1)

        # 최소화 버튼
        self.min_btn = QPushButton("─")
        self.min_btn.setObjectName("TitleBtn")
        self.min_btn.setFixedSize(46, self.HEIGHT)
        self.min_btn.setFocusPolicy(Qt.NoFocus)
        self.min_btn.clicked.connect(self.minimize_clicked.emit)
        layout.addWidget(self.min_btn)

        # 닫기 버튼
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("TitleBtnClose")
        self.close_btn.setFixedSize(46, self.HEIGHT)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.close_btn)

        self._drag_origin = None
        self._window_origin = None

    # ---------- 드래그로 창 이동 ----------

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_origin = e.globalPosition().toPoint()
            self._window_origin = self.window().pos()

    def mouseMoveEvent(self, e):
        if self._drag_origin is not None:
            delta = e.globalPosition().toPoint() - self._drag_origin
            self.window().move(self._window_origin + delta)

    def mouseReleaseEvent(self, _e):
        self._drag_origin = None
        self._window_origin = None

    def mouseDoubleClickEvent(self, _e):
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()
