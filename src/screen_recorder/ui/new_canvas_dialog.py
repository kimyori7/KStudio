"""'새로 만들기' 다이얼로그 — 폭/높이 + 배경(흰색/투명) 입력 후 빈 EditTab 생성.

클립보드에 이미지가 있으면 그 크기를 자동 입력 후보로 표시.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)


_DEFAULT_W = 1920
_DEFAULT_H = 1080
_MIN = 8
_MAX = 16384


class NewCanvasDialog(QDialog):
    """새 빈 캔버스 사이즈 입력 다이얼로그.

    accept() 가 호출되면 self.size() 로 결과 사이즈 조회.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("새 이미지")
        self.setModal(True)

        layout = QVBoxLayout(self)

        # 클립보드 이미지 사이즈 감지 (없으면 기본값)
        cb_size = self._clipboard_image_size()
        init_w = cb_size.width() if cb_size.isValid() else _DEFAULT_W
        init_h = cb_size.height() if cb_size.isValid() else _DEFAULT_H

        # 클립보드 안내 라벨
        if cb_size.isValid():
            note = QLabel(f"📋 클립보드 이미지: {cb_size.width()} × {cb_size.height()} px")
        else:
            note = QLabel("📋 클립보드에 이미지 없음 — 기본 크기로 시작")
        note.setStyleSheet("color: #A0A4AB; padding: 4px 0;")
        layout.addWidget(note)

        # 폭/높이 폼
        form = QFormLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(_MIN, _MAX)
        self.width_spin.setValue(init_w)
        self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(_MIN, _MAX)
        self.height_spin.setValue(init_h)
        self.height_spin.setSuffix(" px")
        form.addRow("가로:", self.width_spin)
        form.addRow("세로:", self.height_spin)
        layout.addLayout(form)

        # 클립보드 사이즈 다시 적용 버튼 (옵션)
        if cb_size.isValid():
            btn_row = QHBoxLayout()
            btn_apply_cb = QPushButton("클립보드 크기 적용")
            btn_apply_cb.clicked.connect(
                lambda: (self.width_spin.setValue(cb_size.width()),
                         self.height_spin.setValue(cb_size.height()))
            )
            btn_row.addStretch(1)
            btn_row.addWidget(btn_apply_cb)
            layout.addLayout(btn_row)

        # 배경 — 투명(기본) / 흰색
        bg_row = QHBoxLayout()
        bg_label = QLabel("배경:")
        bg_label.setFixedWidth(40)
        self._bg_transparent = QRadioButton("투명")
        self._bg_transparent.setToolTip(
            "투명 배경 — PNG 알파를 보존. 누끼/지우개로 비운 영역이 그대로 투명."
        )
        self._bg_white = QRadioButton("흰색")
        self._bg_white.setToolTip(
            "흰 배경 — JPG 등 알파 미지원 포맷이나 종이 위에 그리는 작업에 적합."
        )
        self._bg_transparent.setChecked(True)
        self._bg_group = QButtonGroup(self)
        self._bg_group.addButton(self._bg_transparent)
        self._bg_group.addButton(self._bg_white)
        bg_row.addWidget(bg_label)
        bg_row.addWidget(self._bg_transparent)
        bg_row.addWidget(self._bg_white)
        bg_row.addStretch(1)
        layout.addLayout(bg_row)

        # OK/Cancel
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("만들기")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def size(self) -> QSize:
        return QSize(self.width_spin.value(), self.height_spin.value())

    def fill_white(self) -> bool:
        """선택된 배경이 흰색이면 True, 투명이면 False."""
        return self._bg_white.isChecked()

    @staticmethod
    def _clipboard_image_size() -> QSize:
        cb = QGuiApplication.clipboard()
        if cb is None:
            return QSize()
        img = cb.image()
        if img is None or img.isNull():
            return QSize()
        return img.size()
