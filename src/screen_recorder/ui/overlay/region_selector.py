"""영역 선택 풀스크린 오버레이."""
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QGuiApplication
from PySide6.QtWidgets import QWidget

from ...capture.targets import Rect


class RegionSelector(QWidget):
    region_selected = Signal(object)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        screen = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.setCursor(Qt.CrossCursor)

        self._origin: QPoint | None = None
        self._end: QPoint | None = None
        self._rect = QRect()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._end = self._origin
            self._rect = QRect(self._origin, self._end)
            self.update()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._end = e.position().toPoint()
            self._rect = QRect(self._origin, self._end).normalized()
            self.update()

    def mouseDoubleClickEvent(self, _):
        self._commit()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._rect.isValid() and self._rect.width() > 5 and self._rect.height() > 5:
            self._commit()

    def _commit(self):
        if self._rect.isValid() and self._rect.width() > 5:
            geom = self.geometry()
            r = Rect(
                geom.x() + self._rect.x(),
                geom.y() + self._rect.y(),
                self._rect.width(),
                self._rect.height(),
            )
            self.region_selected.emit(r)
            self.close()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self._rect.isValid():
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(self._rect, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor("#FFB300"), 2, Qt.DashLine)
            p.setPen(pen)
            p.drawRect(self._rect)
