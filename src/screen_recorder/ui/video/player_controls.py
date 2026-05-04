"""곰/팟플레이어 스타일 영상 컨트롤 바."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from .trim_lane import TrimLane


_SPEEDS = [("0.5×", 0.5), ("1.0×", 1.0), ("1.5×", 1.5), ("2.0×", 2.0)]
_CUSTOM_SPEED_LABEL = "사용자 지정…"


def _bump_font_size(btn: QPushButton, points: int) -> None:
    """버튼 텍스트 폰트를 키운다 (이모지 아이콘 가독성용)."""
    f = btn.font()
    f.setPointSize(points)
    btn.setFont(f)


def _format_ms(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


class PlayerControls(QWidget):
    play_toggled = Signal()
    seek_request = Signal(int)        # ms
    volume_changed = Signal(float)    # 0..1
    mute_toggled = Signal()
    speed_changed = Signal(float)
    frame_step = Signal(int)          # -1 / +1
    snapshot_request = Signal()
    fullscreen_toggled = Signal()
    trim_execute_requested = Signal(int, int)   # (in_ms, out_ms)
    trim_cleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PlayerControls")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ===== 트림 row (in/out 점이 하나라도 찍히면 보임) =====
        self.trim_row = QFrame()
        self.trim_row.setObjectName("TrimRow")
        trim_v = QVBoxLayout(self.trim_row)
        trim_v.setContentsMargins(8, 4, 8, 4)
        trim_v.setSpacing(4)
        self.trim_lane = TrimLane()
        trim_v.addWidget(self.trim_lane)
        trim_btns = QHBoxLayout()
        trim_btns.setSpacing(8)
        self.cut_btn = QPushButton("✂ 자르기")
        self.cut_btn.setEnabled(False)
        self.cut_btn.clicked.connect(self._on_cut_clicked)
        # 단축키 모르는 사용자도 마우스로 in/out 마크 가능 + 트림 모드 진입 후 빠른 재마크.
        self.mark_in_btn = QPushButton("[ 시작점")
        self.mark_in_btn.setToolTip("현재 재생 위치를 시작점으로 마크 ([)")
        self.mark_in_btn.clicked.connect(self._on_mark_in_clicked)
        self.mark_out_btn = QPushButton("] 끝점")
        self.mark_out_btn.setToolTip("현재 재생 위치를 끝점으로 마크 (])")
        self.mark_out_btn.clicked.connect(self._on_mark_out_clicked)
        self.cut_clear_btn = QPushButton("✕ 해제")
        self.cut_clear_btn.clicked.connect(self.clear_trim)
        trim_btns.addWidget(self.cut_btn)
        trim_btns.addWidget(self.mark_in_btn)
        trim_btns.addWidget(self.mark_out_btn)
        trim_btns.addStretch(1)
        trim_btns.addWidget(self.cut_clear_btn)
        trim_v.addLayout(trim_btns)
        self.trim_row.hide()
        outer.addWidget(self.trim_row)

        # ===== 기존 메인 컨트롤 row =====
        main_row = QWidget()
        layout = QHBoxLayout(main_row)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        outer.addWidget(main_row)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(36)
        self.play_btn.clicked.connect(self.play_toggled.emit)
        layout.addWidget(self.play_btn)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(110)
        layout.addWidget(self.time_label)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.valueChanged.connect(self.seek_request.emit)
        layout.addWidget(self.seek_slider, stretch=1)

        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setFixedSize(40, 32)
        self.mute_btn.setToolTip("음소거 (M)")
        _bump_font_size(self.mute_btn, 16)
        self.mute_btn.clicked.connect(self.mute_toggled.emit)
        layout.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_changed.emit(v / 100.0)
        )
        layout.addWidget(self.volume_slider)

        self.speed_combo = QComboBox()
        for label, _ in _SPEEDS:
            self.speed_combo.addItem(label)
        self.speed_combo.addItem(_CUSTOM_SPEED_LABEL)   # 맨 끝: 사용자 지정 입력
        self.speed_combo.setCurrentText("1.0×")
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)
        layout.addWidget(self.speed_combo)

        # 프레임 스텝/스냅샷/풀스크린 — 아이콘 가독성을 위해 크게.
        self.frame_back_btn = QPushButton("◀")
        self.frame_back_btn.setFixedSize(40, 32)
        self.frame_back_btn.setToolTip("이전 프레임 (D)")
        self.frame_back_btn.clicked.connect(lambda: self.frame_step.emit(-1))
        _bump_font_size(self.frame_back_btn, 16)
        layout.addWidget(self.frame_back_btn)

        self.frame_forward_btn = QPushButton("▶")
        self.frame_forward_btn.setFixedSize(40, 32)
        self.frame_forward_btn.setToolTip("다음 프레임 (F)")
        self.frame_forward_btn.clicked.connect(lambda: self.frame_step.emit(+1))
        _bump_font_size(self.frame_forward_btn, 16)
        layout.addWidget(self.frame_forward_btn)

        self.snapshot_btn = QPushButton("📸")
        self.snapshot_btn.setFixedSize(40, 32)
        self.snapshot_btn.setToolTip("현재 프레임 → 스크린샷 탭 (Ctrl+Shift+P)")
        self.snapshot_btn.clicked.connect(self.snapshot_request.emit)
        _bump_font_size(self.snapshot_btn, 16)
        layout.addWidget(self.snapshot_btn)

        self.fullscreen_btn = QPushButton("⛶")
        self.fullscreen_btn.setFixedSize(40, 32)
        self.fullscreen_btn.setToolTip("풀스크린")
        self.fullscreen_btn.clicked.connect(self.fullscreen_toggled.emit)
        _bump_font_size(self.fullscreen_btn, 16)
        layout.addWidget(self.fullscreen_btn)

        # 트림 진입 버튼 — 항상 표시. 클릭 = 현재 위치를 in 점으로 마크 ([ 키와 동일).
        # 트림 row 의 ✂ 자르기 버튼은 in/out 둘 다 마크된 후 자르기 실행이고,
        # 이건 트림 모드 *진입* 용 (사용자가 단축키 모르고도 마우스로 시작 가능).
        self.cut_enter_btn = QPushButton("✂")
        self.cut_enter_btn.setFixedSize(40, 32)
        self.cut_enter_btn.setToolTip("트림 시작점 마크 ([) — 영상 시간 일부만 잘라내기")
        _bump_font_size(self.cut_enter_btn, 16)
        self.cut_enter_btn.clicked.connect(self._on_cut_enter_clicked)
        layout.addWidget(self.cut_enter_btn)

        self._duration_ms = 0
        self._position_ms = 0
        self._in_ms: int | None = None
        self._out_ms: int | None = None
        self._refresh_time_label()

        # 트림 레인 → 자체 상태 갱신
        self.trim_lane.in_changed.connect(self._on_lane_in_changed)
        self.trim_lane.out_changed.connect(self._on_lane_out_changed)
        self.trim_lane.seek_request.connect(self.seek_request.emit)

    # ---------- 외부 API ----------
    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, ms)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setRange(0, self._duration_ms)
        self.seek_slider.blockSignals(False)
        self.trim_lane.set_duration_ms(self._duration_ms)
        self._refresh_time_label()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, ms)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(self._position_ms)
        self.seek_slider.blockSignals(False)
        self.trim_lane.set_position_ms(self._position_ms)
        self._refresh_time_label()

    def set_playing(self, playing: bool) -> None:
        self.play_btn.setText("⏸" if playing else "▶")

    def set_audio_enabled(self, enabled: bool) -> None:
        self.volume_slider.setEnabled(enabled)
        self.mute_btn.setEnabled(enabled)

    def set_muted(self, muted: bool) -> None:
        self.mute_btn.setText("🔇" if muted else "🔊")

    def set_speed(self, rate: float) -> None:
        # 프리셋과 매칭되면 그 라벨, 아니면 사용자 지정 라벨로 임시 추가.
        for label, val in _SPEEDS:
            if abs(val - rate) < 1e-3:
                self.speed_combo.setCurrentText(label)
                return
        custom = f"{rate:.2f}×"
        # 사용자 지정 라벨 위치(맨 끝 - 1) 에 임시 추가
        idx_custom = self.speed_combo.findText(_CUSTOM_SPEED_LABEL)
        # 기존 사용자 지정 결과 라벨이 있으면 갱신, 없으면 삽입
        existing = self.speed_combo.findText(custom)
        if existing >= 0:
            self.speed_combo.setCurrentIndex(existing)
        else:
            insert_at = idx_custom if idx_custom >= 0 else self.speed_combo.count()
            self.speed_combo.insertItem(insert_at, custom)
            self.speed_combo.setCurrentText(custom)

    # ---------- 내부 ----------
    def _on_speed_changed(self, label: str) -> None:
        if label == _CUSTOM_SPEED_LABEL:
            # 입력 다이얼로그 → 0.1~16.0 배수
            value, ok = QInputDialog.getDouble(
                self, "재생 속도 지정", "배수:", 1.0, 0.1, 16.0, 2,
            )
            if not ok:
                # 취소 시 1.0× 로 복귀
                self.speed_combo.blockSignals(True)
                self.speed_combo.setCurrentText("1.0×")
                self.speed_combo.blockSignals(False)
                self.speed_changed.emit(1.0)
                return
            self.set_speed(value)
            self.speed_changed.emit(value)
            return
        for lbl, v in _SPEEDS:
            if lbl == label:
                self.speed_changed.emit(v)
                return
        # 사용자가 추가한 임시 라벨 ("1.30×" 등)
        try:
            v = float(label.replace("×", "").strip())
            self.speed_changed.emit(v)
        except ValueError:
            pass

    def _refresh_time_label(self) -> None:
        self.time_label.setText(
            f"{_format_ms(self._position_ms)} / {_format_ms(self._duration_ms)}"
        )

    # ---------- 트림 외부 API ----------
    _MIN_TRIM_MS = 100   # 0.1초 미만 거부

    def in_ms(self) -> int | None:
        return self._in_ms

    def out_ms(self) -> int | None:
        return self._out_ms

    def set_in_ms(self, ms: int) -> None:
        ms = max(0, min(ms, self._duration_ms))
        self._in_ms = ms
        self._maybe_swap()
        self._sync_trim_view()

    def set_out_ms(self, ms: int) -> None:
        ms = max(0, min(ms, self._duration_ms))
        self._out_ms = ms
        self._maybe_swap()
        self._sync_trim_view()

    def clear_trim(self) -> None:
        had = self._in_ms is not None or self._out_ms is not None
        self._in_ms = None
        self._out_ms = None
        self._sync_trim_view()
        if had:
            self.trim_cleared.emit()

    def set_cut_button_enabled(self, on: bool) -> None:
        """외부(MainWindow)가 자르기 진행 중에 버튼을 잠그기 위해 호출."""
        if on:
            self._refresh_cut_button()
        else:
            self.cut_btn.setEnabled(False)

    # ---------- 트림 내부 ----------
    def _maybe_swap(self) -> None:
        if self._in_ms is not None and self._out_ms is not None and self._out_ms < self._in_ms:
            self._in_ms, self._out_ms = self._out_ms, self._in_ms

    def _sync_trim_view(self) -> None:
        self.trim_lane.set_in_ms(self._in_ms)
        self.trim_lane.set_out_ms(self._out_ms)
        any_marked = self._in_ms is not None or self._out_ms is not None
        self.trim_row.setVisible(any_marked)
        # 트림 row 활성 시 시크 슬라이더 숨김 — 트림 레인이 시크 역할도 겸함.
        # 두 가로 막대가 동시에 보여 헷갈리던 UX 이슈 해결.
        self.seek_slider.setVisible(not any_marked)
        self._refresh_cut_button()

    def _refresh_cut_button(self) -> None:
        if self._in_ms is None or self._out_ms is None:
            self.cut_btn.setEnabled(False)
            self.cut_btn.setText("✂ 자르기")
            return
        length = abs(self._out_ms - self._in_ms)
        if length < self._MIN_TRIM_MS:
            self.cut_btn.setEnabled(False)
            self.cut_btn.setText("✂ 자르기 (너무 짧음)")
            return
        self.cut_btn.setEnabled(True)
        sec = length // 1000
        self.cut_btn.setText(f"✂ 자르기 ({sec // 60:02d}:{sec % 60:02d})")

    def _on_lane_in_changed(self, ms: int) -> None:
        self.set_in_ms(ms)

    def _on_lane_out_changed(self, ms: int) -> None:
        self.set_out_ms(ms)

    def _on_cut_clicked(self) -> None:
        if self._in_ms is None or self._out_ms is None:
            return
        self.trim_execute_requested.emit(self._in_ms, self._out_ms)

    def _on_cut_enter_clicked(self) -> None:
        """컨트롤바의 ✂ 트림 진입 버튼 — 현재 위치를 in 점으로 마크.

        '[' 단축키와 동일 동작. 단축키 모르는 사용자도 마우스로 트림 시작 가능.
        """
        self.set_in_ms(self._position_ms)

    def _on_mark_in_clicked(self) -> None:
        """트림 row 의 [ 시작점 버튼 — 현재 재생 위치를 in 점으로 마크 (덮어쓰기 가능)."""
        self.set_in_ms(self._position_ms)

    def _on_mark_out_clicked(self) -> None:
        """트림 row 의 ] 끝점 버튼 — 현재 재생 위치를 out 점으로 마크 (덮어쓰기 가능)."""
        self.set_out_ms(self._position_ms)
