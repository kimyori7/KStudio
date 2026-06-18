"""DownloadsButton — 툴바의 브라우저식 다운로드 버튼 + 드롭다운 트레이.

설정 버튼 *왼쪽*에 두는 버튼. 다운로드가 하나라도 있으면 나타나고, 클릭하면 버튼
아래로 DownloadsPanel(줄 목록)을 팝업으로 띄운다 — 팝업이라 본문(캔버스) 레이아웃을
밀지 않는다(하단 고정 띠가 전체화면을 깎던 문제 해소).

표시:
- 새 다운로드가 시작되면 버튼이 잠깐 반짝(펄스)해 "여기 있어요" 를 알린다(매 추가마다).
- 진행 중에는 집계 진행률(%) + 이번 묶음의 (완료/전체) 개수 — 예: "45% (1/2)".
- 드롭다운 헤더에 받는 중 개수 + 완료 누적(총 몇 개 받았는지)을 함께 보여준다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QToolButton, QFrame, QVBoxLayout

from ..icons import load_icon
from .downloads_panel import DownloadsPanel

_ICON_PX = 16
# 펄스(반짝) 강조색 — 녹색(다운로드 의미). 알파를 0→불투명→0 으로 보간.
_PULSE_RGB = (34, 197, 94)


class _DownloadsPopup(QFrame):
    """버튼 아래로 떠서 DownloadsPanel 을 감싸는 프레임리스 팝업(Qt.Popup)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.Popup)
        self.setObjectName("DownloadsPopup")
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.panel = DownloadsPanel()
        lay.addWidget(self.panel)
        self.setMinimumWidth(560)


class DownloadsButton(QToolButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIcon(load_icon("download", size=_ICON_PX))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setText("")
        self.setToolTip("다운로드")
        self.setVisible(False)   # 다운로드가 생기면 나타남

        self._popup = _DownloadsPopup(self)
        self._panel: DownloadsPanel = self._popup.panel
        self._panel.rows_changed.connect(self._on_rows_changed)

        # 작업별 (downloaded, total) — 집계 진행률 계산용. 완료/실패/취소 시 제거.
        self._progress: dict[int, tuple[int, int]] = {}
        # 이번 묶음(트레이가 비었다가 다시 채워진 이후)의 전체/완료 개수.
        self._batch_total = 0
        self._batch_done = 0
        # 앱 세션 동안 성공적으로 받은 누적 개수(총 몇 개 받았는지).
        self._lifetime_done = 0
        self._flash_anim: QVariantAnimation | None = None

        self.clicked.connect(self._toggle_popup)
        self._update_display()

    # ---------- 외부 API ----------
    def add_job(self, job, title_hint: str = "다운로드 준비 중…"):
        # 트레이가 비어 있던 상태에서 새로 시작하면 묶음 카운터를 리셋.
        if self._panel.row_count() == 0:
            self._batch_total = 0
            self._batch_done = 0

        row = self._panel.add_job(job, title_hint)
        self._batch_total += 1

        key = id(job)
        self._progress[key] = (0, 0)
        job.progress.connect(lambda d, t, k=key: self._on_job_progress(k, d, t))
        job.finished.connect(lambda *_a, k=key: self._on_job_finished(k))
        job.error.connect(lambda *_a, k=key: self._on_job_stopped(k))
        job.cancelled.connect(lambda k=key: self._on_job_stopped(k))

        self.setVisible(True)
        self._flash()           # 매 추가마다 "파팡!" 반짝
        self._update_display()
        return row

    def remove_row(self, row) -> None:
        self._panel._remove_row(row)

    def panel(self) -> DownloadsPanel:
        return self._panel

    # ---------- 내부: 상태 ----------
    def _on_rows_changed(self, n: int) -> None:
        self.setVisible(n > 0)
        if n == 0:
            self._popup.hide()
        self._update_display()

    def _on_job_progress(self, key, downloaded, total) -> None:
        self._progress[key] = (int(downloaded or 0), int(total or 0))
        self._update_display()

    def _on_job_finished(self, key) -> None:
        if self._progress.pop(key, None) is not None:
            self._batch_done += 1
            self._lifetime_done += 1
        self._update_display()

    def _on_job_stopped(self, key) -> None:
        # 실패/취소 — 완료로 세지 않음(전체 개수엔 남아 '몇 개 남음' 계산 유지).
        self._progress.pop(key, None)
        self._update_display()

    def _update_display(self) -> None:
        active = list(self._progress.values())
        n_active = len(active)
        known = [(d, t) for (d, t) in active if t > 0]
        if known:
            dsum = sum(d for d, _ in known)
            tsum = sum(t for _, t in known)
            pct = max(0, min(100, int(dsum * 100 / tsum))) if tsum else 0
            self.setText(f" {pct}% ({self._batch_done}/{self._batch_total})")
        elif n_active:
            self.setText(f" ({self._batch_done}/{self._batch_total})")   # 전체 크기 미정
        elif self._batch_total:
            self.setText(f" {self._batch_done}/{self._batch_total}")      # 진행 중 없음(완료만)
        else:
            self.setText("")
        self.setToolTip(
            f"다운로드 — 받는 중 {n_active} · 완료 누적 {self._lifetime_done}개"
        )
        self._panel.set_header_text(
            f"다운로드 — 받는 중 {n_active} · 완료 누적 {self._lifetime_done}개"
        )

    # ---------- 내부: 반짝(펄스) ----------
    def _flash(self) -> None:
        if self._flash_anim is not None:
            self._flash_anim.stop()
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setKeyValueAt(0.5, 1.0)
        anim.setEndValue(0.0)
        anim.setDuration(450)
        anim.setLoopCount(3)            # 파팡파팡 — 3번 반짝
        anim.valueChanged.connect(self._apply_glow)
        anim.finished.connect(lambda: self._apply_glow(0.0))
        self._flash_anim = anim
        anim.start(QVariantAnimation.DeleteWhenStopped)

    def _apply_glow(self, t) -> None:
        a = int(200 * float(t))
        if a <= 0:
            self.setStyleSheet("")      # 빈 문자열 = 전역 QSS 로 복귀
            return
        r, g, b = _PULSE_RGB
        self.setStyleSheet(
            f"QToolButton {{ background-color: rgba({r},{g},{b},{a}); border-radius: 4px; }}"
        )

    # ---------- 내부: 팝업 ----------
    def _toggle_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.adjustSize()
        below = self.mapToGlobal(QPoint(0, self.height()))
        x = below.x() - max(0, self._popup.width() - self.width())
        self._popup.move(max(0, x), below.y())
        self._popup.show()
