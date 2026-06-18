"""글로벌 툴바 — 모드 토글 + 모드별 액션 (영상: 녹화 / 이미지: 캡처·저장·복사)."""
from __future__ import annotations

from PySide6.QtCore import QSize, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QComboBox, QFrame, QLabel, QButtonGroup,
    QCheckBox, QKeySequenceEdit,
)

from ..core.i18n import tr
from ..core.state import RecorderState
from .drag_save_button import DragSaveButton
from .icons import load_icon
from .mode_controller import AppMode
from .overlay.monitor_identifier import MonitorIdentifier
from .widgets import OneShotKeySequenceEdit


_TB_ICON_PX = 16

_MB = 1024 * 1024
_GB = 1024 * 1024 * 1024


def _fmt_size(num_bytes: int) -> str:
    """바이트를 사람 읽기 좋은 형식으로 — 1GB 이상은 'X.XG', 그 아래는 'XMB'."""
    if num_bytes >= _GB:
        return f"{num_bytes / _GB:.1f}G"
    if num_bytes >= _MB:
        return f"{int(num_bytes / _MB)}MB"
    return f"{num_bytes}B"


def _targets() -> list[tuple[str, str, str]]:
    """대상 토글 라벨 — (key, text, icon_name). tr() 가 부팅 시점 언어 기준이라
    함수로 감싸서 lazy 평가. 아이콘 명은 icons.py 의 _PATHS 키."""
    return [
        ("region", tr("지정 영역"), "square-dashed"),
        ("window", tr("특정 창"), "app-window"),
        ("fullscreen", tr("전체화면"), "monitor"),
    ]


def _formats() -> list[tuple[str, str]]:
    return [("video", tr("영상")), ("gif", tr("GIF"))]


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
    # 인라인 단축키 capture 시작/종료 — main_window 가 글로벌 Win32 핫키를 일시
    # 해제(unregister) → 사용자가 기존 단축키와 같은 조합을 누를 때 그 액션이
    # 발화되지 않도록 함.
    hotkey_editing_started = Signal()
    hotkey_editing_finished = Signal()

    # 액션
    save_clicked = Signal()
    copy_clicked = Signal()
    preferences_clicked = Signal()
    export_video_requested = Signal()   # 영상 내보내기 (영상 모드 전용)
    keep_visible_during_capture_changed = Signal(bool)   # 캡처 중 KStudio UI 보이기 토글

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
        self.video_btn = self._make_toggle_btn(tr("영상"), min_width=80, icon_name="film")
        self.image_btn = self._make_toggle_btn(tr("이미지"), min_width=80, icon_name="image")
        self.document_btn = self._make_toggle_btn(tr("문서"), min_width=80, icon_name="type")
        self._mode_group.addButton(self.video_btn)
        self._mode_group.addButton(self.image_btn)
        self._mode_group.addButton(self.document_btn)
        self.video_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.VIDEO))
        self.image_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.IMAGE))
        self.document_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.DOCUMENT))
        layout.addWidget(self.video_btn)
        layout.addWidget(self.image_btn)
        layout.addWidget(self.document_btn)
        self._sep1 = self._make_sep()
        layout.addWidget(self._sep1)

        # ---------- 영상 모드: 녹화 컨트롤 ----------
        self.record_btn = QPushButton(tr("녹화"))
        self.record_btn.setIcon(load_icon("play", size=_TB_ICON_PX))
        self.record_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.record_btn.clicked.connect(self.record_clicked.emit)
        layout.addWidget(self.record_btn)

        self.pause_btn = QPushButton(tr("일시정지"))
        self.pause_btn.setIcon(load_icon("pause", size=_TB_ICON_PX))
        self.pause_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton(tr("정지"))
        self.stop_btn.setIcon(load_icon("square", size=_TB_ICON_PX))
        self.stop_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_btn)

        # ---------- 영상 모드: 내보내기 버튼 ----------
        self.export_video_btn = QPushButton(tr("내보내기"))
        self.export_video_btn.setIcon(load_icon("upload", size=_TB_ICON_PX))
        self.export_video_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.export_video_btn.setToolTip(tr("현재 영상 탭을 새 MP4 로 내보내기 (Ctrl+Shift+E)"))
        self.export_video_btn.clicked.connect(self.export_video_requested.emit)
        layout.addWidget(self.export_video_btn)

        # ---------- 이미지 모드: 캡처 버튼 ----------
        self.capture_region_btn = QPushButton(tr("영역 캡처"))
        self.capture_region_btn.setIcon(load_icon("camera", size=_TB_ICON_PX))
        self.capture_region_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.capture_region_btn.clicked.connect(self.capture_region_clicked.emit)
        layout.addWidget(self.capture_region_btn)

        self.capture_full_btn = QPushButton(tr("전체 캡처"))
        self.capture_full_btn.setIcon(load_icon("camera", size=_TB_ICON_PX))
        self.capture_full_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.capture_full_btn.clicked.connect(self.capture_full_clicked.emit)
        layout.addWidget(self.capture_full_btn)

        self._sep2 = self._make_sep()
        layout.addWidget(self._sep2)

        # ---------- 영상 모드: 대상 토글 (전체화면/특정 창/지정 영역) ----------
        self._target_group = QButtonGroup(self)
        self._target_group.setExclusive(True)
        self._target_btns: dict[str, QPushButton] = {}
        for key, label, icon_name in _targets():
            btn = self._make_toggle_btn(label, min_width=70, icon_name=icon_name)
            self._target_btns[key] = btn
            self._target_group.addButton(btn)
            btn.clicked.connect(lambda _chk=False, k=key: self._on_target_btn_clicked(k))
            layout.addWidget(btn)
        # 기본 대상
        self._current_target_key = "fullscreen"
        self._target_btns["fullscreen"].setChecked(True)

        # ---------- 모니터 콤보 (전체화면 전용) — 전체화면 버튼 바로 옆 ----------
        # SVG 아이콘 라벨 — 텍스트 이모지(🖥) 대체. QLabel 에 QPixmap 으로 SVG 렌더.
        self._monitor_label = QLabel()
        self._monitor_label.setPixmap(
            load_icon("monitor", size=_TB_ICON_PX).pixmap(_TB_ICON_PX, _TB_ICON_PX)
        )
        self._monitor_label.setContentsMargins(4, 0, 0, 0)
        self._monitor_label.setToolTip(tr("전체화면 캡처/녹화 시 사용할 모니터 — 전체 모니터 또는 1개 선택"))
        layout.addWidget(self._monitor_label)
        self.monitor_combo = _MonitorComboBox()
        self.monitor_combo.setToolTip(tr("전체화면용 모니터 선택"))
        self._refresh_monitors()
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_combo_changed)
        layout.addWidget(self.monitor_combo)

        # ---------- 모니터 콤보 옆 인라인 단축키 편집 ----------
        # 영상 모드는 "영역 녹화" (toggle_record), 이미지 모드는 "영역 스크린샷"
        # (screenshot_region) — 둘 다 "Ctrl+Shift+T / R" 처럼 자주 바뀌지 않는
        # 핵심 단축키라 모니터 옆에서 즉시 확인/수정할 수 있게 노출.
        self._video_hotkey_label = QLabel(" " + tr("영역 녹화"))
        self._video_hotkey_label.setStyleSheet("color: #999;")
        layout.addWidget(self._video_hotkey_label)
        self.video_hotkey_edit = OneShotKeySequenceEdit()
        self.video_hotkey_edit.setMaximumWidth(110)
        self.video_hotkey_edit.setToolTip(tr("영역 녹화 단축키 (3-state 무장→시작→정지)"))
        self.video_hotkey_edit.editingFinished.connect(
            lambda: self._on_inline_hotkey_done("toggle_record", self.video_hotkey_edit)
        )
        self.video_hotkey_edit.editing_started.connect(self.hotkey_editing_started.emit)
        self.video_hotkey_edit.editing_finished_signal.connect(self.hotkey_editing_finished.emit)
        layout.addWidget(self.video_hotkey_edit)

        self._image_hotkey_label = QLabel(" " + tr("영역 스크린샷"))
        self._image_hotkey_label.setStyleSheet("color: #999;")
        layout.addWidget(self._image_hotkey_label)
        self.image_hotkey_edit = OneShotKeySequenceEdit()
        self.image_hotkey_edit.setMaximumWidth(110)
        self.image_hotkey_edit.setToolTip(tr("영역 스크린샷 단축키"))
        self.image_hotkey_edit.editingFinished.connect(
            lambda: self._on_inline_hotkey_done("screenshot_region", self.image_hotkey_edit)
        )
        self.image_hotkey_edit.editing_started.connect(self.hotkey_editing_started.emit)
        self.image_hotkey_edit.editing_finished_signal.connect(self.hotkey_editing_finished.emit)
        layout.addWidget(self.image_hotkey_edit)

        self._sep4 = self._make_sep()
        layout.addWidget(self._sep4)

        # ---------- 영상 모드: 녹화 형식 토글 (영상/GIF) ----------
        self._format_group = QButtonGroup(self)
        self._format_group.setExclusive(True)
        self._format_btns: dict[str, QPushButton] = {}
        for key, label in _formats():
            btn = self._make_toggle_btn(label, min_width=56)
            self._format_btns[key] = btn
            self._format_group.addButton(btn)
            btn.clicked.connect(lambda _chk=False, k=key: self._on_format_btn_clicked(k))
            layout.addWidget(btn)
        self._current_format_key = "video"
        self._format_btns["video"].setChecked(True)

        # KStudio UI 자체를 캡쳐에 포함시킬지 토글 — 영상/GIF 버튼 오른쪽.
        # 켜면 녹화 / 스크린샷 시 메인 창이 가려지지 않고 affinity 도 풀려 결과에 정상 포함.
        self.keep_visible_chk = QCheckBox(tr("내 화면에 보이기"))
        self.keep_visible_chk.setToolTip(tr(
            "켜면 녹화·스크린샷 중에도 KStudio UI 가 가려지지 않고 결과에 정상 포함됩니다.\n"
            "(꺼져 있으면 KStudio 는 자동으로 숨겨지거나 캡쳐에서 제외됩니다.)"
        ))
        self.keep_visible_chk.toggled.connect(
            self.keep_visible_during_capture_changed.emit
        )
        layout.addWidget(self.keep_visible_chk)

        layout.addStretch(1)

        # ---------- 이미지 모드: 글로벌 액션 ----------
        # 드래그-저장 버튼 (저장 버튼 왼쪽) — 폴더에 드래그&드롭하면 PNG 저장.
        self.drag_save_btn = DragSaveButton()
        layout.addWidget(self.drag_save_btn)

        self.save_btn = QPushButton(tr("저장"))
        self.save_btn.setIcon(load_icon("save", size=_TB_ICON_PX))
        self.save_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.save_btn.clicked.connect(self.save_clicked.emit)
        layout.addWidget(self.save_btn)

        self.copy_btn = QPushButton(tr("복사"))
        self.copy_btn.setIcon(load_icon("copy", size=_TB_ICON_PX))
        self.copy_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.copy_btn.clicked.connect(self.copy_clicked.emit)
        layout.addWidget(self.copy_btn)

        # 누끼 (배경 제거) 는 좌측 ToolPalette '자동 누끼' 와 메뉴 '이미지>배경 제거' 로 옮김.
        # 외부 (메뉴 등) 에서 trigger 할 수 있도록 QAction 만 유지 (UI 버튼은 제거).
        self._action_remove_bg = QAction(tr("배경 제거"), self)
        self._action_remove_bg.setIcon(load_icon("sparkles", size=_TB_ICON_PX))
        self._action_remove_bg.setToolTip(tr("활성 ImageLayer 의 배경을 제거 (Ctrl+Shift+B)"))
        self._actions_by_key["remove_bg"] = self._action_remove_bg

        # ---------- 양쪽 공통 ----------
        # 유튜브 다운로드 트레이 버튼 — 설정 버튼 *왼쪽* (브라우저 다운로드 버튼처럼).
        # 다운로드가 생기면 나타나고, 클릭하면 아래로 진행 목록 팝업을 띄운다.
        from .youtube.downloads_button import DownloadsButton
        self.downloads_button = DownloadsButton()
        layout.addWidget(self.downloads_button)

        # 모델 다운로드 진행률 라벨 — 설정 버튼 *왼쪽*. 평소 숨김.
        # 사용자가 ModelDownloadWindow 를 닫아도 진행률을 잃지 않도록 — 백그라운드
        # snapshot_download 가 살아있는 동안 항상 보이는 영구 인디케이터.
        # MainWindow 가 ChatPanel.download_progress_changed 시그널을 받아 여기로
        # 전달 (set_download_progress / clear_download_progress).
        self.download_progress_label = QLabel("")
        self.download_progress_label.setStyleSheet(
            "color:#16a34a;font-size:11px;background:transparent;padding:0px 6px;"
        )
        self.download_progress_label.setVisible(False)
        layout.addWidget(self.download_progress_label)

        self.preferences_btn = QPushButton(tr("설정"))
        self.preferences_btn.setIcon(load_icon("settings", size=_TB_ICON_PX))
        self.preferences_btn.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
        self.preferences_btn.setToolTip(tr("환경설정 (Ctrl+,)"))
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
        elif mode is AppMode.DOCUMENT:
            self.document_btn.setChecked(True)
        else:
            self.image_btn.setChecked(True)
        self._refresh_widgets_visibility()

    def set_recording_state(self, state: RecorderState) -> None:
        self._current_state = state
        if state == RecorderState.PAUSED:
            self.pause_btn.setText(tr("재개"))
            self.pause_btn.setIcon(load_icon("play", size=_TB_ICON_PX))
        else:
            self.pause_btn.setText(tr("일시정지"))
            self.pause_btn.setIcon(load_icon("pause", size=_TB_ICON_PX))
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

    # ---------- 다운로드 진행률 (설정 버튼 왼쪽 라벨) ----------
    def set_download_progress(
        self,
        received_bytes: int,
        total_bytes: int,
        model_name: str,
    ) -> None:
        """다운로드 중인 모델의 진행률 표시. ChatPanel 의 download_progress_changed
        시그널을 MainWindow 가 받아 여기로 위임. 사용자가 ModelDownloadWindow 를
        닫아도 진행률 잃지 않게 영구 인디케이터.

        total_bytes=0 (예상 크기 미정) 면 받은 양만 표시 + percent 생략.
        """
        if total_bytes > 0:
            pct = int(received_bytes / total_bytes * 100)
            pct = max(0, min(100, pct))
            text = (
                f"{pct}% ({_fmt_size(received_bytes)}/{_fmt_size(total_bytes)})"
            )
        else:
            text = f"{_fmt_size(received_bytes)} 다운로드 중"
        self.download_progress_label.setText(text)
        self.download_progress_label.setToolTip(f"{model_name} 다운로드 중")
        self.download_progress_label.setVisible(True)

    def clear_download_progress(self) -> None:
        """다운로드 완료 또는 에러 시 — 라벨 숨김."""
        self.download_progress_label.setVisible(False)
        self.download_progress_label.setText("")
        self.download_progress_label.setToolTip("")

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
        # 문서(DOCUMENT) 모드 추가 후로는 "non-video == image" 가정이 깨지므로
        # 모드를 명시적으로 구분한다. 문서 모드에선 녹화·캡처 chrome 을 모두 숨긴다.
        is_video = self._current_mode is AppMode.VIDEO
        is_image = self._current_mode is AppMode.IMAGE
        is_document = self._current_mode is AppMode.DOCUMENT
        state = self._current_state
        idle = state == RecorderState.IDLE
        active = state in (RecorderState.RECORDING, RecorderState.PAUSED)

        # 영상 모드 전용 — 녹화 컨트롤
        self.record_btn.setVisible(is_video and idle)
        self.pause_btn.setVisible(is_video and active)
        self.stop_btn.setVisible(is_video and active)
        self.export_video_btn.setVisible(is_video)

        # 영상 모드 전용 — 대상 토글, 형식 토글
        for btn in self._target_btns.values():
            btn.setVisible(is_video)
        for btn in self._format_btns.values():
            btn.setVisible(is_video)
        # 모니터 선택은 영상/이미지 모드에서 의미 있음 (영상=전체화면 녹화 대상,
        # 이미지=전체 캡처 대상). 문서 모드에선 무의미하므로 숨김.
        self._monitor_label.setVisible(not is_document)
        self.monitor_combo.setVisible(not is_document)

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
    def _make_toggle_btn(self, text: str, *, min_width: int, icon_name: str | None = None) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setMinimumWidth(min_width)
        if icon_name is not None:
            b.setIcon(load_icon(icon_name, size=_TB_ICON_PX))
            b.setIconSize(QSize(_TB_ICON_PX, _TB_ICON_PX))
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
        self.monitor_combo.addItem(tr("전체 모니터"), -1)
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
