"""글로벌 툴바 — 모드 토글 + 모드별 액션 (영상: 녹화 / 이미지: 캡처·저장·복사)."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QComboBox, QFrame, QLabel, QButtonGroup,
    QKeySequenceEdit,
)

from ..core.state import RecorderState
from .drag_save_button import DragSaveButton
from .mode_controller import AppMode
from .overlay.monitor_identifier import MonitorIdentifier
from .widgets import OneShotKeySequenceEdit


class _MonitorComboBox(QComboBox):
    """드롭다운을 열면 각 모니터 중앙에 큰 번호를 띄우는 콤보박스.

    Windows 의 "디스플레이 설정 → 식별" 처럼 어느 쪽이 몇 번 모니터인지 시각적으로
    알려준다. 모니터가 2 개 이상일 때만 띄움 (1 개면 불필요).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._identifiers: list[MonitorIdentifier] = []

    def showPopup(self) -> None:
        screens = QGuiApplication.screens()
        if len(screens) >= 2:
            for ident in self._identifiers:
                ident.close()
            self._identifiers = [
                MonitorIdentifier(s, i + 1) for i, s in enumerate(screens)
            ]
            for ident in self._identifiers:
                ident.show()
                ident.raise_()
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        # hidePopup 직후엔 사용자가 모니터를 잘 보고 골랐는지 확인할 시간이 필요 없음 —
        # 메뉴가 닫히는 순간 오버레이도 닫는다.
        self._close_identifiers()

    def _close_identifiers(self) -> None:
        for ident in self._identifiers:
            ident.close()
        self._identifiers.clear()


# 사용자 선호 순서: 지정 영역 → 특정 창 → 전체 화면 (모니터 선택은 전체화면 옆에 짝지음).
_TARGETS = [("region", "▭ 지정 영역"), ("window", "🪟 특정 창"), ("fullscreen", "🖥 전체화면")]
_FORMATS = [("video", "영상"), ("gif", "GIF")]


class GlobalToolbar(QWidget):
    # 모드
    mode_clicked = Signal(object)  # AppMode

    # 녹화
    record_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    capture_region_clicked = Signal()
    capture_full_clicked = Signal()

    # 옵션
    target_changed = Signal(str)
    monitor_changed = Signal(int)
    mode_value_changed = Signal(str)  # "video"/"gif" — 녹화 출력 형식
    # 인라인 단축키 편집 — (HotkeySettings 의 필드명, 새 키 시퀀스 텍스트).
    # 모드별로 한 항목씩 노출됨: VIDEO=toggle_record, IMAGE=screenshot_region.
    hotkey_changed = Signal(str, str)

    # 액션
    save_clicked = Signal()
    copy_clicked = Signal()
    preferences_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("GlobalToolbar")
        # key → QAction 등록부 (find_action 으로 외부에서 시그널 연결).
        self._actions_by_key: dict[str, QAction] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # ---------- 모드 토글 (양쪽 공통) ----------
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self.video_btn = self._make_toggle_btn("🎞 영상", min_width=80)
        self.image_btn = self._make_toggle_btn("🖼 이미지", min_width=80)
        self._mode_group.addButton(self.video_btn)
        self._mode_group.addButton(self.image_btn)
        self.video_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.VIDEO))
        self.image_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.IMAGE))
        layout.addWidget(self.video_btn)
        layout.addWidget(self.image_btn)
        self._sep1 = self._make_sep()
        layout.addWidget(self._sep1)

        # ---------- 영상 모드: 녹화 컨트롤 ----------
        self.record_btn = QPushButton("▶ 녹화")
        self.record_btn.clicked.connect(self.record_clicked.emit)
        layout.addWidget(self.record_btn)

        self.pause_btn = QPushButton("⏸ 일시정지")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("⏹ 정지")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_btn)

        # ---------- 이미지 모드: 캡처 버튼 ----------
        self.capture_region_btn = QPushButton("📷 영역 캡처")
        self.capture_region_btn.clicked.connect(self.capture_region_clicked.emit)
        layout.addWidget(self.capture_region_btn)

        self.capture_full_btn = QPushButton("📷⛶ 전체 캡처")
        self.capture_full_btn.clicked.connect(self.capture_full_clicked.emit)
        layout.addWidget(self.capture_full_btn)

        self._sep2 = self._make_sep()
        layout.addWidget(self._sep2)

        # ---------- 영상 모드: 대상 토글 (전체화면/특정 창/지정 영역) ----------
        self._target_group = QButtonGroup(self)
        self._target_group.setExclusive(True)
        self._target_btns: dict[str, QPushButton] = {}
        for key, label in _TARGETS:
            btn = self._make_toggle_btn(label, min_width=70)
            self._target_btns[key] = btn
            self._target_group.addButton(btn)
            btn.clicked.connect(lambda _chk=False, k=key: self._on_target_btn_clicked(k))
            layout.addWidget(btn)
        # 기본 대상
        self._current_target_key = "fullscreen"
        self._target_btns["fullscreen"].setChecked(True)

        # ---------- 모니터 콤보 (전체화면 전용) — 전체화면 버튼 바로 옆 ----------
        self._monitor_label = QLabel(" 🖥")
        self._monitor_label.setToolTip("전체화면 캡처/녹화 시 사용할 모니터 — 전체 모니터 또는 1개 선택")
        layout.addWidget(self._monitor_label)
        self.monitor_combo = _MonitorComboBox()
        self.monitor_combo.setToolTip("전체화면용 모니터 선택")
        self._refresh_monitors()
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_combo_changed)
        layout.addWidget(self.monitor_combo)

        # ---------- 모니터 콤보 옆 인라인 단축키 편집 ----------
        # 영상 모드는 "영역 녹화" (toggle_record), 이미지 모드는 "영역 스크린샷"
        # (screenshot_region) — 둘 다 "Ctrl+Shift+T / R" 처럼 자주 바뀌지 않는
        # 핵심 단축키라 모니터 옆에서 즉시 확인/수정할 수 있게 노출.
        self._video_hotkey_label = QLabel(" 영역 녹화")
        self._video_hotkey_label.setStyleSheet("color: #999;")
        layout.addWidget(self._video_hotkey_label)
        self.video_hotkey_edit = OneShotKeySequenceEdit()
        self.video_hotkey_edit.setMaximumWidth(110)
        self.video_hotkey_edit.setToolTip("영역 녹화 단축키 (3-state 무장→시작→정지)")
        self.video_hotkey_edit.editingFinished.connect(
            lambda: self._on_inline_hotkey_done("toggle_record", self.video_hotkey_edit)
        )
        layout.addWidget(self.video_hotkey_edit)

        self._image_hotkey_label = QLabel(" 영역 스크린샷")
        self._image_hotkey_label.setStyleSheet("color: #999;")
        layout.addWidget(self._image_hotkey_label)
        self.image_hotkey_edit = OneShotKeySequenceEdit()
        self.image_hotkey_edit.setMaximumWidth(110)
        self.image_hotkey_edit.setToolTip("영역 스크린샷 단축키")
        self.image_hotkey_edit.editingFinished.connect(
            lambda: self._on_inline_hotkey_done("screenshot_region", self.image_hotkey_edit)
        )
        layout.addWidget(self.image_hotkey_edit)

        self._sep4 = self._make_sep()
        layout.addWidget(self._sep4)

        # ---------- 영상 모드: 녹화 형식 토글 (영상/GIF) ----------
        self._format_group = QButtonGroup(self)
        self._format_group.setExclusive(True)
        self._format_btns: dict[str, QPushButton] = {}
        for key, label in _FORMATS:
            btn = self._make_toggle_btn(label, min_width=56)
            self._format_btns[key] = btn
            self._format_group.addButton(btn)
            btn.clicked.connect(lambda _chk=False, k=key: self._on_format_btn_clicked(k))
            layout.addWidget(btn)
        self._current_format_key = "video"
        self._format_btns["video"].setChecked(True)

        layout.addStretch(1)

        # ---------- 이미지 모드: 글로벌 액션 ----------
        # 드래그-저장 버튼 (저장 버튼 왼쪽) — 폴더에 드래그&드롭하면 PNG 저장.
        self.drag_save_btn = DragSaveButton()
        layout.addWidget(self.drag_save_btn)

        self.save_btn = QPushButton("💾 저장")
        self.save_btn.clicked.connect(self.save_clicked.emit)
        layout.addWidget(self.save_btn)

        self.copy_btn = QPushButton("📋 복사")
        self.copy_btn.clicked.connect(self.copy_clicked.emit)
        layout.addWidget(self.copy_btn)

        # 누끼 (배경 제거) 는 좌측 ToolPalette '✨ 자동 누끼' 와 메뉴 '이미지>배경 제거' 로 옮김.
        # 외부 (메뉴 등) 에서 trigger 할 수 있도록 QAction 만 유지 (UI 버튼은 제거).
        self._action_remove_bg = QAction("✨ 배경 제거", self)
        self._action_remove_bg.setToolTip("활성 ImageLayer 의 배경을 제거 (Ctrl+Shift+B)")
        self._actions_by_key["remove_bg"] = self._action_remove_bg

        # ---------- 양쪽 공통 ----------
        self.preferences_btn = QPushButton("⚙")
        self.preferences_btn.setFixedWidth(32)
        self.preferences_btn.setToolTip("환경설정 (Ctrl+,)")
        self.preferences_btn.clicked.connect(self.preferences_clicked.emit)
        layout.addWidget(self.preferences_btn)

        # 초기 상태
        self._current_mode: AppMode = AppMode.IMAGE
        self._current_state: RecorderState = RecorderState.IDLE
        self.set_mode(AppMode.IMAGE)
        self.set_recording_state(RecorderState.IDLE)

    # ---------- 외부 API ----------
    def find_action(self, key: str) -> QAction | None:
        """key → QAction 조회. 외부에서 trigger 시그널을 핸들러에 연결할 때 사용."""
        return self._actions_by_key.get(key)

    def set_mode(self, mode: AppMode) -> None:
        self._current_mode = mode
        if mode is AppMode.VIDEO:
            self.video_btn.setChecked(True)
        else:
            self.image_btn.setChecked(True)
        self._refresh_widgets_visibility()

    def set_recording_state(self, state: RecorderState) -> None:
        self._current_state = state
        self.pause_btn.setText("▶ 재개" if state == RecorderState.PAUSED else "⏸ 일시정지")
        # 녹화 중에는 옵션 잠금
        idle = state == RecorderState.IDLE
        for btn in self._target_btns.values():
            btn.setEnabled(idle)
        for btn in self._format_btns.values():
            btn.setEnabled(idle)
        self.monitor_combo.setEnabled(idle)
        self._refresh_widgets_visibility()

    def set_target(self, key: str) -> None:
        if key in self._target_btns and key != self._current_target_key:
            self._current_target_key = key
            self._target_btns[key].setChecked(True)

    def current_target(self) -> str:
        return self._current_target_key

    def set_recording_mode(self, key: str) -> None:
        if key in self._format_btns and key != self._current_format_key:
            self._current_format_key = key
            self._format_btns[key].setChecked(True)

    def current_recording_mode(self) -> str:
        return self._current_format_key

    def set_monitor_index(self, idx: int) -> None:
        """idx 는 모니터 번호 (-1 = 전체 모니터). 콤보 항목과 매칭되는 것을 선택."""
        for i in range(self.monitor_combo.count()):
            if self.monitor_combo.itemData(i) == idx:
                self.monitor_combo.setCurrentIndex(i)
                return

    def current_monitor_index(self) -> int:
        """현재 선택된 모니터 (-1 = 전체 모니터)."""
        data = self.monitor_combo.currentData()
        return int(data) if data is not None else -1

    def set_inline_hotkey(self, key: str, sequence_text: str) -> None:
        """외부에서 인라인 단축키 표시값 동기화 (환경설정 다이얼로그에서 바뀌었을 때 등)."""
        editor = (self.video_hotkey_edit if key == "toggle_record"
                  else self.image_hotkey_edit if key == "screenshot_region"
                  else None)
        if editor is None:
            return
        editor.blockSignals(True)
        editor.setKeySequence(QKeySequence(sequence_text))
        editor.blockSignals(False)

    # ---------- 가시성 통합 관리 ----------
    def _refresh_widgets_visibility(self) -> None:
        is_video = self._current_mode is AppMode.VIDEO
        is_image = not is_video
        state = self._current_state
        idle = state == RecorderState.IDLE
        active = state in (RecorderState.RECORDING, RecorderState.PAUSED)

        # 영상 모드 전용 — 녹화 컨트롤
        self.record_btn.setVisible(is_video and idle)
        self.pause_btn.setVisible(is_video and active)
        self.stop_btn.setVisible(is_video and active)

        # 영상 모드 전용 — 대상 토글, 형식 토글
        for btn in self._target_btns.values():
            btn.setVisible(is_video)
        for btn in self._format_btns.values():
            btn.setVisible(is_video)
        # 모니터 선택은 양쪽 모드에서 모두 의미 있음 (영상=전체화면 녹화 대상,
        # 이미지=전체 캡처 대상). 항상 표시.
        self._monitor_label.setVisible(True)
        self.monitor_combo.setVisible(True)

        # 인라인 단축키 — 모드별로 한 쌍만 노출.
        self._video_hotkey_label.setVisible(is_video)
        self.video_hotkey_edit.setVisible(is_video)
        self._image_hotkey_label.setVisible(is_image)
        self.image_hotkey_edit.setVisible(is_image)

        # 이미지 모드 전용 — 캡처 + 액션
        self.capture_region_btn.setVisible(is_image)
        self.capture_full_btn.setVisible(is_image)
        self.save_btn.setVisible(is_image)
        self.copy_btn.setVisible(is_image)
        self.drag_save_btn.setVisible(is_image)

        # 분리자: 영상 모드에서만 의미 있는 것들 (sep3 는 모니터 콤보 합치며 제거)
        self._sep2.setVisible(is_video)
        self._sep4.setVisible(is_video)

    # ---------- 내부 ----------
    def _make_toggle_btn(self, text: str, *, min_width: int) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setMinimumWidth(min_width)
        return b

    def _make_sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setFixedWidth(2)
        f.setStyleSheet(
            "QFrame { background-color: #4A5060; border: none; "
            "margin-left: 6px; margin-right: 6px; }"
        )
        return f

    def _refresh_monitors(self) -> None:
        screens = QGuiApplication.screens() or []
        self.monitor_combo.clear()
        # 첫 항목 = "전체 모니터" (가상 데스크톱 전체) — userData -1
        self.monitor_combo.addItem("전체 모니터", -1)
        for i, s in enumerate(screens):
            g = s.geometry()
            self.monitor_combo.addItem(f"{i + 1}: {g.width()}×{g.height()}", i)
        if not screens:
            self.monitor_combo.addItem("1", 0)

    def _on_monitor_combo_changed(self, idx: int) -> None:
        # 콤보의 itemData 가 실제 모니터 인덱스 (-1 = 전체 모니터).
        data = self.monitor_combo.itemData(idx)
        if data is None:
            return
        self.monitor_changed.emit(int(data))

    def selected_monitor_index(self) -> int:
        """현재 선택된 모니터 인덱스 (-1 = 전체 모니터)."""
        data = self.monitor_combo.currentData()
        return int(data) if data is not None else -1

    def _on_target_btn_clicked(self, key: str) -> None:
        if key == self._current_target_key:
            return
        self._current_target_key = key
        self.target_changed.emit(key)

    def _on_format_btn_clicked(self, key: str) -> None:
        if key == self._current_format_key:
            return
        self._current_format_key = key
        self.mode_value_changed.emit(key)

    def _on_inline_hotkey_done(self, key: str, editor: QKeySequenceEdit) -> None:
        """QKeySequenceEdit.editingFinished 핸들러 — 사용자가 입력을 마쳤을 때만 emit.
        keySequenceChanged 는 키 입력 도중마다 발화돼 핫키 재등록이 너무 잦아짐."""
        text = editor.keySequence().toString(QKeySequence.PortableText)
        self.hotkey_changed.emit(key, text)
