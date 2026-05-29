"""공용 위젯 — 글로벌 툴바와 환경설정 다이얼로그가 공유."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QKeySequenceEdit, QLabel, QPushButton, QWidget,
)


class OneShotKeySequenceEdit(QKeySequenceEdit):
    """한 번 입력 후 자동으로 capture 를 끝내는 QKeySequenceEdit.

    기본 QKeySequenceEdit 는 setMaximumSequenceLength(1) 이어도 입력 후 포커스가
    유지돼, 사용자가 다음 키를 누르면 또다시 새 시퀀스가 잡혀 "여러번 먹는"
    것처럼 느껴진다. 이 서브클래스는 editingFinished 시 즉시 clearFocus() 를
    호출해 capture 를 닫고, 포커스 상태를 시각적으로 표시한다.

    또한 editing_started / editing_finished 시그널을 발화해 외부 (main_window) 가
    글로벌 핫키(Win32 RegisterHotKey) 를 일시 해제할 수 있게 한다 — 그러지 않으면
    Ctrl+Shift+T 같은 기존 등록 단축키를 재지정할 때 기존 액션이 가로채 capture 가
    안 된다.
    """

    editing_started = Signal()
    editing_finished_signal = Signal()  # editingFinished 와 이름 충돌 방지

    _STYLE_IDLE = (
        "QLineEdit { border: 1px solid #555; padding: 2px 4px; }"
    )
    _STYLE_CAPTURE = (
        "QLineEdit { border: 2px solid #E53935; background: #2A1E1E; "
        "color: #FFCDD2; padding: 1px 3px; }"
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumSequenceLength(1)
        self.setStyleSheet(self._STYLE_IDLE)
        # editing_started 를 냈으면 반드시 editing_finished_signal 로 짝을 맞춘다 —
        # main_window 가 전역 핫키를 unregister(started)→register(finished) 하므로,
        # finished 가 누락되면 핫키가 영구 해제로 남는다 (사용자 보고 2026-05-29:
        # 편집기에 포커스 준 뒤 모드 전환으로 숨겨져 focusOut 누락 → Ctrl+Shift+R 사망).
        self._capturing = False
        # 한 번 입력되면 자동 종료 — clearFocus 하면 focusOutEvent 가 발화해 스타일 복귀.
        self.editingFinished.connect(self.clearFocus)

    def _end_capture(self) -> None:
        """capture 종료를 한 번만 발화 (idempotent) — focusOut/hide 어느 쪽이 먼저 와도 안전."""
        if not self._capturing:
            return
        self._capturing = False
        self.setStyleSheet(self._STYLE_IDLE)
        self.setToolTip("")
        self.editing_finished_signal.emit()

    def focusInEvent(self, e) -> None:  # type: ignore[override]
        super().focusInEvent(e)
        self.setStyleSheet(self._STYLE_CAPTURE)
        self.setToolTip("🔴 지정 중입니다 — 단축키 한 번만 누르세요.")
        if not self._capturing:
            self._capturing = True
            self.editing_started.emit()

    def focusOutEvent(self, e) -> None:  # type: ignore[override]
        super().focusOutEvent(e)
        self._end_capture()

    def hideEvent(self, e) -> None:  # type: ignore[override]
        # 포커스를 가진 채 숨겨지면 (모드 전환·툴바 재구성 등) focusOutEvent 가 안 올 수
        # 있어 editing_finished_signal 이 누락된다 → 전역 핫키 영구 해제 회귀. 숨김 시에도
        # capture 종료를 보장해 짝을 맞춘다.
        super().hideEvent(e)
        self._end_capture()


class CenteredIconButton(QPushButton):
    """icon+text 를 진짜 가운데 정렬해서 표시하는 QPushButton.

    **왜 필요한가** — Qt 의 QPushButton 은 icon 을 좌측 padding 직후에 고정 배치하고
    그 다음에 text 를 놓는다. `text-align: center` QSS 를 줘도 *text 만* 가운데로
    가고 icon 은 좌측에 그대로 남아서, 버튼 폭이 컨텐츠보다 넓을 때 오른쪽에 빈
    공간이 생긴다 (사용자가 "왼쪽 치우쳐 보임" 으로 느낌).

    이 위젯은 setIcon/setText 를 쓰지 않고 내부에 QHBoxLayout 을 깔아 양옆 stretch
    로 icon+text 를 묶어 진짜 가운데 정렬한다. 단, QPushButton 의 sizeHint 는 기본적
    으로 setLayout 한 자식 layout 을 무시하므로 (setText/setIcon 만 봄), sizeHint /
    minimumSizeHint 를 layout 기준으로 override 해야 폭이 컨텐츠에 맞게 잡힌다.

    외관은 글로벌 QSS 의 QPushButton 규칙을 그대로 받아 일관성 유지.
    """

    def __init__(
        self,
        icon: Optional[QIcon] = None,
        text: str = "",
        *,
        icon_px: int = 14,
        spacing: int = 6,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        # layout margins (14, 4, 14, 4) — QPushButton 의 일반 padding 과 동등한 시각.
        # 검증 (scripts/diagnose_autoedit_button.py 변형 H): QSS padding 과 layout
        # margins 가 *이중으로 빠지지 않음* — Qt 가 setLayout 된 QPushButton 의 QSS
        # padding 을 layout 영역 안으로 흡수하는 것으로 보임. margins=0 으로 두면
        # 컨텐츠가 border 에 닿아 cramped (사용자 보고 2026-05-28).
        lay.setContentsMargins(14, 4, 14, 4)
        lay.setSpacing(spacing)
        lay.addStretch(1)
        if icon is not None and not icon.isNull():
            self._icon_lbl: Optional[QLabel] = QLabel()
            self._icon_lbl.setPixmap(icon.pixmap(icon_px, icon_px))
            self._icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._icon_lbl.setStyleSheet("background: transparent;")
            lay.addWidget(self._icon_lbl, 0, Qt.AlignVCenter)
        else:
            self._icon_lbl = None
        self._text_lbl = QLabel(text)
        self._text_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._text_lbl, 0, Qt.AlignVCenter)
        lay.addStretch(1)

    # ---- sizeHint override — layout 기준으로 폭/높이 결정 (QPushButton 기본은 text/icon 이라 0 에 가까움) ----
    def sizeHint(self) -> QSize:  # type: ignore[override]
        lay = self.layout()
        return lay.sizeHint() if lay is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        lay = self.layout()
        return lay.minimumSize() if lay is not None else super().minimumSizeHint()

    def setText(self, text: str) -> None:  # type: ignore[override]
        """런타임 텍스트 교체 — 내부 QLabel 갱신 (QPushButton 의 _text 는 안 씀)."""
        self._text_lbl.setText(text)
        self.updateGeometry()

    def text(self) -> str:  # type: ignore[override]
        return self._text_lbl.text()
