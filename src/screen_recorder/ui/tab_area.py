"""스크린샷·영상 탭 통합 위젯. 모드에 따라 탭 스트립을 필터링."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QTabWidget, QWidget

from ..core.settings import PlayerSettings
from .mode_controller import AppMode, ModeController
from .edit_tab import EditTab
from .video_tab import VideoTab


class TabArea(QTabWidget):
    """탭 스트립과 캔버스/플레이어 영역을 묶은 위젯."""

    entry_closed = Signal(int)             # entry id (탭이 사용자에 의해 닫힐 때)
    snapshot_requested = Signal(QImage, str)   # 영상 탭의 프레임 스냅샷
    tab_added = Signal(QWidget, object)    # (widget, AppMode) — 외부에서 시그널 와이어링용

    def __init__(self, mode_controller: ModeController, player_settings: PlayerSettings) -> None:
        super().__init__()
        self._mode = mode_controller
        self._player_settings = player_settings
        self._tabs: list[tuple[QWidget, AppMode, int]] = []  # (widget, mode, entry_id)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self._on_close_requested)
        self.currentChanged.connect(self._on_current_changed)
        self._mode.mode_changed.connect(self._refresh_visibility)

    # ---------- 추가 ----------
    def add_screenshot(self, *, image: QImage, source_label: str, entry_id: int) -> int:
        tab = EditTab.from_screenshot(image, source_label=source_label)
        idx = self._add_tab(tab, AppMode.IMAGE, entry_id, label=f"📸 {source_label}")
        return idx

    def add_video(self, *, path: Path, source_label: str, duration_ms: int, entry_id: int) -> int:
        tab = VideoTab(path=path, source_label=source_label,
                       duration_ms=duration_ms, player_settings=self._player_settings)
        tab.snapshot_requested.connect(self.snapshot_requested.emit)
        idx = self._add_tab(tab, AppMode.VIDEO, entry_id,
                            label=f"🎞 {source_label} ({duration_ms // 1000}s)")
        return idx

    def _add_tab(self, widget: QWidget, mode: AppMode, entry_id: int, *, label: str) -> int:
        idx = self.addTab(widget, label)
        self._tabs.append((widget, mode, entry_id))
        self.setCurrentIndex(idx)
        self.tab_added.emit(widget, mode)
        # 새 탭 추가는 모드 자동 전환을 트리거
        self._mode.set_mode(mode)
        return idx

    # ---------- 조회 ----------
    def count_visible(self) -> int:
        n = 0
        for i in range(self.count()):
            if not self.isTabVisible(i):
                continue
            n += 1
        return n

    def current_entry_id(self) -> Optional[int]:
        idx = self.currentIndex()
        if idx < 0 or idx >= len(self._tabs):
            return None
        return self._tabs[idx][2]

    def find_index_by_entry(self, entry_id: int) -> int:
        for i, (_, _, eid) in enumerate(self._tabs):
            if eid == entry_id:
                return i
        return -1

    def tab_widget_for_entry(self, entry_id: int) -> Optional[QWidget]:
        i = self.find_index_by_entry(entry_id)
        if i < 0:
            return None
        return self._tabs[i][0]

    # ---------- 포커스 / 모드 ----------
    def focus_entry(self, entry_id: int) -> None:
        i = self.find_index_by_entry(entry_id)
        if i < 0:
            return
        self.setCurrentIndex(i)

    def _refresh_visibility(self, mode: AppMode) -> None:
        for i, (_, m, _) in enumerate(self._tabs):
            self.setTabVisible(i, m is mode)
        # 현재 탭이 숨겨졌다면 보이는 첫 탭으로 이동
        cur_idx = self.currentIndex()
        if cur_idx >= 0 and not self.isTabVisible(cur_idx):
            for i in range(self.count()):
                if self.isTabVisible(i):
                    self.setCurrentIndex(i)
                    return
            # 그 모드의 탭이 하나도 없음 — 위젯 본문도 직접 숨김
            # (setTabVisible 은 탭 헤더만 숨기고 currentWidget 은 그대로 보이는 Qt 동작)
            cur_w = self.widget(cur_idx)
            if cur_w is not None:
                cur_w.hide()

    def _on_current_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._tabs):
            return
        _, mode, _ = self._tabs[idx]
        self._mode.set_mode(mode)

    def _on_close_requested(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._tabs):
            return
        widget, _, eid = self._tabs[idx]
        self.removeTab(idx)
        del self._tabs[idx]
        widget.deleteLater()
        self.entry_closed.emit(eid)
