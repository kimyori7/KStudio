"""DownloadsButton — 툴바의 브라우저식 다운로드 버튼 + 드롭다운 트레이.

설정 버튼 *왼쪽*에 두는 버튼. 다운로드가 하나라도 있으면 나타나고, 클릭하면 버튼
아래로 DownloadsPanel(줄 목록)을 팝업으로 띄운다 — 팝업이라 본문(캔버스) 레이아웃을
밀지 않는다(하단 고정 띠가 전체화면을 깎던 문제 해소). 진행 중에는 버튼에 집계
진행률(%)을 표시해 웹 브라우저 다운로드처럼 한눈에 보이게 한다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QToolButton, QFrame, QVBoxLayout

from ..icons import load_icon
from .downloads_panel import DownloadsPanel

_ICON_PX = 16


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
        self.setMinimumWidth(540)


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

        # 작업별 (downloaded, total) — 버튼 집계 진행률 계산용. 완료/실패/취소 시 제거.
        self._progress: dict[int, tuple[int, int]] = {}
        self.clicked.connect(self._toggle_popup)

    # ---------- 외부 API ----------
    def add_job(self, job, title_hint: str = "다운로드 준비 중…"):
        row = self._panel.add_job(job, title_hint)
        key = id(job)
        self._progress[key] = (0, 0)
        job.progress.connect(lambda d, t, k=key: self._on_job_progress(k, d, t))
        job.finished.connect(lambda *_a, k=key: self._on_job_done(k))
        job.error.connect(lambda *_a, k=key: self._on_job_done(k))
        job.cancelled.connect(lambda k=key: self._on_job_done(k))
        self.setVisible(True)
        self._update_button_text()
        return row

    def remove_row(self, row) -> None:
        self._panel._remove_row(row)

    def panel(self) -> DownloadsPanel:
        return self._panel

    # ---------- 내부 ----------
    def _on_rows_changed(self, n: int) -> None:
        self.setVisible(n > 0)
        if n == 0:
            self._popup.hide()

    def _on_job_progress(self, key, downloaded, total) -> None:
        self._progress[key] = (int(downloaded or 0), int(total or 0))
        self._update_button_text()

    def _on_job_done(self, key) -> None:
        self._progress.pop(key, None)
        self._update_button_text()

    def _update_button_text(self) -> None:
        active = list(self._progress.values())
        known = [(d, t) for (d, t) in active if t > 0]
        if known:
            dsum = sum(d for d, _ in known)
            tsum = sum(t for _, t in known)
            pct = max(0, min(100, int(dsum * 100 / tsum))) if tsum else 0
            self.setText(f" {pct}%")
        elif active:
            self.setText(f" {len(active)}")   # 전체 크기 미정 — 개수만
        else:
            self.setText("")                  # 진행 중 없음(완료 줄만 남음)
        self.setToolTip(f"다운로드 — 진행 {len(active)} · 전체 {self._panel.row_count()}")

    def _toggle_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.adjustSize()
        below = self.mapToGlobal(QPoint(0, self.height()))
        # 팝업이 버튼보다 넓으므로 오른쪽 끝을 버튼에 맞춰 왼쪽으로 펼친다.
        x = below.x() - max(0, self._popup.width() - self.width())
        self._popup.move(max(0, x), below.y())
        self._popup.show()
