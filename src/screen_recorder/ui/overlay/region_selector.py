"""영역 선택 풀스크린 오버레이 (가상 데스크톱 + 확대경 + 치수 라벨)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QGuiApplication, QImage, QFont
from PySide6.QtWidgets import QWidget

from ...capture.targets import Rect
from ...screenshot.capture import virtual_desktop_bounds
from .magnifier import Magnifier, TOTAL_W as MAG_W, TOTAL_H as MAG_H


_MAG_OFFSET = 24      # 커서에서 확대경까지 간격


class RegionSelector(QWidget):
    region_selected = Signal(object)   # Rect
    cancelled = Signal()

    def __init__(self, show_magnifier: bool = True):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 가상 데스크톱 전체 덮기 (모든 모니터)
        bounds = virtual_desktop_bounds()
        self.setGeometry(bounds)
        self._bounds = bounds
        self.setCursor(Qt.CrossCursor)

        self._origin: QPoint | None = None
        self._end: QPoint | None = None
        self._rect = QRect()

        self._show_magnifier = show_magnifier
        self._magnifier: Magnifier | None = None
        if show_magnifier:
            self._magnifier = Magnifier(self)
            self._magnifier.hide()  # 드래그 시작할 때만 보여줌

    # ---------- 외부 API ----------

    def set_source_image(self, img: QImage) -> None:
        """확대경에 쓸 소스 이미지(가상 데스크톱 스냅샷) 주입."""
        if self._magnifier is not None:
            self._magnifier.set_source(img)

    # ---------- 이벤트 ----------

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._cancel()
            return
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._end = self._origin
            self._rect = QRect(self._origin, self._end)
            self._show_mag_at(self._origin)
            self.update()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._end = e.position().toPoint()
            self._rect = QRect(self._origin, self._end).normalized()
            self._show_mag_at(self._end)
            self.update()

    def mouseDoubleClickEvent(self, _):
        self._commit()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._rect.isValid() and self._rect.width() > 5 and self._rect.height() > 5:
            self._commit()

    # ---------- 헬퍼 ----------

    def _show_mag_at(self, local_pos: QPoint) -> None:
        if self._magnifier is None:
            return
        # 위젯 좌표 → 가상 데스크톱 좌표 (magnifier 가 소스 이미지에서 발췌할 때 필요)
        global_pt = QPoint(
            self._bounds.x() + local_pos.x(),
            self._bounds.y() + local_pos.y(),
        )
        self._magnifier.update_at(global_pt)

        # 확대경을 커서 오른쪽-아래 살짝 떨어진 위치에 두되, 화면 밖으로 넘치면 반대쪽으로
        mx = local_pos.x() + _MAG_OFFSET
        my = local_pos.y() + _MAG_OFFSET
        if mx + MAG_W > self.width():
            mx = local_pos.x() - _MAG_OFFSET - MAG_W
        if my + MAG_H > self.height():
            my = local_pos.y() - _MAG_OFFSET - MAG_H
        self._magnifier.move(max(0, mx), max(0, my))
        self._magnifier.show()
        self._magnifier.raise_()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    def _commit(self) -> None:
        if self._rect.isValid() and self._rect.width() > 0 and self._rect.height() > 0:
            # 위젯 좌표 → 가상 데스크톱 좌표
            r = Rect(
                self._bounds.x() + self._rect.x(),
                self._bounds.y() + self._rect.y(),
                self._rect.width(),
                self._rect.height(),
            )
            self.region_selected.emit(r)
            self.close()

    def paintEvent(self, _):
        p = QPainter(self)
        # 반투명 어두움으로 화면 전체 덮기
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if self._rect.isValid():
            # 선택 영역만 원본 노출 (clear composition)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(self._rect, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # 점선 테두리
            pen = QPen(QColor("#FFB300"), 2, Qt.DashLine)
            p.setPen(pen)
            p.drawRect(self._rect)

            # 치수 라벨
            self._draw_dimension_label(p)

    def _draw_dimension_label(self, p: QPainter) -> None:
        w = self._rect.width()
        h = self._rect.height()
        text = f"{w} × {h}"
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        padding = 4
        text_w = fm.horizontalAdvance(text) + padding * 2
        text_h = fm.height() + padding * 2
        # 기본: 사각형 왼쪽 위 바깥. 화면 위쪽에 공간이 없으면 안쪽 위로.
        lx = self._rect.left()
        ly = self._rect.top() - text_h - 2
        if ly < 0:
            ly = self._rect.top() + 2
        bg = QRect(lx, ly, text_w, text_h)
        p.fillRect(bg, QColor(0, 0, 0, 200))
        p.setPen(QColor(255, 255, 255))
        p.drawText(bg, Qt.AlignCenter, text)
