"""앱 전체에 적용되는 다크 테마 QSS — 모드별 팔레트.

tokens.PALETTES 에서 "video" / "image" 팔레트를 골라 f-string 으로 QSS 빌드.
폰트는 시스템 폰트(Segoe UI / 맑은 고딕 / Apple SD Gothic Neo) 유지 — 추가 폰트 번들 없음.

apply_theme 은 **시작 시 1회 전용**이다. 모드 전환에 재호출하면 앱 안의 모든 위젯이 다시
polish 되어 열린 탭 수에 따라 비용이 급증한다 (탭 16개 2.2초). 모드 전환은
theme_scope.ThemeScope 가 chrome 위젯과 각 탭에만 적용한다.
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

from PySide6.QtWidgets import QApplication

from screen_recorder.ui import icons
from screen_recorder.ui.tokens import PALETTES, VIDEO_PALETTE

_ASSET_DIR = os.path.join(tempfile.gettempdir(), "kstudio_theme")

# 탭을 담는 중앙 컨테이너의 objectName. QSS 셀렉터와 main_window 의 setObjectName 이
# 같은 값을 써야 하므로 여기서 한 번만 정의한다.
CENTRAL_HOST_NAME = "KStudioCentralHost"


def _chevron_arrow_png(color: str, px: int = 28) -> Optional[str]:
    """QComboBox down-arrow 용 chevron-down 을 color 로 렌더한 PNG 경로 반환 (forward-slash).

    QSS 의 image:url() 은 파일 경로가 필요하고(데이터 URI 미지원), SVG-url 은 PyInstaller
    에서 qsvg 이미지 플러그인 누락 시 깨질 수 있어 PNG 로 굽는다. icons._render_pixmap 으로
    렌더 → 임시 폴더에 color 별 1회 캐시. 쓰기 실패(권한/디스크) 시 None → 호출자가
    border-삼각형으로 폴백(아무것도 안 그려지는 것보다 안전).
    """
    try:
        os.makedirs(_ASSET_DIR, exist_ok=True)
        safe = (color or "").lstrip("#") or "default"
        path = os.path.join(_ASSET_DIR, f"chevron-down-{safe}-{px}.png")
        if not os.path.exists(path):
            pm = icons._render_pixmap("chevron-down", int(px), color or icons.COLOR_BASE)
            if not pm.save(path, "PNG"):
                return None
        return path.replace("\\", "/") if os.path.exists(path) else None
    except OSError:
        return None


def _down_arrow_rule(p: dict[str, str], arrow_icon_path: Optional[str]) -> str:
    """QComboBox::down-arrow QSS 규칙. PNG 가 있으면 image, 없으면 border-삼각형 폴백."""
    if arrow_icon_path:
        return (
            "QComboBox::down-arrow {\n"
            f'    image: url("{arrow_icon_path}");\n'
            "    width: 12px;\n"
            "    height: 12px;\n"
            "}"
        )
    return (
        "QComboBox::down-arrow {\n"
        "    image: none;\n"
        "    width: 0;\n"
        "    height: 0;\n"
        "    border-left: 4px solid transparent;\n"
        "    border-right: 4px solid transparent;\n"
        f'    border-top: 5px solid {p["text_sub"]};\n'
        "}"
    )


def build_qss(p: dict[str, str], arrow_icon_path: Optional[str] = None) -> str:
    """팔레트 dict 에서 전체 QSS 문자열 생성.

    arrow_icon_path 주어지면 QComboBox 펼침 화살표를 그 PNG 로(권장), 없으면 border 삼각형.
    """
    down_arrow_rule = _down_arrow_rule(p, arrow_icon_path)
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
{down_arrow_rule}
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

/* ----- 스크롤바 — 미니멀 얇은 pill (반투명 흰색, hover 시 또렷) -----
   12px 트랙 안에 2px inset 으로 ≈8px 알약형 핸들. 색은 팔레트 독립(반투명 흰색)
   이라 영상/이미지/문서 어느 모드 다크 배경에서도 일관되게 보인다. */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.18);
    min-height: 36px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 0.34);
}}
QScrollBar::handle:vertical:pressed {{
    background: rgba(255, 255, 255, 0.46);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 0.18);
    min-width: 36px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(255, 255, 255, 0.34);
}}
QScrollBar::handle:horizontal:pressed {{
    background: rgba(255, 255, 255, 0.46);
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
QAbstractScrollArea::corner {{
    background: transparent;
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
{_mode_property_rules()}
"""


def _mode_property_rules() -> str:
    """`kmode` 동적 property 로 모드 색이 정해지는 위젯들의 규칙 (모든 모드 분을 한꺼번에).

    범위를 좁힐 수 없는 위젯 — 자식 subtree 전체가 딸려 오는 QMainWindow, QTabWidget —
    은 스타일시트를 새로 걸면 그 아래 모든 탭까지 repolish 되어 비용이 탭 수에 따라
    급증한다 (탭 16개에서 2.2초). 대신 세 모드 규칙을 모두 넣어 두고 전환 시에는
    property 만 바꿔 그 위젯 하나만 repolish 한다 (0.1ms).

    theme_scope.ThemeScope 가 property 설정과 단일 repolish 를 담당한다.
    """
    out: list[str] = []
    for name, p in PALETTES.items():
        # 셀렉터는 최대한 좁게 — `QWidget[kmode=...]` 처럼 범용으로 두면 polish 때마다
        # 모든 위젯에 대해 속성 매칭이 일어나 chrome/탭 적용 비용이 3배로 늘었다(실측).
        out.append(
            f'QMainWindow[kmode="{name}"] {{ background-color: {p["bg"]}; }}\n'
            # 탭 바 오른쪽 빈 칸을 칠하는 중앙 컨테이너 (main_window 가 이 이름을 붙인다).
            f'QWidget#{CENTRAL_HOST_NAME}[kmode="{name}"] {{'
            f' background-color: {p["bg"]}; }}\n'
            f'QTabWidget[kmode="{name}"] {{ background-color: {p["bg"]}; }}\n'
            f'QTabWidget[kmode="{name}"]::pane {{'
            f' border: 1px solid {p["border_dim"]}; background: {p["bg"]}; }}'
        )
    return "\n".join(out)


# palette 이름 → 완성된 QSS 문자열. 빌드 자체는 1ms 미만이지만 모드 전환마다 여러
# 위젯에 같은 문자열을 거므로 동일 인스턴스를 재사용해 Qt 의 파싱 캐시도 태운다.
_qss_cache: dict[str, str] = {}


def qss_for(palette_name: str) -> str:
    """모드 이름 → 그 모드의 전체 QSS (캐시)."""
    if palette_name not in PALETTES:
        palette_name = "video"
    cached = _qss_cache.get(palette_name)
    if cached is not None:
        return cached
    p = PALETTES[palette_name]
    qss = build_qss(p, _chevron_arrow_png(p.get("text_sub", "")))
    _qss_cache[palette_name] = qss
    return qss


_current_palette: dict[str, str] = VIDEO_PALETTE


def current_palette() -> dict[str, str]:
    """현재 모드 팔레트 (없으면 VIDEO_PALETTE).

    전역 stylesheet 는 문자열이라 역파싱이 불가능하므로, 다이얼로그 등이 현재
    모드 액센트 색을 알아야 할 때 이 함수를 쓴다. 모드 전환은 apply_theme 이 아니라
    theme_scope.ThemeScope 가 처리하므로, 그쪽도 set_current_palette 로 이 값을
    갱신한다 — 갱신을 빠뜨리면 다이얼로그만 이전 모드 액센트로 남는다.
    """
    return _current_palette


def set_current_palette(palette_name: str) -> dict[str, str]:
    """current_palette() 가 돌려줄 팔레트를 지정하고 그 팔레트를 반환."""
    global _current_palette
    _current_palette = PALETTES.get(palette_name, VIDEO_PALETTE)
    return _current_palette


def apply_theme(app: QApplication, palette_name: str = "video") -> None:
    """QApplication 전역에 모드 테마 적용 — **시작 시 1회만** 호출할 것.

    이 호출은 앱 안의 모든 위젯을 repolish 하며 비용이 열린 탭 수에 따라 급증한다
    (탭 2개 62ms → 16개 2225ms). 따라서 모드 전환에는 쓰지 말고 theme_scope.ThemeScope
    를 쓴다. 시작 시점엔 위젯이 몇 개 없어 비용이 무시할 만하다.

    palette_name 미지정 시 영상 모드(시안) 로 폴백 — 모드 시스템이 없는 컨텍스트
    (예: 일부 다이얼로그 단독 테스트) 에서도 안전한 기본값.
    """
    set_current_palette(palette_name)
    app.setStyleSheet(qss_for(palette_name))
