"""모드 전환이 전역 스타일시트를 다시 걸지 않는지 (탭이 쌓여도 느려지지 않는 근거).

회귀 배경: 모드 전환마다 QApplication.setStyleSheet 을 호출했고, 그 비용이 열린 탭
수에 따라 급증해 (탭 16개 2.2초, 실사용 로그 탭 24개 3.9초) 영상↔이미지 전환과
스크린샷 촬영 직후가 몇 초씩 멈췄다. 지금은 chrome 위젯과 각 탭에만 건다.
"""
from PySide6.QtWidgets import QApplication, QWidget

from screen_recorder.ui.theme import (
    CENTRAL_HOST_NAME, apply_theme, current_palette, qss_for,
)
from screen_recorder.ui.theme_scope import MODE_PROPERTY, ThemeScope
from screen_recorder.ui.tokens import IMAGE_PALETTE, VIDEO_PALETTE


def test_set_mode_leaves_app_stylesheet_untouched(qtbot):
    app = QApplication.instance()
    apply_theme(app, "video")
    before = app.styleSheet()

    scope = ThemeScope(app, "video")
    scope.set_mode("image")

    assert app.styleSheet() == before


def test_set_mode_restyles_registered_chrome_only(qtbot):
    app = QApplication.instance()
    apply_theme(app, "video")
    chrome = QWidget()
    other = QWidget()
    qtbot.addWidget(chrome)
    qtbot.addWidget(other)

    scope = ThemeScope(app, "video")
    scope.register_chrome(chrome)
    scope.set_mode("image")

    assert chrome.styleSheet() == qss_for("image")
    assert other.styleSheet() == ""


def test_mode_property_widget_gets_property_not_stylesheet(qtbot):
    """탭을 자식으로 갖는 위젯은 스타일시트 대신 property 로만 모드를 바꾼다."""
    app = QApplication.instance()
    apply_theme(app, "video")
    holder = QWidget()
    qtbot.addWidget(holder)

    scope = ThemeScope(app, "video")
    scope.register_mode_property(holder)
    scope.set_mode("image")

    assert holder.property(MODE_PROPERTY) == "image"
    assert holder.styleSheet() == ""


def test_style_tab_keeps_its_own_mode_after_switch(qtbot):
    """탭은 만들어질 때 자기 모드 QSS 를 받고, 이후 모드 전환에 영향받지 않는다."""
    app = QApplication.instance()
    apply_theme(app, "video")
    video_tab = QWidget()
    qtbot.addWidget(video_tab)

    scope = ThemeScope(app, "video")
    scope.style_tab(video_tab, "video")
    scope.set_mode("image")

    assert video_tab.styleSheet() == qss_for("video")


def test_current_palette_follows_mode(qtbot):
    app = QApplication.instance()
    apply_theme(app, "video")
    scope = ThemeScope(app, "video")
    assert current_palette()["primary"] == VIDEO_PALETTE["primary"]

    scope.set_mode("image")
    assert current_palette()["primary"] == IMAGE_PALETTE["primary"]


def test_qss_carries_mode_property_rules_for_every_palette():
    """세 모드 규칙이 모든 QSS 에 들어 있어야 property 전환만으로 색이 바뀐다."""
    qss = qss_for("video")
    for name in ("video", "image", "document"):
        assert f'QMainWindow[{MODE_PROPERTY}="{name}"]' in qss
        assert f'QWidget#{CENTRAL_HOST_NAME}[{MODE_PROPERTY}="{name}"]' in qss
        assert f'QTabWidget[{MODE_PROPERTY}="{name}"]::pane' in qss


def test_mode_property_selectors_are_not_universal():
    """`QWidget[kmode=...]` 같은 범용 속성 셀렉터는 금지 — polish 마다 모든 위젯에 대해
    속성 매칭이 일어나 chrome/탭 적용 비용이 3배가 된다 (실측 후 좁힌 규칙)."""
    qss = qss_for("video")
    assert f'QWidget[{MODE_PROPERTY}=' not in qss


def test_main_window_registers_tab_holding_widgets_as_property_only(qtbot):
    """탭을 자식으로 갖는 위젯(메인 창·탭 영역·중앙 컨테이너)에는 스타일시트를 걸지 않는다.

    하나라도 스타일시트를 받으면 그 아래 모든 탭이 함께 repolish 되어 최적화가 무효가 된다.
    """
    from screen_recorder.app.main import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.theme_scope.set_mode("image")

    for holder in (win, win.tab_area, win._central_host):
        assert holder.styleSheet() == ""
        assert holder.property(MODE_PROPERTY) == "image"
    win.close()
