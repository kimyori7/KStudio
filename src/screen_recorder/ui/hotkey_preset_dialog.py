"""단축키 프리셋 선택 다이얼로그 — 두 차원 라디오.

차원 1: 글로벌 (캡처 / 녹화 / 편집기)  — windows-standard / kstudio-default
차원 2: 영상 플레이어                     — kstudio-default / goom-style

첫 실행 + 환경설정의 "프리셋 선택…" 버튼에서 같은 다이얼로그를 재사용.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)


_GLOBAL_OPTIONS = [
    ("kstudio-default",
     "🛠 KStudio 기본",
     "영역 캡처 Ctrl+Shift+R · 영역 녹화 Ctrl+Shift+T"),
    ("windows-standard",
     "🖥 윈도우 표준",
     "영역 캡처 Ctrl+Win+S · 영역 녹화 Ctrl+Alt+R"),
]

_PLAYER_OPTIONS = [
    ("kstudio-default",
     "🛠 KStudio 기본",
     "프레임 step D/F · 스냅샷 Ctrl+Shift+P"),
    ("goom-style",
     "🎮 곰플레이어 호환",
     "프레임 step A/D · 스냅샷 Ctrl+G"),
]


def _make_radio_group(parent: QWidget, options: list[tuple[str, str, str]],
                       default_id: str) -> tuple[QButtonGroup, dict[str, QRadioButton]]:
    """라디오 버튼 묶음 생성. default_id 의 라디오를 체크 상태로."""
    group = QButtonGroup(parent)
    radios: dict[str, QRadioButton] = {}
    for opt_id, title, desc in options:
        rb = QRadioButton()
        rb.setText(f"{title}\n   {desc}")
        rb.setStyleSheet("QRadioButton { padding: 6px; color: #E8E9EE; }")
        if opt_id == default_id:
            rb.setChecked(True)
        group.addButton(rb)
        radios[opt_id] = rb
    return group, radios


class HotkeyPresetDialog(QDialog):
    """두 차원 라디오 선택 — selected_global / selected_player 속성으로 결과 반환.

    accept 후:
      - 사용자가 적용 누름: selected_global / selected_player 가 둘 다 set
      - 사용자가 건너뛰기: 둘 다 None
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 *, current_global: str = "kstudio-default",
                 current_player: str = "kstudio-default") -> None:
        super().__init__(parent)
        self.setWindowTitle("KStudio 단축키 프리셋")
        self.setModal(True)
        self.resize(560, 460)
        self.selected_global: Optional[str] = None
        self.selected_player: Optional[str] = None

        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        intro = QLabel("자주 쓰는 단축키 묶음을 한 번에 적용합니다.\n"
                       "두 차원이 직교적이라 자유롭게 조합할 수 있어요.")
        intro.setStyleSheet("color: #C0C4CC;")
        outer.addWidget(intro)

        # ===== 차원 1: 글로벌 =====
        outer.addWidget(self._section_title("📷 캡처 / 녹화 (글로벌 단축키)"))
        global_default = current_global if current_global in {o[0] for o in _GLOBAL_OPTIONS} else "kstudio-default"
        self._global_group, self._global_radios = _make_radio_group(self, _GLOBAL_OPTIONS, global_default)
        for rb in self._global_radios.values():
            outer.addWidget(rb)

        outer.addWidget(self._make_separator())

        # ===== 차원 2: 영상 플레이어 =====
        outer.addWidget(self._section_title("🎬 영상 플레이어"))
        player_default = current_player if current_player in {o[0] for o in _PLAYER_OPTIONS} else "kstudio-default"
        self._player_group, self._player_radios = _make_radio_group(self, _PLAYER_OPTIONS, player_default)
        for rb in self._player_radios.values():
            outer.addWidget(rb)

        outer.addStretch(1)

        # ===== 버튼 =====
        btn_box = QDialogButtonBox()
        skip_btn = QPushButton("건너뛰기 (현재 키 유지)")
        skip_btn.clicked.connect(self._on_skip)
        btn_box.addButton(skip_btn, QDialogButtonBox.RejectRole)
        apply_btn = QPushButton("적용")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply)
        btn_box.addButton(apply_btn, QDialogButtonBox.AcceptRole)
        outer.addWidget(btn_box)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 12pt; font-weight: 600; color: #E8E9EE; margin-top: 4px;")
        return lbl

    @staticmethod
    def _make_separator() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color: #3A3D44;")
        return f

    def _on_apply(self) -> None:
        self.selected_global = self._checked_id(self._global_radios)
        self.selected_player = self._checked_id(self._player_radios)
        self.accept()

    def _on_skip(self) -> None:
        self.selected_global = None
        self.selected_player = None
        self.accept()

    @staticmethod
    def _checked_id(radios: dict[str, QRadioButton]) -> Optional[str]:
        for opt_id, rb in radios.items():
            if rb.isChecked():
                return opt_id
        return None
