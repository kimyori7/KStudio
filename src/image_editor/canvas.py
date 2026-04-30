"""LayerCanvas — LayerStack 을 QGraphicsScene 으로 시각화."""
from __future__ import annotations
from typing import Dict, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap, QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsItemGroup, QGraphicsPixmapItem,
    QGraphicsScene, QGraphicsView,
)

from .layer_model import LayerStack
from .layers.annotation_layer import AnnotationLayer
from .layers.base import Layer
from .layers.image_layer import ImageLayer
from .selection import SelectionModel, SelectionOverlay
from .tools.base import Tool

ZOOM_MIN = 0.25
ZOOM_MAX = 4.0
ZOOM_STEP = 1.15

# 투명 영역 시각화 — Photoshop 스타일 격자무늬. 캔버스 sceneRect 안쪽만 그림.
_CHECKER_SIZE = 10
_CHECKER_LIGHT = QColor("#3A3F46")    # 다크 테마 — 매우 어두운 회색
_CHECKER_DARK = QColor("#2C3138")     # 그보다 살짝 더 어두운 회색


def _make_checkerboard_brush() -> QBrush:
    """sceneRect 위 투명 영역에 깔리는 격자무늬 brush — 한 번 만들어 재사용."""
    s = _CHECKER_SIZE
    pm = QPixmap(s * 2, s * 2)
    p = QPainter(pm)
    try:
        p.fillRect(0, 0, s * 2, s * 2, _CHECKER_LIGHT)
        p.fillRect(0, 0, s, s, _CHECKER_DARK)
        p.fillRect(s, s, s, s, _CHECKER_DARK)
    finally:
        p.end()
    return QBrush(pm)


_CHECKER_BRUSH: QBrush | None = None


def _checkerboard_brush() -> QBrush:
    global _CHECKER_BRUSH
    if _CHECKER_BRUSH is None:
        _CHECKER_BRUSH = _make_checkerboard_brush()
    return _CHECKER_BRUSH


class LayerCanvas(QGraphicsView):
    zoom_changed = Signal(float)   # 새 배율 (1.0 = 100%) — 옵션바 줌 라벨 갱신용
    delete_selection_requested = Signal()  # Del 키 — selection 영역 삭제 요청

    def __init__(self, stack: LayerStack) -> None:
        self._stack = stack
        self._scene = QGraphicsScene()
        super().__init__(self._scene)
        self._items: Dict[int, QGraphicsItem] = {}   # layer_id → scene item
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 브러시 도구의 커서 미리보기 링이 hover 로 따라오도록 mouse tracking 활성.
        self.viewport().setMouseTracking(True)
        self._sync_scene_rect()
        self._stack.layers_changed.connect(self._rebuild_items)
        self._stack.layer_pixmap_changed.connect(self._refresh_single_layer)
        self._stack.canvas_size_changed.connect(self._sync_scene_rect)
        self._tool: Optional[Tool] = None
        self._tool_scene: QGraphicsScene = self._scene
        self._zoom: float = 1.0
        # 큰 이미지 로드 시 창 축소가 막히는 문제 방지 — 캔버스의 최소 크기는 작게.
        self.setMinimumSize(0, 0)
        self._shift_held: bool = False
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFocusPolicy(Qt.StrongFocus)
        self._stack.active_layer_changed.connect(self._on_active_changed)
        self._rebuild_items()

    # --- 배경 페인팅 ---
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        """sceneRect 안쪽엔 투명 격자무늬, 바깥쪽은 뷰포트 기본색.

        scene 의 sceneRect 가 캔버스 영역. 그 안쪽만 격자로 채워야 캔버스 외부와 시각적으로
        구분됨. 격자는 zoom 과 무관한 device-pixel 단위로 그리도록 painter transform 을
        잠깐 reset — 안 그러면 zoom 시 격자가 같이 늘어나 점이 커 보임.
        """
        super().drawBackground(painter, rect)
        scene_rect = self.scene().sceneRect()
        clip = rect.intersected(scene_rect)
        if clip.isEmpty():
            return
        # device 좌표 기준으로 격자 크기 고정 (zoom 무관).
        painter.save()
        painter.setBrushOrigin(0, 0)
        painter.fillRect(clip, _checkerboard_brush())
        painter.restore()

    # --- 모델 → 뷰 ---
    def _sync_scene_rect(self) -> None:
        s = self._stack.canvas_size
        self._scene.setSceneRect(QRectF(0, 0, s.width(), s.height()))

    def _rebuild_items(self) -> None:
        # 단순 전략: 매번 전체 동기화 (성능 충분, 1차 단순성 우선)
        existing_ids = set(self._items.keys())
        wanted_ids = {l.id for l in self._stack.layers}
        # 제거
        for lid in existing_ids - wanted_ids:
            it = self._items.pop(lid)
            self._scene.removeItem(it)
            # AnnotationLayer.scene 에 연결한 changed 핸들러 정리
            self._disconnect_annotation_scene(lid)
        # 추가/갱신
        for z, layer in enumerate(self._stack.layers):
            it = self._items.get(layer.id)
            if it is None:
                it = self._make_item(layer)
                self._items[layer.id] = it
                self._scene.addItem(it)
                # AnnotationLayer 는 scene.changed 에 연결해 시각 자동 갱신
                if isinstance(layer, AnnotationLayer):
                    self._connect_annotation_scene(layer)
            self._update_item(it, layer, z)

    def _make_item(self, layer: Layer) -> QGraphicsItem:
        # 모든 레이어를 QGraphicsPixmapItem 으로 — AnnotationLayer 도 pixmap 으로 렌더링.
        return QGraphicsPixmapItem()

    def _update_item(self, it: QGraphicsItem, layer: Layer, z: int) -> None:
        it.setVisible(bool(layer.visible))
        it.setOpacity(float(layer.opacity))
        it.setZValue(z)
        if isinstance(layer, ImageLayer) and isinstance(it, QGraphicsPixmapItem):
            cs = self._stack.canvas_size
            # 빠른 경로 — offset 이 0 이고 픽스맵이 캔버스 크기와 같으면 클리핑이
            # 필요 없어 캔버스 크기 버퍼 합성을 건너뛴다 (브러시/지우개 핫패스의
            # ~24MB/frame 메모리 트래픽을 절약 — 1080p 에서 큰 차이).
            needs_clip = (
                layer.offset.x() != 0 or layer.offset.y() != 0
                or layer.pixmap.width() != cs.width()
                or layer.pixmap.height() != cs.height()
            )
            if needs_clip:
                # offset 이 음수이거나 크기가 다르면 캔버스 영역 밖 픽셀을 잘라낸다
                # (Crop 후 overflow 방지). opacity 는 item.setOpacity 에서 처리하므로
                # 여기서는 적용하지 않음.
                buf = QImage(cs, QImage.Format_ARGB32)
                buf.fill(Qt.transparent)
                p = QPainter(buf)
                try:
                    p.drawImage(layer.offset, layer.composed_pixmap())
                finally:
                    p.end()
                it.setPixmap(QPixmap.fromImage(buf))
            else:
                it.setPixmap(QPixmap.fromImage(layer.composed_pixmap()))
            it.setPos(0, 0)
        elif isinstance(layer, AnnotationLayer) and isinstance(it, QGraphicsPixmapItem):
            # AnnotationLayer 자체 scene 의 모든 아이템을 한 장 이미지로 렌더링.
            rendered = layer.render(self._stack.canvas_size)
            it.setPixmap(QPixmap.fromImage(rendered))
            it.setPos(0, 0)

    def _connect_annotation_scene(self, layer: "AnnotationLayer") -> None:
        """AnnotationLayer 의 scene.changed → 해당 레이어 픽스맵 즉시 재렌더."""
        scene = layer.scene
        layer_id = layer.id
        # 동일 layer 가 이미 연결되어 있으면 무시 (rebuild 시 중복 방지)
        existing = self._scene_conns.get(layer_id) if hasattr(self, "_scene_conns") else None
        if existing is not None:
            return
        if not hasattr(self, "_scene_conns"):
            self._scene_conns: Dict[int, "tuple"] = {}

        def _refresh(_rects=None) -> None:
            it = self._items.get(layer_id)
            l = self._stack.get_layer(layer_id)
            if it is None or l is None:
                return
            rendered = l.render(self._stack.canvas_size)
            if isinstance(it, QGraphicsPixmapItem):
                it.setPixmap(QPixmap.fromImage(rendered))

        scene.changed.connect(_refresh)
        self._scene_conns[layer_id] = (scene, _refresh)

    def _refresh_single_layer(self, layer_id: int) -> None:
        """layer_pixmap_changed 신호 핸들러 — 한 레이어의 픽스맵만 갱신.

        브러시/지우개 등 매 mouse_move 마다 호출되는 핫패스이므로 전체 rebuild 대신
        해당 레이어 아이템만 업데이트 (1080p 풀합성 비용 회피).
        """
        layer = self._stack.get_layer(layer_id)
        if layer is None:
            return
        it = self._items.get(layer_id)
        if it is None:
            return
        # z 인덱스는 변하지 않으므로 _update_item 의 visible/opacity/픽스맵 갱신만 필요.
        # _stack.layers 에서 z 를 다시 찾는 것은 O(n) 이라 그냥 현재 zValue 유지.
        z = int(it.zValue())
        self._update_item(it, layer, z)

    def _disconnect_annotation_scene(self, layer_id: int) -> None:
        if not hasattr(self, "_scene_conns"):
            return
        pair = self._scene_conns.pop(layer_id, None)
        if pair is None:
            return
        scene, slot = pair
        try:
            scene.changed.disconnect(slot)
        except (TypeError, RuntimeError):
            pass

    # --- 합성 출력 ---
    def composite(self) -> QImage:
        out = QImage(self._stack.canvas_size, QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            for layer in self._stack.layers:
                if not layer.visible:
                    continue
                rendered = layer.render(self._stack.canvas_size)
                painter.setOpacity(1.0)
                painter.drawImage(0, 0, rendered)
        finally:
            painter.end()
        return out

    # --- 도구 ---
    def set_tool(self, tool: Optional[Tool], *,
                 target_scene: Optional[QGraphicsScene] = None) -> None:
        """tool 을 활성 도구로 지정. target_scene 을 주면 도구의 mouse/key 이벤트가
        그 scene 에 라우팅됨 (예: 활성 AnnotationLayer 의 자체 scene). None 이면
        뷰의 기본 scene 을 사용한다."""
        if self._tool is tool and target_scene is self._tool_scene:
            return
        if self._tool is not None:
            self._tool.deactivated(self._tool_scene)
        self._tool = tool
        self._tool_scene = target_scene if target_scene is not None else self._scene
        if tool is not None:
            tool.activated(self._tool_scene)

    def current_tool(self) -> Optional[Tool]:
        return self._tool

    def attach_selection(self, model: SelectionModel) -> None:
        """SelectionModel 을 캔버스의 메인 scene 위 marching-ants 오버레이로 시각화."""
        if getattr(self, "_selection_overlay", None) is not None:
            self._selection_overlay.detach()
        self._selection_overlay = SelectionOverlay(self._scene, model, parent=self)
        self._selection_model = model

    def selection_model(self) -> Optional["SelectionModel"]:
        return getattr(self, "_selection_model", None)

    def active_layer_id(self) -> Optional[int]:
        return self._stack.active_layer_id

    def _on_active_changed(self, lid: int) -> None:
        # 후속에 도구 활/비활 정책에 사용. 현재는 이벤트 후크 자리만.
        pass

    # --- 줌 ---
    def zoom_factor(self) -> float:
        return self._zoom

    def current_zoom(self) -> float:
        """현재 배율 (1.0 = 100%). zoom_factor 의 alias — 외부 호환용."""
        return self._zoom

    def set_zoom(self, factor: float) -> None:
        factor = max(ZOOM_MIN, min(ZOOM_MAX, factor))
        if abs(factor - self._zoom) < 1e-6:
            return
        ratio = factor / self._zoom
        self._zoom = factor
        self.scale(ratio, ratio)
        self.zoom_changed.emit(self._zoom)

    def set_zoom_factor(self, factor: float) -> None:
        """절대 배율 지정 — 외부 호환용 (set_zoom 의 alias)."""
        self.set_zoom(factor)

    def set_hundred_percent_mode(self) -> None:
        """배율을 100% 로 리셋."""
        self.resetTransform()
        self._zoom = 1.0
        self.zoom_changed.emit(self._zoom)

    def zoom_in_at_cursor(self) -> None:
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out_at_cursor(self) -> None:
        self.set_zoom(self._zoom / ZOOM_STEP)

    def fit_to_view(self) -> None:
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        # fitInView 가 transform 을 직접 바꾸므로 _zoom 동기화
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    def shift_held(self) -> bool:
        return self._shift_held

    # --- 이벤트 ---
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in_at_cursor()
            else:
                self.zoom_out_at_cursor()
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.mouse_press(self._tool_scene, scene_pos)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.mouse_move(self._tool_scene, scene_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.mouse_release(self._tool_scene, scene_pos)
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if self._tool is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            self._tool.double_click(self._tool_scene, scene_pos)
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Shift:
            self._shift_held = True
        if self._tool is not None:
            if e.key() == Qt.Key_Escape:
                self._tool.key_escape(self._scene)
            elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._tool.key_enter(self._scene)
        # Del — 도구가 자체적으로 처리하면(예: 마술봉 보류 → 확정) 그 결과를 우선.
        # 그렇지 않으면 캔버스의 selection 영역 삭제로 폴백.
        if e.key() == Qt.Key_Delete:
            consumed = False
            if self._tool is not None:
                consumed = bool(self._tool.key_delete(self._scene))
            if not consumed:
                sel = self.selection_model()
                if sel is not None and sel.has_selection():
                    self.delete_selection_requested.emit()
                    e.accept()
                    return
            else:
                e.accept()
                return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Shift:
            self._shift_held = False
        super().keyReleaseEvent(e)
