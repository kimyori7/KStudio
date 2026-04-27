"""스크린샷 뷰어 창 — 탭 컨테이너 + 저장/복사 워크플로우."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage, QAction, QKeySequence, QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QFileDialog, QMessageBox,
)

from ..core.settings import AppSettings
from ..core.filename import build_filename, resolve_collision
from ..screenshot.capture import save_png
from .screenshot_tab import ScreenshotTab
from .screenshot_close_dialog import CloseDialog, CloseAction
from .app_icon import app_icon
from .capture_exclude import exclude_from_capture
from .toast import show_toast


class ScreenshotViewer(QMainWindow):
    closed = Signal()  # 창이 완전히 닫히는 시점 (main_window 가 참조 정리용)

    def __init__(self, settings: AppSettings):
        super().__init__()
        self.setWindowTitle("Screenshot Viewer")
        self.setWindowIcon(app_icon())

        self._settings = settings

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.setCentralWidget(self._tabs)

        self._build_toolbar()

        # 마지막 창 위치/크기 복원
        s = settings.screenshot
        if s.viewer_x >= 0 and s.viewer_y >= 0 and s.viewer_w > 0 and s.viewer_h > 0:
            self.setGeometry(s.viewer_x, s.viewer_y, s.viewer_w, s.viewer_h)
        else:
            self.resize(900, 700)

    # ---------- 외부 API ----------

    def add_tab(self, image: QImage, source_label: str) -> None:
        """새 캡처 탭 추가. source_label 은 파일명 {target} 토큰에 쓰임 (예: 'region'/'fullscreen')."""
        tab = ScreenshotTab(image, source_label=source_label)
        tab.save_state_changed.connect(lambda i=tab: self._refresh_tab_title_for(i))

        idx = self._tabs.addTab(tab, "")
        self._refresh_tab_title_for(tab)
        self._tabs.setCurrentIndex(idx)

        # 최소화 상태였으면 복원 + 포커스 (D9)
        if self.isMinimized():
            self.showNormal()
        elif not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def tab_count(self) -> int:
        return self._tabs.count()

    def current_index(self) -> int:
        return self._tabs.currentIndex()

    def current_tab(self) -> ScreenshotTab | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, ScreenshotTab) else None

    def tab_title(self, index: int) -> str:
        return self._tabs.tabText(index)

    def save_current_tab(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if self._settings.screenshot.save_dir == "":
            # 저장 폴더가 아직 지정되지 않았으면 기본 경로(~/Pictures/KStudio)를
            # 자동 생성하고 settings 에도 기록한다. 사용자는 나중에 패널에서 바꿀 수 있다.
            default_dir = Path.home() / "Pictures" / "KStudio"
            try:
                default_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, "저장 실패", f"기본 폴더 생성 실패: {e}")
                return
            self._settings.screenshot.save_dir = str(default_dir)

        target_label = tab.source_label()
        out_dir = Path(self._settings.screenshot.save_dir)
        name = build_filename(
            pattern=self._settings.screenshot.filename_pattern,
            when=datetime.now(),
            mode="screenshot",
            target=target_label,
            extension=self._settings.screenshot.format,
        )
        path = resolve_collision(out_dir / name)
        try:
            save_png(tab.image(), path)
            tab.mark_saved(path)
            show_toast(self, f"저장됨: {path.name}", 1500)
        except IOError as e:
            QMessageBox.warning(self, "저장 실패", str(e))

    def save_current_tab_as(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        default_dir = self._settings.screenshot.save_dir or str(Path.home() / "Pictures" / "KStudio")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장",
            str(Path(default_dir) / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"),
            "PNG Image (*.png)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if not path.suffix:
            path = path.with_suffix(".png")
        try:
            save_png(tab.image(), path)
            tab.mark_saved(path)
            show_toast(self, f"저장됨: {path.name}", 1500)
        except IOError as e:
            QMessageBox.warning(self, "저장 실패", str(e))

    def copy_current_to_clipboard(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        QGuiApplication.clipboard().setImage(tab.image())

    def close_tab(self, index: int) -> None:
        """경고 없이 탭 제거 (caller 가 가드 처리한 뒤 호출)."""
        w = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if w is not None:
            w.deleteLater()
        if self._tabs.count() == 0:
            self.close()

    # ---------- 내부 ----------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self._act_save = QAction("저장", self)
        self._act_save.setShortcut(QKeySequence("Ctrl+S"))
        self._act_save.triggered.connect(self.save_current_tab)
        tb.addAction(self._act_save)

        self._act_save_as = QAction("다른 이름으로", self)
        self._act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_save_as.triggered.connect(self.save_current_tab_as)
        tb.addAction(self._act_save_as)

        self._act_copy = QAction("복사", self)
        self._act_copy.setShortcut(QKeySequence("Ctrl+C"))
        self._act_copy.triggered.connect(self.copy_current_to_clipboard)
        tb.addAction(self._act_copy)

    def _refresh_tab_title_for(self, tab: ScreenshotTab) -> None:
        idx = self._tabs.indexOf(tab)
        if idx < 0:
            return
        label = tab.source_label()
        base = f"{label} {idx + 1}"
        title = base if tab.is_saved() else f"● {base}"
        self._tabs.setTabText(idx, title)

    def _unsaved_count(self) -> int:
        return sum(
            1 for i in range(self._tabs.count())
            if isinstance(self._tabs.widget(i), ScreenshotTab)
            and not self._tabs.widget(i).is_saved()
        )

    def _drop_all_tabs(self) -> None:
        while self._tabs.count() > 0:
            w = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if w is not None:
                w.deleteLater()

    def _on_tab_close_requested(self, index: int) -> None:
        # 닫기 요청 → 저장 안 된 탭이 하나라도 있으면 다이얼로그
        unsaved_count = self._unsaved_count()
        if unsaved_count == 0:
            self.close_tab(index)
            return
        dlg = CloseDialog(unsaved_count, parent=self)
        dlg.exec()
        action = dlg.action()
        if action == CloseAction.CANCEL:
            return
        if action == CloseAction.CLOSE_CURRENT:
            self.close_tab(index)
            return
        # CLOSE_ALL — 모든 탭 제거 후 창 닫힘
        self._drop_all_tabs()
        self.close()

    def closeEvent(self, e):
        # 창 X 클릭 시 — 저장 안 된 탭 경고
        unsaved_count = self._unsaved_count()
        if unsaved_count > 0:
            dlg = CloseDialog(unsaved_count, parent=self)
            dlg.exec()
            action = dlg.action()
            if action == CloseAction.CANCEL:
                e.ignore()
                return
            if action == CloseAction.CLOSE_CURRENT:
                # 창 X 인데 현재 탭만 닫기 선택 → 창은 유지
                idx = self._tabs.currentIndex()
                w = self._tabs.widget(idx)
                self._tabs.removeTab(idx)
                if w is not None:
                    w.deleteLater()
                if self._tabs.count() == 0:
                    e.accept()
                else:
                    e.ignore()
                return
            # CLOSE_ALL: 통과 (모든 탭 버리고 창 닫음)

        # 기하학 저장
        g = self.geometry()
        s = self._settings.screenshot
        s.viewer_x, s.viewer_y, s.viewer_w, s.viewer_h = g.x(), g.y(), g.width(), g.height()

        self.closed.emit()
        e.accept()

    def showEvent(self, e):
        super().showEvent(e)
        # 자기 창이 다음 스크린샷 캡처에 찍히지 않도록 제외
        exclude_from_capture(self)
