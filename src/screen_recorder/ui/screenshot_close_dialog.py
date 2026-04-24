"""저장 안 된 탭이 있을 때 표시되는 3버튼 닫기 다이얼로그."""
from __future__ import annotations
from enum import Enum

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout


class CloseAction(Enum):
    CLOSE_ALL = "all"
    CLOSE_CURRENT = "current"
    CANCEL = "cancel"


class CloseDialog(QDialog):
    def __init__(self, unsaved_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("저장되지 않은 스크린샷")
        self.setModal(True)

        self._action = CloseAction.CANCEL

        root = QVBoxLayout(self)

        msg = QLabel(
            f"저장되지 않은 스크린샷이 {unsaved_count}개 있습니다.\n"
            "어떻게 할까요?\n\n"
            "(저장하려면 '취소' 후 Ctrl+S 를 눌러주세요.)"
        )
        msg.setWordWrap(True)
        root.addWidget(msg)

        row = QHBoxLayout()
        row.addStretch(1)

        self.btn_all = QPushButton("전체 닫기")
        self.btn_all.clicked.connect(lambda: self._choose(CloseAction.CLOSE_ALL))
        row.addWidget(self.btn_all)

        self.btn_current = QPushButton("현재 탭만 닫기")
        self.btn_current.clicked.connect(lambda: self._choose(CloseAction.CLOSE_CURRENT))
        row.addWidget(self.btn_current)

        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setDefault(True)
        self.btn_cancel.clicked.connect(lambda: self._choose(CloseAction.CANCEL))
        row.addWidget(self.btn_cancel)

        root.addLayout(row)

    def _choose(self, action: CloseAction) -> None:
        self._action = action
        if action == CloseAction.CANCEL:
            self.reject()
        else:
            self.accept()

    def action(self) -> CloseAction:
        return self._action
