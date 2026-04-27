"""스크린샷 뷰어 창 — 탭 컨테이너 + 저장/복사 워크플로우."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QImage, QAction, QKeySequence, QShortcut, QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QFileDialog, QMessageBox,
)

from .annotation_toolbar import AnnotationToolbar
from .annotation.tools.select import SelectTool
from .annotation.tools.rect import RectTool
from .annotation.tools.arrow import ArrowTool
from .annotation.tools.text import TextTool

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
        self.setWindowTitle("KPhotoShop")
        self.setWindowIcon(app_icon())

        self._settings = settings

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.setCentralWidget(self._tabs)

        self._build_toolbar()

        # 편집 툴바 (Phase 2) — 기존 툴바 아래에 새 줄로 추가
        self.annotation_toolbar = AnnotationToolbar(self)
        self.addToolBarBreak()
        self.addToolBar(self.annotation_toolbar)

        # 마지막 색/두께 복원
        self.annotation_toolbar.set_current_color(QColor(settings.annotation.last_color))
        self.annotation_toolbar.set_current_thickness_step(settings.annotation.last_thickness)

        self.annotation_toolbar.tool_changed.connect(self._on_tool_changed)
        self.annotation_toolbar.color_changed.connect(self._on_color_changed)
        self.annotation_toolbar.thickness_changed.connect(self._on_thickness_changed)
        self.annotation_toolbar.undo_requested.connect(self._on_undo)
        self.annotation_toolbar.redo_requested.connect(self._on_redo)
        self.annotation_toolbar.original_requested.connect(self._on_original)

        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._on_undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._on_redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self._on_redo)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self._on_original)

        self._tabs.currentChanged.connect(self._on_current_tab_changed)

        # 마지막 창 위치/크기 복원
        s = settings.screenshot
        if s.viewer_x >= 0 and s.viewer_y >= 0 and s.viewer_w > 0 and s.viewer_h > 0:
            self.setGeometry(s.viewer_x, s.viewer_y, s.viewer_w, s.viewer_h)
        else:
            self.resize(1170, 910)  # 기본 크기 (Phase 1 의 900×700 에서 30% 키움)

    # ---------- 외부 API ----------

    def add_tab(self, image: QImage, source_label: str) -> None:
        """새 캡처 탭 추가. source_label 은 파일명 {target} 토큰에 쓰임 (예: 'region'/'fullscreen')."""
        tab = ScreenshotTab(image, source_label=source_label)
        tab.save_state_changed.connect(lambda i=tab: self._refresh_tab_title_for(i))
        tab.canvas.zoom_changed.connect(self._on_zoom_changed)

        idx = self._tabs.addTab(tab, "")
        self._refresh_tab_title_for(tab)
        self._tabs.setCurrentIndex(idx)
        self._apply_tool_to_current_tab()  # 새 탭에 현재 도구 반영
        self.annotation_toolbar.set_zoom_label(tab.canvas.current_zoom())

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

        # 이미 저장되어 있고 변경도 없으면 무시 (no-op)
        if tab.is_saved() and tab.undo_stack.isClean():
            return

        # 이미 저장된 적 있으면 같은 경로에 덮어쓰기
        if tab.is_saved():
            path = tab.saved_path()
            try:
                save_png(tab.image(), path)
                tab.mark_saved(path)
                show_toast(self, f"저장됨: {path.name}", 1500)
            except IOError as e:
                QMessageBox.warning(self, "저장 실패", str(e))
            return

        # 최초 저장 — Phase 1 로직 그대로
        if self._settings.screenshot.save_dir == "":
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
        self._act_save.setToolTip("저장 (Ctrl+S) — 같은 파일에 덮어쓰기")
        self._act_save.triggered.connect(self.save_current_tab)
        tb.addAction(self._act_save)

        self._act_save_as = QAction("다른 이름으로", self)
        self._act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_save_as.setToolTip("다른 이름으로 저장 (Ctrl+Shift+S)")
        self._act_save_as.triggered.connect(self.save_current_tab_as)
        tb.addAction(self._act_save_as)

        self._act_copy = QAction("복사", self)
        self._act_copy.setShortcut(QKeySequence("Ctrl+C"))
        self._act_copy.setToolTip("이미지 클립보드 복사 (Ctrl+C) — 다른 앱에 Ctrl+V 로 붙여넣기")
        self._act_copy.triggered.connect(self.copy_current_to_clipboard)
        tb.addAction(self._act_copy)

    def _refresh_tab_title_for(self, tab: ScreenshotTab) -> None:
        idx = self._tabs.indexOf(tab)
        if idx < 0:
            return
        label = tab.source_label()
        base = f"{label} {idx + 1}"
        title = base if not tab.needs_save() else f"● {base}"
        self._tabs.setTabText(idx, title)

    def _unsaved_count(self) -> int:
        return sum(
            1 for i in range(self._tabs.count())
            if isinstance(self._tabs.widget(i), ScreenshotTab)
            and self._tabs.widget(i).needs_save()
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
        # Windows: OS 기본 타이틀바를 다크 모드로 (DwmSetWindowAttribute,
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20). Windows 11 / 최신 10 에서 동작.
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                value = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
                )
            except Exception:
                pass

    def createPopupMenu(self):
        # QMainWindow 기본 동작은 툴바 우클릭 시 "툴바 숨기기" 컨텍스트 메뉴를
        # 띄우는데, 두 툴바를 모두 숨기면 복구할 방법이 없어 의도적으로 차단.
        return None

    def _apply_tool_to_current_tab(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        tool_id = self.annotation_toolbar.current_tool_id()
        color = self.annotation_toolbar.current_color()
        th = self.annotation_toolbar.current_thickness_step()
        stack = tab.undo_stack
        if tool_id == "select":
            tab.canvas.set_tool(SelectTool())
        elif tool_id == "rect":
            tab.canvas.set_tool(RectTool(color, th, tab.canvas.shift_held, stack))
        elif tool_id == "arrow":
            tab.canvas.set_tool(ArrowTool(color, th, tab.canvas.shift_held, stack))
        elif tool_id == "text":
            # 텍스트 한 개 완성되면(ESC 또는 박스 외 클릭) 자동으로 선택 도구로 복귀.
            tab.canvas.set_tool(TextTool(color, stack, on_commit=self._after_text_commit))

        # Undo/Redo 버튼 활성 상태
        self.annotation_toolbar.set_undo_enabled(tab.undo_stack.canUndo())
        self.annotation_toolbar.set_redo_enabled(tab.undo_stack.canRedo())

    def _on_tool_changed(self, tool_id: str) -> None:
        self._apply_tool_to_current_tab()

    def _on_color_changed(self, color: QColor) -> None:
        self._settings.annotation.last_color = color.name()  # "#RRGGBB"
        self._apply_tool_to_current_tab()

    def _on_thickness_changed(self, step: int) -> None:
        self._settings.annotation.last_thickness = step
        self._apply_tool_to_current_tab()

    def _on_undo(self) -> None:
        tab = self.current_tab()
        if tab and tab.undo_stack.canUndo():
            tab.undo_stack.undo()
            self._apply_tool_to_current_tab()  # 버튼 활성 상태 갱신

    def _on_redo(self) -> None:
        tab = self.current_tab()
        if tab and tab.undo_stack.canRedo():
            tab.undo_stack.redo()
            self._apply_tool_to_current_tab()

    def _on_original(self) -> None:
        tab = self.current_tab()
        if tab:
            tab.canvas.set_hundred_percent_mode()

    def _on_zoom_changed(self, factor: float) -> None:
        self.annotation_toolbar.set_zoom_label(factor)

    def _on_current_tab_changed(self, idx: int) -> None:
        if idx >= 0:
            self._apply_tool_to_current_tab()
            tab = self.current_tab()
            if tab:
                self.annotation_toolbar.set_zoom_label(tab.canvas.current_zoom())

    def _after_text_commit(self) -> None:
        """텍스트 도구로 한 개 입력 완료 후 자동으로 선택 도구로 복귀."""
        self.annotation_toolbar.set_current_tool("select")
