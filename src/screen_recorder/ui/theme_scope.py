"""모드 테마를 '앱 전역'이 아니라 '필요한 위젯에만' 적용하는 배선.

## 왜 필요한가

`QApplication.setStyleSheet` 은 앱 안의 **모든** 위젯을 다시 polish 한다. 그 비용은
열린 탭 수에 따라 급격히 커진다 (실측: 탭 2개 62ms / 8개 607ms / 16개 2225ms,
실사용 로그에서는 탭 24개일 때 3889ms). 모드 전환마다 이 호출이 있었기 때문에
영상↔이미지 전환과, 새 탭을 여는 모든 동작(스크린샷 촬영 직후 포함)이 몇 초씩 멈췄다.

## 어떻게 바꾸는가

전역 스타일시트는 시작 시 1회만 걸고 그대로 둔다. 모드가 바뀌면:

1. **chrome** — 메뉴 바·툴바·도구 팔레트·상태바·도크·탭 바 등 모드 색이 보여야 하는
   상단/주변 위젯들에만 그 모드 QSS 를 건다. 위젯 자신에게 건 스타일시트는 전역보다
   우선하므로 색이 제대로 덮인다. 개수가 고정이라 탭이 몇 개든 비용이 늘지 않는다.
2. **탭** — 탭은 각자 하나의 모드에만 속하므로, 만들어질 때 자기 모드 QSS 를 한 번
   걸어 두면 이후 모드 전환에서 다시 손댈 필요가 없다.
3. **창 배경 등 범위를 좁힐 수 없는 위젯** — QMainWindow·QTabWidget 에 스타일시트를
   걸면 그 아래 모든 탭까지 딸려 와 원래 비용으로 돌아간다. 대신 세 모드 규칙을 전역
   QSS 에 미리 넣어 두고(theme._mode_property_rules) `kmode` property 만 바꿔 그
   위젯 하나만 repolish 한다.
4. **다이얼로그** — 나중에 만들어지는 최상위 창은 전역(시작 모드) QSS 를 물려받으므로
   활성화될 때 현재 모드 QSS 를 걸어 준다. 자기 subtree 만 repolish 되어 저렴하다.
"""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog, QDockWidget, QWidget

from . import theme

# 이 property 로 모드가 정해지는 위젯(QMainWindow / QTabWidget)에 쓰는 키.
# theme._mode_property_rules() 의 셀렉터와 반드시 같아야 한다.
MODE_PROPERTY = "kmode"

# 최상위 창에 어느 모드 QSS 를 걸어 뒀는지 기록해 같은 창에 반복 적용하지 않기 위한 키.
_APPLIED_PROPERTY = "_kstudio_theme_mode"


class ThemeScope(QObject):
    """모드 QSS 를 정해진 위젯 집합에만 적용한다.

    사용법:
        scope = ThemeScope(app)
        scope.register_chrome(menu_bar, toolbar, ...)
        scope.register_mode_property(main_window, tab_area)
        scope.set_mode("image")          # 모드 전환 시
        scope.style_tab(widget, "image") # 새 탭이 생길 때
    """

    def __init__(self, app: QApplication, mode_name: str = "video",
                 parent: Optional[QObject] = None) -> None:
        # parent 는 QApplication 이 아니라 메인 창을 넘길 것. QApplication 에 붙이면
        # 종료 시 파이썬 래퍼가 먼저 사라진 뒤 Qt 가 자식을 지우며 access violation 이
        # 난다 (테스트에서 전원 통과 후 프로세스가 죽는 형태로 나타남).
        super().__init__(parent)
        self._app = app
        self._mode_name = mode_name
        self._chrome: list[QWidget] = []
        self._prop_widgets: list[QWidget] = []
        # 전환 시점에 숨어 있어 적용을 미룬 도크들.
        self._deferred: list[QWidget] = []
        theme.set_current_palette(mode_name)

    # ---------- 등록 ----------
    def register_chrome(self, *widgets: Optional[QWidget]) -> None:
        """모드가 바뀔 때마다 그 모드 QSS 를 다시 걸 위젯들.

        탭을 자식으로 갖는 위젯(QMainWindow, TabArea, central widget)은 절대 넣지 말 것 —
        넣는 순간 모든 탭이 함께 repolish 되어 최적화가 통째로 무효가 된다.

        QDockWidget 은 숨겨져 있으면 적용을 미룬다 — 레이어 도크처럼 자식이 많은 패널
        (289개, 250ms)이 그 모드에서 보이지도 않는데 비용을 내는 것을 막는다. 다시 보일 때
        visibilityChanged 로 밀린 적용이 처리된다.
        """
        for w in widgets:
            if w is None or w in self._chrome:
                continue
            self._chrome.append(w)
            if isinstance(w, QDockWidget):
                w.visibilityChanged.connect(self._on_dock_visibility_changed)

    def register_mode_property(self, *widgets: Optional[QWidget]) -> None:
        """`kmode` property 로만 모드 색이 바뀌는 위젯들.

        탭을 자식으로 갖는 것들 — 메인 창, 탭 영역, 탭을 담는 중앙 컨테이너. 대응하는
        규칙은 theme._mode_property_rules() 가 모든 모드 분을 전역 QSS 에 미리 넣어 둔다.
        """
        for w in widgets:
            if w is not None and w not in self._prop_widgets:
                self._prop_widgets.append(w)

    # ---------- 적용 ----------
    def mode_name(self) -> str:
        return self._mode_name

    def set_mode(self, mode_name: str) -> None:
        """모드 전환 — chrome 재적용 + property 위젯 repolish. 탭은 건드리지 않는다."""
        self._mode_name = mode_name
        theme.set_current_palette(mode_name)
        qss = theme.qss_for(mode_name)
        self._deferred.clear()
        for w in self._chrome:
            if isinstance(w, QDockWidget) and not w.isVisible():
                self._deferred.append(w)   # 다시 보일 때 적용 (visibilityChanged)
                continue
            _set_stylesheet(w, qss)
        for w in self._prop_widgets:
            _set_mode_property(w, mode_name)

    def _on_dock_visibility_changed(self, visible: bool) -> None:
        """숨어 있어 건너뛴 도크가 다시 보이면 그때 현재 모드 QSS 를 적용."""
        if not visible or not self._deferred:
            return
        qss = theme.qss_for(self._mode_name)
        still_hidden = []
        for w in self._deferred:
            try:
                if w.isVisible():
                    _set_stylesheet(w, qss)
                else:
                    still_hidden.append(w)
            except RuntimeError:
                continue
        self._deferred = still_hidden

    def style_tab(self, widget: Optional[QWidget], mode_name: str) -> None:
        """새로 만들어진 탭에 그 탭이 속한 모드의 QSS 를 한 번 건다."""
        if widget is None:
            return
        _set_stylesheet(widget, theme.qss_for(mode_name))

    def style_toplevel(self, widget: Optional[QWidget]) -> None:
        """다이얼로그/메뉴 등 최상위 창에 현재 모드 QSS 적용 (이미 같은 모드면 무시)."""
        if widget is None:
            return
        if widget.property(_APPLIED_PROPERTY) == self._mode_name:
            return
        widget.setProperty(_APPLIED_PROPERTY, self._mode_name)
        _set_stylesheet(widget, theme.qss_for(self._mode_name))

    # ---------- 최상위 창 자동 처리 ----------
    def install_toplevel_filter(self) -> None:
        """다이얼로그가 활성화될 때 현재 모드 QSS 를 자동으로 걸어 준다.

        전역 스타일시트는 시작 모드로 고정돼 있어, 이 처리가 없으면 다른 모드에서 연
        다이얼로그만 시작 모드 액센트로 보인다.

        QApplication 전역 eventFilter 로 Show 를 잡는 방법은 쓰지 않는다 — 앱의 모든
        이벤트가 파이썬 호출을 거치게 되어 그 자체로 전반적인 지연을 만든다. 창 활성화
        신호는 드물게 발화하므로 비용이 없다.
        """
        self._app.focusWindowChanged.connect(self._on_focus_window_changed)

    def _on_focus_window_changed(self, _window) -> None:
        # activeWindow() 는 최상위 QWidget — 메인 창이면 절대 건드리지 않는다
        # (메인 창에 스타일시트를 걸면 모든 탭이 함께 repolish 되어 원래 비용으로 돌아간다).
        active = self._app.activeWindow()
        if isinstance(active, QDialog):
            self.style_toplevel(active)


def _set_stylesheet(widget: QWidget, qss: str) -> None:
    """이미 같은 문자열이면 건너뛴다 — Qt 는 같은 값이어도 repolish 를 다시 한다."""
    try:
        if widget.styleSheet() == qss:
            return
        widget.setStyleSheet(qss)
    except RuntimeError:
        # 이미 파괴된 위젯 — 등록 후 닫힌 도크 등. 조용히 무시해도 되는 유일한 경우.
        pass


def _set_mode_property(widget: QWidget, mode_name: str) -> None:
    """`kmode` property 변경 + 그 위젯 하나만 repolish (자식은 건드리지 않음)."""
    try:
        if widget.property(MODE_PROPERTY) == mode_name:
            return
        widget.setProperty(MODE_PROPERTY, mode_name)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
    except RuntimeError:
        pass


def chrome_widgets_of(window) -> Iterable[QWidget]:
    """MainWindow 에서 chrome 으로 등록할 위젯들을 모은다 (없는 속성은 건너뜀).

    탭을 품는 위젯(tab_area 자체, centralWidget, window 자신)은 의도적으로 제외한다.
    탭 바는 tab_area 의 자식이지만 탭 본문과 형제라 따로 걸어도 안전하다.
    """
    names = (
        "menu_bar", "title_bar", "_global_tb_host", "annotation_toolbar",
        "tool_palette", "status_bar",
        "library_dock", "layers_dock", "record_status_dock", "inspector_dock",
    )
    for name in names:
        w = getattr(window, name, None)
        if isinstance(w, QWidget):
            yield w
    tab_area = getattr(window, "tab_area", None)
    if tab_area is not None:
        bar = tab_area.tabBar()
        if bar is not None:
            yield bar
