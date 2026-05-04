"""이미지 크기 변경 다이얼로그 — 픽셀 또는 퍼센트 단위 자유 입력.

UX:
- 현재 W × H 표시 (read-only)
- 모드 라디오: [픽셀] / [퍼센트]
- 픽셀 모드: W [____] × H [____] 입력 + "비율 유지" 체크 (기본 ON)
- 퍼센트 모드: [____] % 입력 (한 박스, 비율 자동 유지)
- 결과 미리보기: "결과: 1920 × 1080"
- OK / 취소

비율 유지 ON 일 때 한 쪽을 바꾸면 다른 쪽이 원본 비율로 자동 갱신.
입력값은 1~16384 로 클램프 (16K 위 어차피 메모리 부담).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)


_MIN_PX = 1
_MAX_PX = 16384


class ScaleDialog(QDialog):
    """이미지 크기 변경 입력 다이얼로그."""

    def __init__(self, *, src_w: int, src_h: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("이미지 크기 변경")
        self._src_w = max(1, int(src_w))
        self._src_h = max(1, int(src_h))
        # 사용자가 비율 유지 모드에서 W/H 한쪽을 바꾸면 콜백이 다른 쪽 값을 자동
        # 갱신한다. 이 자동 갱신이 다시 콜백을 트리거하면 무한 재귀가 되므로
        # _suppress 플래그로 한 사이클만 차단.
        self._suppress = False

        root = QVBoxLayout(self)

        # 현재 크기
        cur_lbl = QLabel(f"현재 크기:  {self._src_w} × {self._src_h}")
        cur_lbl.setStyleSheet("color: #C0C4CC;")
        root.addWidget(cur_lbl)

        # 모드 선택
        mode_row = QHBoxLayout()
        self.mode_pixel = QRadioButton("픽셀")
        self.mode_percent = QRadioButton("퍼센트")
        self.mode_pixel.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.mode_pixel)
        grp.addButton(self.mode_percent)
        mode_row.addWidget(self.mode_pixel)
        mode_row.addWidget(self.mode_percent)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        # 입력 폼
        form = QFormLayout()

        self.spin_w = QSpinBox()
        self.spin_w.setRange(_MIN_PX, _MAX_PX)
        self.spin_w.setSuffix(" px")
        self.spin_w.setValue(self._src_w)

        self.spin_h = QSpinBox()
        self.spin_h.setRange(_MIN_PX, _MAX_PX)
        self.spin_h.setSuffix(" px")
        self.spin_h.setValue(self._src_h)

        self.spin_pct = QSpinBox()
        self.spin_pct.setRange(1, 800)   # 1% ~ 800% — LANCZOS 한도
        self.spin_pct.setSuffix(" %")
        self.spin_pct.setValue(100)

        self.lock_aspect = QCheckBox("비율 유지")
        self.lock_aspect.setChecked(True)

        form.addRow("가로:", self.spin_w)
        form.addRow("세로:", self.spin_h)
        form.addRow("배율:", self.spin_pct)
        form.addRow("", self.lock_aspect)
        root.addLayout(form)

        # 결과 미리보기
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("color: #5BC07C; font-weight: 600;")
        root.addWidget(self.preview_label)

        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText("적용")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # 시그널
        self.spin_w.valueChanged.connect(self._on_w_changed)
        self.spin_h.valueChanged.connect(self._on_h_changed)
        self.spin_pct.valueChanged.connect(self._on_pct_changed)
        self.mode_pixel.toggled.connect(self._on_mode_changed)
        self.mode_percent.toggled.connect(self._on_mode_changed)
        self.lock_aspect.toggled.connect(self._refresh_preview)

        self._on_mode_changed()
        self._refresh_preview()

    # ---------- 시그널 핸들러 ----------

    def _on_mode_changed(self) -> None:
        is_pct = self.mode_percent.isChecked()
        self.spin_w.setEnabled(not is_pct)
        self.spin_h.setEnabled(not is_pct)
        self.spin_pct.setEnabled(is_pct)
        # 모드 전환 시 현재 모드의 입력값을 다른 모드로 동기화 — 사용자가
        # 모드만 바꿔도 미리보기가 자연스레 따라옴.
        if is_pct:
            pct = max(1, int(round(self.spin_w.value() / self._src_w * 100)))
            self._suppress = True
            self.spin_pct.setValue(pct)
            self._suppress = False
        else:
            w, h = self._target_from_pct(self.spin_pct.value())
            self._suppress = True
            self.spin_w.setValue(w)
            self.spin_h.setValue(h)
            self._suppress = False
        self._refresh_preview()

    def _on_w_changed(self, w: int) -> None:
        if self._suppress:
            return
        if self.lock_aspect.isChecked():
            self._suppress = True
            self.spin_h.setValue(max(_MIN_PX, int(round(w * self._src_h / self._src_w))))
            self._suppress = False
        self._refresh_preview()

    def _on_h_changed(self, h: int) -> None:
        if self._suppress:
            return
        if self.lock_aspect.isChecked():
            self._suppress = True
            self.spin_w.setValue(max(_MIN_PX, int(round(h * self._src_w / self._src_h))))
            self._suppress = False
        self._refresh_preview()

    def _on_pct_changed(self, _pct: int) -> None:
        if self._suppress:
            return
        self._refresh_preview()

    # ---------- 결과 미리보기 ----------

    def _target_from_pct(self, pct: int) -> tuple[int, int]:
        w = max(_MIN_PX, min(_MAX_PX, int(round(self._src_w * pct / 100))))
        h = max(_MIN_PX, min(_MAX_PX, int(round(self._src_h * pct / 100))))
        return w, h

    def _refresh_preview(self) -> None:
        w, h = self.target_size()
        delta = ""
        if w > self._src_w or h > self._src_h:
            delta = "  (업스케일)"
        elif w < self._src_w or h < self._src_h:
            delta = "  (다운스케일)"
        self.preview_label.setText(f"결과:  {w} × {h}{delta}")

    # ---------- API ----------

    def target_size(self) -> tuple[int, int]:
        """현재 입력으로 결정된 목표 크기. 모드에 따라 픽셀 또는 퍼센트 기반."""
        if self.mode_percent.isChecked():
            return self._target_from_pct(self.spin_pct.value())
        return self.spin_w.value(), self.spin_h.value()
