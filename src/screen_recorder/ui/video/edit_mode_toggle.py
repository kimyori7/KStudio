"""편집 모드 ON/OFF 토글 버튼 — 컨트롤바 우측에 배치."""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QPushButton

from ..icons import load_icon
from ...core.i18n import tr


_ICON_PX = 18


class EditModeToggle(QPushButton):
    """편집 모드 토글 — checkable QPushButton.

    외부에서 set_on(True/False) 또는 사용자가 클릭할 때 toggled_changed 발생.
    set_on 이 현재 상태와 같으면 시그널 발화 없음 (idempotent).
    """

    toggled_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setIcon(load_icon("edit-3", size=_ICON_PX))
        self.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.setText(tr("편집"))
        self.setToolTip(tr("편집 모드 켜기/끄기 (Ctrl+E)"))
        self.setFixedHeight(32)
        self.toggled.connect(self._on_qt_toggled)

    def is_on(self) -> bool:
        return self.isChecked()

    def set_on(self, on: bool) -> None:
        if self.isChecked() == on:
            return
        self.setChecked(on)
        # setChecked 가 toggled 시그널 발생시키므로 _on_qt_toggled 가 호출됨

    def _on_qt_toggled(self, on: bool) -> None:
        self.toggled_changed.emit(on)
