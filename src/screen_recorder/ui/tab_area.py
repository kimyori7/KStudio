"""스크린샷·영상 탭 통합 위젯. 모드에 따라 탭 스트립을 필터링."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QTabBar, QTabWidget, QToolButton, QWidget

from ..core.settings import PlayerHotkeys, PlayerSettings
from .mode_controller import AppMode, ModeController
from .edit_tab import EditTab
from .icons import load_icon
from .markdown_tab import MarkdownTab
from .video_tab import VideoTab
from .audio_tab import AudioTab


_SCROLL_BTN_PX = 32       # 스크롤 버튼 가로/세로
_SCROLL_ICON_PX = 20      # 그 안에 들어가는 chevron 아이콘 크기
_DELETED_TAB_COLOR = "#d08770"   # 취소선/dim 색 (외부 삭제된 파일)


class _StrikeThroughTabBar(QTabBar):
    """삭제된 파일 탭에 VSCode 식 취소선을 덧그린다.

    기본 paint 를 그대로 두고(close 버튼·이모지·스크롤 등 회귀 위험 0) 그 위에 가로선만
    오버레이한다. 어떤 탭이 삭제 상태인지는 부모 TabArea 의 `_is_tab_index_deleted` 가
    판단(위젯↔인덱스는 indexOf 로 안전 매핑)."""

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        ta = self.parent()
        is_deleted = getattr(ta, "_is_tab_index_deleted", None)
        if is_deleted is None:
            return
        painter = QPainter(self)
        pen = QPen(QColor(_DELETED_TAB_COLOR))
        pen.setWidth(1)
        painter.setPen(pen)
        for i in range(self.count()):
            if not self.isTabVisible(i) or not is_deleted(i):
                continue
            r = self.tabRect(i)
            if r.isNull():
                continue
            y = r.center().y()
            # 왼쪽 이모지(약 22px)·오른쪽 close 버튼(약 26px) 영역을 피해 텍스트 위만 긋는다.
            painter.drawLine(r.left() + 22, y, r.right() - 26, y)
        painter.end()


class TabArea(QTabWidget):
    """탭 스트립과 캔버스/플레이어 영역을 묶은 위젯."""

    entry_closed = Signal(int)             # entry id (탭이 사용자에 의해 닫힐 때)
    snapshot_requested = Signal(QImage, str)   # 영상 탭의 프레임 스냅샷
    tab_added = Signal(QWidget, object)    # (widget, AppMode) — 외부에서 시그널 와이어링용
    video_duration_resolved = Signal(int, int)   # (entry_id, duration_ms) — player 로드 후

    def __init__(self, mode_controller: ModeController, player_settings: PlayerSettings,
                 player_hotkeys: PlayerHotkeys | None = None,
                 sidecar_dir_provider=None) -> None:
        super().__init__()
        self._mode = mode_controller
        self._player_settings = player_settings
        self._player_hotkeys = player_hotkeys or PlayerHotkeys()
        # 사용자 설정의 사이드카 폴더를 동적으로 읽기 위한 콜백 — settings 변경 시 다음
        # 새 영상 탭부터 즉시 반영. None 이면 VideoTab 이 default_sidecar_dir 사용.
        self._sidecar_dir_provider = sidecar_dir_provider
        self._tabs: list[tuple[QWidget, AppMode, int]] = []  # (widget, mode, entry_id)
        # 모든 탭의 baseline 라벨 (파일명 등). 이미지 탭은 저장 상태 ● 마커가 동적으로
        # 붙고, 영상 탭은 duration 접미사가 붙어, 라벨 재계산이 필요해 베이스만 보관.
        self._tab_base_labels: dict[QWidget, str] = {}
        # 영상 탭의 duration 접미사 (예: " (3s)") — 베이스와 분리 보관.
        self._video_duration_suffix: dict[QWidget, str] = {}
        # 외부에서 파일이 삭제된 탭 — 취소선 표시 대상 (위젯 기준, 이동/제거에도 안전).
        self._deleted_widgets: set[QWidget] = set()
        self.setTabBar(_StrikeThroughTabBar(self))
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self._on_close_requested)
        self.currentChanged.connect(self._on_current_changed)
        self._mode.mode_changed.connect(self._refresh_visibility)
        # QTabBar 의 기본 스크롤 버튼은 16px 정도로 작고 아이콘이 거의 안 보임 →
        # lucide chevron 아이콘 + 32px 크기로 교체. Qt 가 버튼을 lazy 생성/숨김 하므로
        # 첫 노출 직전과 매 탭 추가 시점에 한 번씩 ensure 호출.
        self._customize_scroll_buttons()

    # ---------- 추가 ----------
    def add_screenshot(self, *, image: QImage, source_label: str, entry_id: int,
                        display_name: str | None = None) -> int:
        tab = EditTab.from_screenshot(image, source_label=source_label)
        # 탭 라벨 — 실제 파일명(display_name)이 있으면 그걸로, 없으면 source_label fallback.
        base = display_name if display_name else source_label
        self._tab_base_labels[tab] = base
        idx = self._add_tab(tab, AppMode.IMAGE, entry_id,
                            label=self._format_tab_label(tab))
        # 저장 상태가 바뀔 때마다 ● 마커 토글.
        tab.save_state_changed.connect(lambda t=tab: self._refresh_tab_label(t))
        return idx

    def add_image_tab(self, tab: EditTab, *, entry_id: int,
                       display_name: str | None = None,
                       label: str | None = None) -> int:
        """이미 구성된 EditTab 을 그대로 추가 (파일 열기 흐름).

        display_name 우선. 하위 호환을 위해 legacy `label` 도 받지만 이모지 prefix 만
        떼고 베이스로 사용. 가능하면 호출 측에서 display_name 을 명시.
        """
        if display_name:
            base = display_name
        elif label:
            base = label
            for prefix in ("📸 ", "📂 "):
                if base.startswith(prefix):
                    base = base[len(prefix):].strip()
                    break
        else:
            base = ""
        self._tab_base_labels[tab] = base
        idx = self._add_tab(tab, AppMode.IMAGE, entry_id,
                            label=self._format_tab_label(tab))
        tab.save_state_changed.connect(lambda t=tab: self._refresh_tab_label(t))
        return idx

    def add_markdown(self, tab: "MarkdownTab", *, entry_id: int,
                     display_name: str | None = None) -> int:
        base = display_name if display_name else "untitled.md"
        self._tab_base_labels[tab] = base
        idx = self._add_tab(tab, AppMode.DOCUMENT, entry_id,
                            label=self._format_tab_label(tab))
        tab.save_state_changed.connect(lambda t=tab: self._refresh_tab_label(t))
        return idx

    # ---------- 통합 탭 라벨 포맷 ----------
    def _format_tab_label(self, tab: QWidget) -> str:
        base = self._tab_base_labels.get(tab, "")
        if isinstance(tab, MarkdownTab):
            marker = " ●" if tab.needs_save() else ""
            return f"📄 {base}{marker}"
        if isinstance(tab, EditTab):
            # 미저장(또는 저장 후 변경됨) 이면 ● 마커.
            marker = " ●" if tab.needs_save() else ""
            return f"📸 {base}{marker}"
        if isinstance(tab, VideoTab):
            suffix = self._video_duration_suffix.get(tab, "")
            return f"🎞 {base}{suffix}"
        if isinstance(tab, AudioTab):
            return f"🎵 {base}"
        return base

    def _refresh_tab_label(self, tab: QWidget) -> None:
        idx = self.indexOf(tab)
        if idx < 0:
            return
        self.setTabText(idx, self._format_tab_label(tab))

    def set_entry_deleted(self, entry_id: int, deleted: bool = True) -> None:
        """엔트리의 파일이 외부에서 삭제됨(또는 복구됨)을 탭에 반영 — 취소선 + 글자 dim."""
        widget = self.tab_widget_for_entry(entry_id)
        if widget is None:
            return
        if deleted:
            self._deleted_widgets.add(widget)
        else:
            self._deleted_widgets.discard(widget)
        idx = self.indexOf(widget)
        if idx >= 0:
            # dim(삭제) / 기본색 복구. 빈 QColor() = 팔레트 기본색으로 리셋.
            self.tabBar().setTabTextColor(idx, QColor(_DELETED_TAB_COLOR) if deleted else QColor())
        self.tabBar().update()

    def _is_tab_index_deleted(self, idx: int) -> bool:
        """그 탭 인덱스가 삭제 상태인가 — 커스텀 tab bar 의 취소선 paint 가 호출."""
        for w in self._deleted_widgets:
            if self.indexOf(w) == idx:
                return True
        return False

    def update_tab_base(self, entry_id: int, new_base: str) -> None:
        """라이브러리 rename / Save As 로 파일명이 바뀌면 베이스 라벨도 갱신.
        이미지·영상 탭 모두 적용."""
        idx = self.find_index_by_entry(entry_id)
        if idx < 0:
            return
        widget = self._tabs[idx][0]
        if widget not in self._tab_base_labels:
            return
        self._tab_base_labels[widget] = new_base
        self._refresh_tab_label(widget)

    def add_video(self, *, path: Path, source_label: str, duration_ms: int, entry_id: int,
                   display_name: str | None = None,
                   thumbnail: Optional[QImage] = None,
                   sidecar_dir: "Path | None" = None,
                   sidecar_path: "Path | None" = None,
                   project_path: "Path | None" = None) -> int:
        # 명시 인자가 있으면 그것 우선 (사용자가 사이드카 파일 직접 열기), 없으면
        # provider 콜백 (환경설정 폴더).
        sc_dir = sidecar_dir
        if sc_dir is None and self._sidecar_dir_provider is not None:
            try:
                sc_dir = self._sidecar_dir_provider()
            except (RuntimeError, OSError):
                sc_dir = None
        tab = VideoTab(path=path, source_label=source_label,
                       duration_ms=duration_ms, player_settings=self._player_settings,
                       thumbnail=thumbnail, player_hotkeys=self._player_hotkeys,
                       sidecar_dir=sc_dir, sidecar_path=sidecar_path,
                       project_path=project_path)
        tab.snapshot_requested.connect(self.snapshot_requested.emit)
        # 탭 라벨 — 실제 파일명(display_name)이 있으면 그걸로, 없으면 source_label.
        base = display_name if display_name else source_label
        self._tab_base_labels[tab] = base
        # 탭 생성 시점엔 duration_ms 가 0 일 수 있음 (인코더가 막 끝낸 영상은 메타가 늦게
        # 채워짐). VideoTab.duration_resolved 가 player 로드 후 실제 길이를 알려주면
        # 탭 라벨을 다시 쓴다.
        self._video_duration_suffix[tab] = self._format_video_duration(duration_ms)
        idx = self._add_tab(tab, AppMode.VIDEO, entry_id,
                            label=self._format_tab_label(tab))
        tab.duration_resolved.connect(
            lambda ms, t=tab: self._on_video_duration_resolved(t, ms)
        )
        return idx

    def add_audio(self, *, path: Path, source_label: str, entry_id: int,
                  display_name: str | None = None,
                  sidecar_dir: "Path | None" = None,
                  sidecar_path: "Path | None" = None) -> int:
        """오디오 파일을 새 AudioTab 으로 추가. add_video 미러(영상 프레임 없음·전용 탭).

        오디오 탭도 AppMode.VIDEO 영역에 둔다(별도 모드 추가의 침습성 회피)."""
        sc_dir = sidecar_dir
        if sc_dir is None and self._sidecar_dir_provider is not None:
            try:
                sc_dir = self._sidecar_dir_provider()
            except (RuntimeError, OSError):
                sc_dir = None
        tab = AudioTab(path=path, player_settings=self._player_settings,
                       sidecar_dir=sc_dir, sidecar_path=sidecar_path)
        base = display_name if display_name else source_label
        self._tab_base_labels[tab] = base
        return self._add_tab(tab, AppMode.VIDEO, entry_id,
                             label=self._format_tab_label(tab))

    @staticmethod
    def _format_video_duration(ms: int) -> str:
        if ms <= 0:
            return ""
        s = ms // 1000
        if s < 60:
            return f" ({s}s)"
        return f" ({s // 60}m{s % 60:02d}s)"

    def _on_video_duration_resolved(self, tab: VideoTab, duration_ms: int) -> None:
        """player 가 영상 메타를 다 읽고 실제 duration 을 알려줬을 때 호출 — 탭 라벨 갱신 +
        뷰어가 보여주는 라이브러리 항목도 자체 시그널로 갱신되도록 외부에 알림."""
        idx = self.indexOf(tab)
        if idx < 0:
            return
        self._video_duration_suffix[tab] = self._format_video_duration(duration_ms)
        self._refresh_tab_label(tab)
        # entry_id 알아내서 외부 (main_window) 가 라이브러리 모델에 반영하도록
        eid = self._tabs[idx][2] if 0 <= idx < len(self._tabs) else None
        if eid is not None:
            self.video_duration_resolved.emit(int(eid), int(duration_ms))

    def _add_tab(self, widget: QWidget, mode: AppMode, entry_id: int, *, label: str) -> int:
        idx = self.addTab(widget, label)
        self._tabs.append((widget, mode, entry_id))
        self.setCurrentIndex(idx)
        self.tab_added.emit(widget, mode)
        # 새 탭 추가는 모드 자동 전환을 트리거
        self._mode.set_mode(mode)
        # 스크롤 버튼은 Qt 가 lazy 생성/표시 — 새 탭으로 overflow 가 막 일어나는
        # 시점에 처음 만들어질 수 있으니 매 추가 시 재커스터마이즈.
        self._customize_scroll_buttons()
        return idx

    # ---------- 스크롤 버튼 커스터마이즈 ----------
    def _customize_scroll_buttons(self) -> None:
        """QTabBar 의 기본 좌/우 스크롤 버튼을 lucide chevron 으로 교체 + 크게.

        Qt 의 QTabBar 는 overflow 시 두 개의 QToolButton 자식을 만들어 양쪽 끝에
        붙인다. 기본 크기가 16~20px 로 작고 아이콘이 거의 안 보여 사용성이 떨어짐.
        runtime 에 그 자식들을 찾아 SVG 아이콘 + 32px 로 교체. arrowType 을
        NoArrow 로 설정해야 Qt 의 기본 화살표 그리기가 비활성화돼 우리 아이콘이
        그대로 보임.
        """
        bar = self.tabBar()
        if bar is None:
            return
        for btn in bar.findChildren(QToolButton):
            arrow = btn.arrowType()
            if arrow == Qt.LeftArrow:
                icon_name = "chevron-left"
            elif arrow == Qt.RightArrow:
                icon_name = "chevron-right"
            else:
                continue  # 다른 QToolButton (탭 close 등) 은 건드리지 않음
            btn.setArrowType(Qt.NoArrow)
            btn.setIcon(load_icon(icon_name, size=_SCROLL_ICON_PX))
            btn.setIconSize(QSize(_SCROLL_ICON_PX, _SCROLL_ICON_PX))
            btn.setFixedSize(_SCROLL_BTN_PX, _SCROLL_BTN_PX)
            btn.setAutoRaise(True)  # 평소엔 평면, hover 시만 배경
            btn.setCursor(Qt.PointingHandCursor)

    # ---------- 조회 ----------
    def current_video_tab(self) -> Optional["VideoTab"]:
        """현재 활성 탭이 VideoTab 이면 반환, 아니면 None."""
        idx = self.currentIndex()
        if idx < 0 or idx >= len(self._tabs):
            return None
        widget, mode, _ = self._tabs[idx]
        if mode is AppMode.VIDEO and isinstance(widget, VideoTab):
            return widget
        return None

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

    def entry_id_for_widget(self, widget: QWidget) -> Optional[int]:
        for w, _, eid in self._tabs:
            if w is widget:
                return eid
        return None

    # ---------- 포커스 / 모드 ----------
    def focus_entry(self, entry_id: int) -> None:
        i = self.find_index_by_entry(entry_id)
        if i < 0:
            return
        self.setCurrentIndex(i)

    def _refresh_visibility(self, mode: AppMode) -> None:
        visible_indices: list[int] = []
        for i, (_, m, _) in enumerate(self._tabs):
            match = m is mode
            self.setTabVisible(i, match)
            if match:
                visible_indices.append(i)
        if visible_indices:
            # 현재 탭이 이 모드 소속이 아니면 보이는 첫 탭으로 이동 (Qt 가 본문 교체).
            if self.currentIndex() not in visible_indices:
                self.setCurrentIndex(visible_indices[0])
            return
        # 그 모드의 탭이 하나도 없음 — 본문이 비치지 않게 모든 탭 위젯을 직접 숨김.
        # (setTabVisible 은 탭 헤더만 숨기고 위젯 본문은 그대로 보임. 게다가 현재 탭이
        #  숨겨지면 Qt 가 currentIndex 를 -1 로 바꿔 기존 `cur_idx>=0` 가드가 빗나가
        #  직전 탭 본문(예: 문서 모드 md)이 다른 모드 화면에 그대로 노출됐음.)
        for i in range(self.count()):
            w = self.widget(i)
            if w is not None:
                w.hide()

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
        self._tab_base_labels.pop(widget, None)
        self._video_duration_suffix.pop(widget, None)
        self._deleted_widgets.discard(widget)
        # VideoTab 의 player 가 잡고 있는 QMediaPlayer/QMovie 핸들을 즉시 해제.
        # deleteLater 만으로는 closeEvent 가 발화하지 않아 Windows 가 "파일 사용 중"
        # 으로 파일을 계속 잠가둠 → 사용자가 라이브러리에서 곧장 Del 하면 send2trash
        # 실패. 여기서 명시 해제하면 X 로 닫고 나서 휴지통 이동도 깔끔히 성공.
        if isinstance(widget, VideoTab):
            try:
                # 닫기 전에 미반영 autosave 가 있으면 즉시 디스크에 flush — debounce
                # 타이머가 아직 안 fire 했을 때 데이터 손실 방지 (사용자 보고: "자르고
                # 닫았더니 자른건 그대로인데 나머지는 없어졌어").
                widget.edit_controller().flush_autosave()
            except (RuntimeError, AttributeError):
                pass
            try:
                widget.player.stop()
                widget.player.release_file_handles()
            except (RuntimeError, AttributeError):
                pass
        if isinstance(widget, MarkdownTab):
            # WebEngine page/profile/render-process 정리 (앱 누수 방지).
            try:
                widget.cleanup()
            except (RuntimeError, AttributeError):
                pass
        widget.deleteLater()
        self.entry_closed.emit(eid)
        # QTabWidget 은 탭 제거 후 currentIndex 를 자동 재설정하는데, 이 때 다른 모드의
        # (현재는 숨겨진) 탭 위젯으로 넘어갈 수 있다. 그러면 이미지 모드인데 영상 플레이어
        # 위젯이 중앙에 그대로 표시되는 현상 발생. 모드 visibility 를 재적용해 현재 모드
        # 의 보이는 탭으로 전환하거나, 없으면 위젯을 숨김.
        self._refresh_visibility(self._mode.mode())
