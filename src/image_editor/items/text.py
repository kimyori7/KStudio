"""텍스트 주석 — QGraphicsTextItem 래핑 (자동 크기, 더블클릭 재편집)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QTextCursor
from PySide6.QtWidgets import QGraphicsTextItem, QStyle

from .base import AnnotationProperties

FONT_FAMILY = "Malgun Gothic"
FONT_POINT_SIZE = 18


class TextAnnotationItem(QGraphicsTextItem):
    """Phase 2: 고정 폰트(맑은고딕 18pt), 색상 변경만 가능."""

    def __init__(
        self,
        pos: QPointF,
        text: str,
        color: QColor,
    ) -> None:
        super().__init__(text)
        font = QFont(FONT_FAMILY, FONT_POINT_SIZE)
        self.setFont(font)
        self.setPos(pos)
        self._props = AnnotationProperties(color, thickness_step=2)  # 두께 미사용
        self._props.changed.connect(self._apply_color)
        self._apply_color()
        self.setFlag(QGraphicsTextItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsTextItem.ItemIsMovable, True)
        self.setFlag(QGraphicsTextItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        # 외부(주로 TextTool)가 편집 종료(ESC, focusOut) 시점을 알 수 있게 하는 콜백.
        # 호출 후 자동으로 None 으로 비워져 재진입(commit_active → exit_edit_mode → cb → ...) 방지.
        self.on_edit_finished = None  # type: Callable[[], None] | None

    # --- accessors ---
    def pos_f(self) -> QPointF:
        return QPointF(self.pos())

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        if self.toPlainText() != text:
            self.setPlainText(text)

    def color(self) -> QColor:
        return self._props.color()

    def set_color(self, color: QColor) -> None:
        self._props.set_color(color)

    def thickness_step(self) -> int:
        # 텍스트는 두께 미사용 — 인터페이스 일관성 위해 값만 반환
        return self._props.thickness_step()

    def set_thickness_step(self, step: int) -> None:
        self._props.set_thickness_step(step)

    # --- editing ---
    def enter_edit_mode(self) -> None:
        """텍스트 편집 모드 진입 — 외부에서 호출 (더블클릭/새 생성 시)."""
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)
        cursor = self.textCursor()
        cursor.select(QTextCursor.Document)
        self.setTextCursor(cursor)

    def exit_edit_mode(self) -> None:
        if self.textInteractionFlags() == Qt.NoTextInteraction:
            return  # 이미 편집 모드 아니면 콜백 재호출 방지
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        cb = self.on_edit_finished
        self.on_edit_finished = None
        if cb is not None:
            cb()

    def focusOutEvent(self, event):
        # 박스 외 클릭/포커스 이동 시 자동 편집 종료
        super().focusOutEvent(event)
        if self.textInteractionFlags() != Qt.NoTextInteraction:
            self.exit_edit_mode()

    def _apply_color(self) -> None:
        self.setDefaultTextColor(self._props.color())

    def itemChange(self, change, value):
        if change == QGraphicsTextItem.ItemPositionChange and self.scene() is not None:
            from .base import clamp_position_to_scene
            clamped = clamp_position_to_scene(
                self.boundingRect(),
                value,
                self.scene().sceneRect(),
            )
            if clamped != value:
                return clamped
        return super().itemChange(change, value)

    def keyPressEvent(self, event):
        # Ctrl+Enter도 줄바꿈, Enter는 Qt 기본(=줄바꿈). ESC는 편집 종료.
        if event.key() == Qt.Key_Escape:
            self.exit_edit_mode()
            return
        super().keyPressEvent(event)

    # --- hover / selected 시각 표시 ---
    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)  # 텍스트 자체 그리기
        selected = bool(option.state & QStyle.State_Selected)
        hovered = self.isUnderMouse() and not selected
        editing = self.textInteractionFlags() != Qt.NoTextInteraction
        if not (selected or hovered or editing):
            return
        outline = QColor(100, 180, 255)
        # editing 또는 selected = 진한 dashed, hover = 옅은 solid
        strong = selected or editing
        outline.setAlpha(220 if strong else 110)
        painter.setPen(QPen(outline, 1, Qt.DashLine if strong else Qt.SolidLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.boundingRect().adjusted(2, 2, -2, -2))

    def hoverEnterEvent(self, event):
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.update()
        super().hoverLeaveEvent(event)
