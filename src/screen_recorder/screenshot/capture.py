"""스크린샷 캡처 순수 유틸 — 가상 데스크톱 스냅, 크롭, PNG 저장."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter, QGuiApplication


def virtual_desktop_bounds() -> QRect:
    """모든 스크린 geometry 의 union 을 계산.

    반환값은 가상 데스크톱 좌표계의 bounding rectangle.
    """
    screens = QGuiApplication.screens()
    if not screens:
        return QRect(0, 0, 0, 0)
    bounds = screens[0].geometry()
    for s in screens[1:]:
        bounds = bounds.united(s.geometry())
    return bounds


def snapshot_virtual_desktop() -> QImage:
    """현재 화면 전체(가상 데스크톱)를 하나의 QImage 로 스냅.

    각 스크린을 따로 grab 해서 virtual desktop 좌표로 합성한다.
    """
    screens = QGuiApplication.screens()
    bounds = virtual_desktop_bounds()
    if bounds.isEmpty():
        return QImage()

    canvas = QImage(bounds.size(), QImage.Format_ARGB32)
    canvas.fill(0)  # 투명 배경

    painter = QPainter(canvas)
    for screen in screens:
        pixmap = screen.grabWindow(0)  # 0 = desktop root
        geom = screen.geometry()
        # bounds 를 기준으로 상대 좌표 계산
        painter.drawPixmap(geom.x() - bounds.x(), geom.y() - bounds.y(), pixmap)
    painter.end()
    return canvas


def crop_to_rect(src: QImage, rect: QRect) -> QImage:
    """이미지를 사각형으로 자른다. 범위 밖이면 교집합만 반환."""
    if src.isNull():
        return QImage()
    src_rect = QRect(0, 0, src.width(), src.height())
    clipped = rect.intersected(src_rect)
    if clipped.isEmpty():
        return QImage()
    return src.copy(clipped)


def save_png(image: QImage, path: Path) -> None:
    """QImage 를 PNG 파일로 저장. 상위 디렉토리가 없으면 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        raise IOError(f"Failed to save PNG: {path}")
