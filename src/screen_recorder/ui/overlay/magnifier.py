"""영역 선택 드래그 중에 표시되는 확대경 위젯 (120x120 @ 4x)."""
from __future__ import annotations
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import QWidget


LENS_SIZE = 120           # 확대 박스 한 변
ZOOM = 4                  # 확대 배율 — 원본 30x30 영역을 120x120 으로
LABEL_HEIGHT = 20         # 좌표 라벨 높이
TOTAL_W = LENS_SIZE
TOTAL_H = LENS_SIZE + LABEL_HEIGHT


class Magnifier(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # 드래그 가로막지 않음
        self.setFixedSize(TOTAL_W, TOTAL_H)

        self._source: QImage | None = None
        self._cursor_pos: QPoint = QPoint(0, 0)

    def set_source(self, img: QImage) -> None:
        self._source = img

    def update_at(self, pos: QPoint) -> None:
        """커서의 가상 데스크톱 좌표 (소스 이미지 상 좌표와 동일)."""
        self._cursor_pos = QPoint(pos)
        self.update()

    def coord_text(self) -> str:
        return f"X: {self._cursor_pos.x()}  Y: {self._cursor_pos.y()}"

    def paintEvent(self, _):
        p = QPainter(self)
        lens_rect = QRect(0, 0, LENS_SIZE, LENS_SIZE)
        label_rect = QRect(0, LENS_SIZE, TOTAL_W, LABEL_HEIGHT)

        # 확대 영역
        p.fillRect(lens_rect, QColor(20, 20, 20))
        if self._source is not None and not self._source.isNull():
            src_w = LENS_SIZE // ZOOM     # 30
            src_h = LENS_SIZE // ZOOM
            sx = self._cursor_pos.x() - src_w // 2
            sy = self._cursor_pos.y() - src_h // 2
            # 가상 데스크톱 경계 근처에서 source_rect 가 이미지 바깥으로 나가지 않도록 클램프
            sx = max(0, min(sx, self._source.width() - src_w))
            sy = max(0, min(sy, self._source.height() - src_h))
            src_rect = QRect(sx, sy, src_w, src_h)
            p.drawImage(lens_rect, self._source, src_rect)

        # 십자선
        p.setPen(QPen(QColor(255, 190, 0), 1))
        cx = LENS_SIZE // 2
        cy = LENS_SIZE // 2
        p.drawLine(cx, 0, cx, LENS_SIZE)
        p.drawLine(0, cy, LENS_SIZE, cy)
        # 가운데 1픽셀 박스 (실제 선택될 픽셀 강조)
        p.setPen(QPen(QColor(255, 50, 50), 1))
        p.drawRect(cx - ZOOM // 2, cy - ZOOM // 2, ZOOM, ZOOM)

        # 테두리
        p.setPen(QPen(QColor(255, 190, 0), 2))
        p.drawRect(lens_rect.adjusted(0, 0, -1, -1))

        # 좌표 라벨
        p.fillRect(label_rect, QColor(0, 0, 0, 200))
        p.setPen(QColor(255, 255, 255))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(label_rect, Qt.AlignCenter, self.coord_text())
