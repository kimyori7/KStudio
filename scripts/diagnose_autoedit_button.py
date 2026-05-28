"""자동 편집 버튼 진단 — 실제 렌더링을 PNG 로 캡처 + 메트릭 출력.

사용자 보고: 버튼 안 텍스트가 가운데 정렬 안 되어 보임. 픽셀 단위 튜닝 대신
근본 원인 (sizeHint / styleSheet / 내부 layout 동작) 을 데이터로 확인.
"""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_recorder.ui.theme import apply_theme  # noqa: E402
from screen_recorder.ui.icons import load_icon    # noqa: E402


def make_test_buttons() -> QWidget:
    """기존 + 후보 해결책 비교 — 가운데 정렬이 진짜 되는 게 어떤 건지 시각 검증."""
    from PySide6.QtWidgets import QFrame, QLabel
    from screen_recorder.ui.icons import COLOR_BASE

    root = QWidget()
    root.setFixedSize(1400, 80)
    lay = QHBoxLayout(root)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(20)

    # ❌ 변형 A — 현재(망가짐): QPushButton + QIcon. icon 좌측 고정, text-align center 무시.
    a = QPushButton(load_icon("sparkles", size=14), "자동 편집")
    a.setIconSize(QSize(14, 14))
    a.setObjectName("A_icon+text(broken)")
    lay.addWidget(a)

    # ✓ 변형 B — 순수 텍스트. Qt 가 알아서 가운데.
    b = QPushButton("자동 편집")
    b.setObjectName("B_text-only")
    lay.addWidget(b)

    # ✓ 변형 C — QFrame 을 버튼 모양으로 styling + 내부 HBoxLayout 으로 icon+text 진짜 가운데.
    #            QPushButton 상속 안 함 → click 처리는 mousePressEvent 로 따로 (이 진단에선 외관만).
    c = QFrame()
    c.setObjectName("C_frame+layout")
    c.setProperty("class", "FakeButton")
    c.setStyleSheet(
        "QFrame[class=\"FakeButton\"] {"
        "  background-color: #2A2D34;"
        "  border: 1px solid #3F4554;"
        "  border-radius: 6px;"
        "  min-height: 22px;"
        "}"
        "QFrame[class=\"FakeButton\"] QLabel { background: transparent; color: #E8E9EE; }"
    )
    c_lay = QHBoxLayout(c)
    c_lay.setContentsMargins(14, 6, 14, 6)
    c_lay.setSpacing(6)
    c_lay.addStretch(1)
    icon_lbl = QLabel()
    icon_lbl.setPixmap(load_icon("sparkles", size=14, color=COLOR_BASE).pixmap(14, 14))
    c_lay.addWidget(icon_lbl, 0, Qt.AlignVCenter)
    text_lbl = QLabel("자동 편집")
    c_lay.addWidget(text_lbl, 0, Qt.AlignVCenter)
    c_lay.addStretch(1)
    lay.addWidget(c)

    # ❌ 변형 D — QPushButton + 내부 layout (이전 시도) — sizeHint 가 layout 무시 → 잘림.
    d = QPushButton()
    d.setObjectName("D_btn+inner(sizeHint broken)")
    d_lay = QHBoxLayout(d)
    d_lay.setContentsMargins(14, 0, 14, 0)
    d_lay.setSpacing(6)
    d_lay.addStretch(1)
    di = QLabel()
    di.setPixmap(load_icon("sparkles", size=14, color=COLOR_BASE).pixmap(14, 14))
    di.setStyleSheet("background: transparent;")
    di.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    d_lay.addWidget(di, 0, Qt.AlignVCenter)
    dt = QLabel("자동 편집")
    dt.setStyleSheet("background: transparent;")
    dt.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    d_lay.addWidget(dt, 0, Qt.AlignVCenter)
    d_lay.addStretch(1)
    lay.addWidget(d)

    # ✓ 변형 E — QPushButton 서브클래스 + sizeHint override.
    #            D 와 동일 구조이지만 sizeHint 를 layout.sizeHint() 로 강제.
    #            click signal / focus ring 등 native QPushButton 동작 보존하면서 정렬 OK.
    class CenteredButton(QPushButton):
        def sizeHint(self):
            lay = self.layout()
            return lay.sizeHint() if lay else super().sizeHint()

        def minimumSizeHint(self):
            lay = self.layout()
            return lay.minimumSize() if lay else super().minimumSizeHint()

    e = CenteredButton()
    e.setObjectName("E_subclass+sizeHint")
    e_lay = QHBoxLayout(e)
    e_lay.setContentsMargins(14, 6, 14, 6)
    e_lay.setSpacing(6)
    e_lay.addStretch(1)
    ei = QLabel()
    ei.setPixmap(load_icon("sparkles", size=14, color=COLOR_BASE).pixmap(14, 14))
    ei.setStyleSheet("background: transparent;")
    ei.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    e_lay.addWidget(ei, 0, Qt.AlignVCenter)
    et = QLabel("자동 편집")
    et.setStyleSheet("background: transparent;")
    et.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    e_lay.addWidget(et, 0, Qt.AlignVCenter)
    e_lay.addStretch(1)
    lay.addWidget(e)

    # ★ 변형 F — 현재 CenteredIconButton (margin=0 — 컨텐츠가 border 에 닿아 cramped).
    from screen_recorder.ui.widgets import CenteredIconButton
    f = CenteredIconButton(load_icon("sparkles", size=14), "자동 편집", icon_px=14)
    f.setObjectName("F_margin=0(cramped)")
    lay.addWidget(f)

    # ★ 변형 G — QSS padding override + layout margin 14 — height 가 25로 짧아짐 (탈락).
    g = CenteredIconButton(load_icon("sparkles", size=14), "자동 편집", icon_px=14)
    g.setObjectName("G_qss-padding-0_short")
    g.setStyleSheet("QPushButton { padding: 0; }")
    g.layout().setContentsMargins(14, 4, 14, 4)
    lay.addWidget(g)

    # ★ 변형 H — QSS 그대로 + layout margins (14, 4, 14, 4). E 와 동일 recipe 를 클래스에 적용.
    h = CenteredIconButton(load_icon("sparkles", size=14), "자동 편집", icon_px=14)
    h.setObjectName("H_lay-14-4")
    h.layout().setContentsMargins(14, 4, 14, 4)
    lay.addWidget(h)

    lay.addStretch(1)
    return root, [a, b, c, d, e, f, g, h]


def report(btn) -> None:
    """버튼의 sizeHint / 실제 size 출력 — QFrame/QPushButton 둘 다 OK."""
    sh = btn.sizeHint()
    sz = btn.size()
    print(f"  {btn.objectName()}: "
          f"sizeHint=({sh.width()}, {sh.height()}), "
          f"size=({sz.width()}, {sz.height()})")


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app, "video")
    root, buttons = make_test_buttons()
    root.show()
    # show 후 layout 이 한 번 돌아야 size/sizeHint 가 안정됨.
    app.processEvents()

    print("=== 버튼 메트릭 (theme 적용 후) ===")
    for b in buttons:
        report(b)

    # 전체 윈도우 grab 으로 PNG 저장.
    out = ROOT / "test_output.png"
    pixmap = root.grab()
    pixmap.save(str(out))
    print(f"\n→ 캡처 저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
