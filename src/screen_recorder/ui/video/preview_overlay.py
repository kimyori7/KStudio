"""영상 위에 효과 시뮬레이션을 그리는 투명 오버레이.

Stage 3a: 캡션만. Stage 4+ 에서 줌·SVG HUD 추가.

PlayerWidget 의 비디오 surface 위에 자식으로 떠 있다. 매 paint 마다 현재
재생 위치(_position_ms) 와 사이드카(_sidecar) 를 보고, in_ms~out_ms 안에
들어오는 캡션을 그린다. fade in/out 은 선형 알파 보간.

캡션 드래그: 어느 anchor 든 화면에서 드래그 가능. 드래그 시 자동으로
anchor='free' 로 전환되고 정규화 좌표(0~1) 로 저장. 호버 시 손 모양 커서로
드래그 가능함을 시각화. 그 외 영역의 마우스 이벤트는 하부 영상 surface 로
통과 (mousePressEvent 가 hit 안 되면 ignore() 호출).
"""
from __future__ import annotations
from dataclasses import replace
from typing import Callable, Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ...effects import Sidecar
from ...effects.types.broll import BrollEffect
from ...effects.types.caption import CaptionEffect, Position
from ...effects.types.zoom import ZoomEffect
from . import caption_renderer


# Stage 6 — 줌 가이드 사각형 색. 노란/주황 반투명, 헤더 색(_TYPE_COLOR["zoom"]) 과 다른
# 색을 사용해 lane 막대와 시각적으로 구분 (lane 은 초록, 가이드는 노랑).
_ZOOM_GUIDE_COLOR = QColor(255, 200, 0, 200)
_ZOOM_LABEL_BG = QColor(0, 0, 0, 160)
_ZOOM_LABEL_FG = QColor(255, 255, 255, 240)

# Stage 7 — broll PiP 가이드 사각형 색. _TYPE_COLOR["broll"] (#f59e0b) 와 매칭되는
# 주황 외곽선 + 반투명 검정 채움 + 흰 라벨. 줌 가이드(노랑 외곽선만) 와 구분.
_BROLL_GUIDE_COLOR = QColor(245, 158, 11, 220)
_BROLL_FILL_COLOR = QColor(0, 0, 0, 110)
_BROLL_LABEL_FG = QColor(255, 255, 255, 240)
_BROLL_MARGIN = 8   # px — 화면 가장자리에서 사각형까지 여백


class PreviewOverlay(QWidget):
    """투명 위젯 — paintEvent 에서 캡션을 그린다.

    어느 anchor 든 캡션은 화면 위에서 드래그 가능. 드래그 시작 시 자동으로
    anchor='free' 로 전환됨. 캡션 외 영역의 마우스 이벤트는 ignore() 통과.
    """

    caption_position_changed = Signal(object)   # CaptionEffect — 드래그 후 새 position
    effect_drag_changed = Signal(object)        # ZoomEffect / BrollEffect — 드래그 후 갱신

    def __init__(self) -> None:
        super().__init__()
        # WA_TransparentForMouseEvents 를 끄고 hit-test 로 직접 처리해야 캡션
        # 드래그가 가능. 비-hit 영역은 mousePressEvent 에서 ignore() → 부모로 전달.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 호버 커서 변경 위해 mouseTracking ON.
        self.setMouseTracking(True)
        self._sidecar: Optional[Sidecar] = None
        self._position_ms: int = 0
        # paintEvent 마다 모든 캡션의 bounding box 저장 — mousePress/Move hit-test 용.
        self._caption_bboxes: dict[str, "QRect"] = {}
        # 줌·곁들임 가이드의 bbox + effect id — paint 마다 갱신, 드래그 hit-test 용.
        # 그려진 순서대로 기록 (위로 갈수록 z-order 위) — 역순으로 hit-test.
        self._overlay_hits: list[tuple[QRect, str, str]] = []   # (bbox, kind, eff_id)
        # 드래그 상태 — 캡션
        self._drag_caption_id: Optional[str] = None
        self._drag_start_pos = None       # QPoint
        self._drag_start_offset_norm: tuple[float, float] = (0.5, 0.5)
        self._drag_override_offset: Optional[tuple[float, float]] = None
        # 드래그 상태 — 줌·곁들임 (한 번에 하나만 활성). drag_kind in {"zoom", "broll"}.
        self._drag_kind: Optional[str] = None
        self._drag_eff_id: Optional[str] = None
        self._drag_start_norm: tuple[float, float] = (0.5, 0.5)
        self._drag_override_norm: Optional[tuple[float, float]] = None
        # 드래그 정규화 좌표의 허용 범위 (xmin, xmax, ymin, ymax) — 사각형의 모서리가
        # 영상 frame 안에 머물도록 효과별 크기를 고려해 mousePress 시 계산.
        # 줌(scale=2) → cx/cy 가능 범위 = [0.25, 0.75], 곁들임(size_ratio=0.3) → pos_x/y = [0, 0.7].
        self._drag_clamp: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0)
        # 영상 프레임 rect provider — letterbox 시 검은 띠를 제외한 실제 영상 영역.
        # None 이면 self.rect() (위젯 전체) 사용. 이 rect 안에서만 그리고 드래그한다.
        self._frame_rect_provider: Optional[Callable[[], QRect]] = None

    # ---------- public ----------
    def set_sidecar(self, sc: Optional[Sidecar]) -> None:
        self._sidecar = sc
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self.update()

    def set_video_frame_rect_provider(self, fn: Optional[Callable[[], QRect]]) -> None:
        """영상 프레임 rect (letterbox 영역 제외) 를 매번 조회하는 콜백 설치.

        호출자(VideoTab) 가 player.video_frame_rect 를 lambda 로 넘긴다.
        None 이면 위젯 전체를 영상 프레임으로 간주 (테스트 호환).
        """
        self._frame_rect_provider = fn
        self.update()

    # ---------- internal: frame rect ----------
    def _frame_rect(self) -> QRect:
        if self._frame_rect_provider is not None:
            r = self._frame_rect_provider()
            if r.isValid() and r.width() > 0 and r.height() > 0:
                return r
        return self.rect()

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        self._caption_bboxes = {}   # 매 paint 마다 갱신
        self._overlay_hits = []
        if self._sidecar is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        for eff in self._sidecar.effects:
            if eff.type != "caption":
                continue
            self._draw_caption(p, eff)

        # Stage 6 — 활성 ZoomEffect 가 있으면 가이드 사각형 그리기.
        # v1: 실제 픽셀 줌은 export 에서만 적용. 미리보기는 사각형으로 영역 표시.
        for eff in self._sidecar.effects:
            if not isinstance(eff, ZoomEffect):
                continue
            if not (eff.in_ms <= self._position_ms < eff.out_ms):
                continue
            self._draw_zoom_guide(p, eff)

        # Stage 7 — 활성 BrollEffect (PiP) 가 있으면 가이드 사각형 그리기.
        # v1: 실제 영상 PiP 는 export 에서만 적용. 미리보기는 사각형 + 라벨.
        # placement='fullscreen' 은 v1 미지원 — 가이드 미표시.
        for eff in self._sidecar.effects:
            if not isinstance(eff, BrollEffect):
                continue
            if not (eff.in_ms <= self._position_ms < eff.out_ms):
                continue
            if eff.placement != "pip" or eff.pip is None:
                continue
            self._draw_broll_guide(p, eff)

    def _draw_caption(self, p: QPainter, c: CaptionEffect) -> None:
        # 드래그 중인 경우 임시 override position 사용
        position = c.position
        if c.id == self._drag_caption_id and self._drag_override_offset is not None:
            position = Position(anchor="free",
                                offset_x=self._drag_override_offset[0],
                                offset_y=self._drag_override_offset[1])
        # caption_renderer 의 모든 그리기를 호출하기 전에 hit-test bbox 를 기록.
        # 텍스트 width 계산을 위해 폰트는 잠시 set 후 fontMetrics 만 사용.
        f = QFont(c.font.family, c.font.size)
        f.setBold(c.font.bold)
        p.setFont(f)
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(c.text) if c.text else 0
        text_h = fm.height()
        pad = 8
        # 위치 계산은 영상 프레임 rect 안에서 — letterbox 가 있으면 검은 띠를 피해 그려진다.
        frame = self._frame_rect()
        x, y = caption_renderer.anchor_xy(
            position, text_w=text_w, text_h=text_h, pad=pad,
            surface_w=frame.width(), surface_h=frame.height(),
        )
        if position.anchor != "free":
            x += int(position.offset_x)
            y += int(position.offset_y)
        x += frame.x()
        y += frame.y()
        # 모든 anchor 의 캡션을 hit-test 대상으로 등록 — 호버/드래그 가능.
        # 보이는 (in_ms~out_ms 범위 내) 캡션만 등록해 안 보이는 캡션 클릭 방지.
        if c.in_ms <= self._position_ms < c.out_ms:
            self._caption_bboxes[c.id] = QRect(
                x - pad, y - text_h - pad, text_w + 2 * pad, text_h + 2 * pad,
            )
        # 실제 그리기는 frame 좌표에서 painter 를 translate 후 caption_renderer 호출 —
        # caption_renderer 는 surface 안에서 그리므로 translate 가 letterbox 보정.
        p.save()
        p.translate(frame.x(), frame.y())
        eff_for_draw = replace(c, position=position) if position is not c.position else c
        caption_renderer.draw_caption(
            p, eff_for_draw, position_ms=self._position_ms,
            surface_w=frame.width(), surface_h=frame.height(),
        )
        p.restore()

    # ---------- zoom guide (Stage 6) ----------
    def _draw_zoom_guide(self, p: QPainter, eff: ZoomEffect) -> None:
        """활성 ZoomEffect 의 영역을 노란 사각형으로 표시.

        v1: start.cx/cy/scale 만 사용 (정적 줌). 사각형의 중심은 영상 프레임 안의
        (cx*w, cy*h), 크기는 (w/scale, h/scale) — letterbox 가 있어도 영상 안에서만
        그려진다.
        """
        frame = self._frame_rect()
        w = max(1, frame.width())
        h = max(1, frame.height())
        # 드래그 중인 줌이면 override (cx, cy) 사용 — 즉시 사각형이 따라 움직임.
        cx_n = float(eff.start.cx)
        cy_n = float(eff.start.cy)
        if (self._drag_kind == "zoom"
                and self._drag_eff_id == eff.id
                and self._drag_override_norm is not None):
            cx_n, cy_n = self._drag_override_norm
        scale = max(0.1, float(eff.start.scale))
        cx_px = cx_n * w
        cy_px = cy_n * h
        rect_w = w / scale
        rect_h = h / scale
        rx = int(round(cx_px - rect_w / 2.0)) + frame.x()
        ry = int(round(cy_px - rect_h / 2.0)) + frame.y()
        rw = int(round(rect_w))
        rh = int(round(rect_h))
        # hit-test bbox 등록 — 그려진 순서대로 push.
        self._overlay_hits.append((QRect(rx, ry, rw, rh), "zoom", eff.id))
        # 외곽선만 (내부는 투명) — 사각형이 영상을 덮지 않도록.
        pen = QPen(_ZOOM_GUIDE_COLOR)
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(rx, ry, rw, rh)
        # 라벨 — 사각형 좌상단 안쪽에 작은 박스 + 텍스트.
        label = f"⊕ {eff.start.scale:g}×"
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(label)
        text_h = fm.height()
        pad = 4
        # 라벨 박스는 사각형의 좌상단 안쪽 (사각형이 너무 작으면 외부도 가능).
        lx = rx + 2
        ly = ry + 2
        p.fillRect(lx, ly, text_w + pad * 2, text_h + pad, _ZOOM_LABEL_BG)
        p.setPen(_ZOOM_LABEL_FG)
        p.drawText(lx + pad, ly, text_w + pad, text_h + pad,
                   Qt.AlignVCenter | Qt.AlignLeft, label)

    # ---------- broll PiP guide (Stage 7) ----------
    def _draw_broll_guide(self, p: QPainter, eff: BrollEffect) -> None:
        """활성 BrollEffect(PiP) 의 영역을 주황 사각형으로 표시.

        v1: 실제 영상 PiP 는 export 에서만 적용. 미리보기는 사각형 + 파일명 라벨.
        pip.pos_x / pos_y 가 둘 다 set 이면 corner 보다 우선 (자유 위치).
        eff.pip 가 None 이거나 placement='fullscreen' 이면 호출 측에서 미리 차단.
        """
        from pathlib import Path
        assert eff.pip is not None   # 호출자가 보장
        frame = self._frame_rect()
        w = max(1, frame.width())
        h = max(1, frame.height())
        ratio = max(0.05, min(0.9, float(eff.pip.size_ratio)))
        rect_w = int(round(w * ratio))
        rect_h = int(round(h * ratio))
        # 드래그 override > pos_x/pos_y > corner.
        if (self._drag_kind == "broll"
                and self._drag_eff_id == eff.id
                and self._drag_override_norm is not None):
            nx, ny = self._drag_override_norm
            rx = int(round(nx * w))
            ry = int(round(ny * h))
        elif eff.pip.pos_x is not None and eff.pip.pos_y is not None:
            rx = int(round(float(eff.pip.pos_x) * w))
            ry = int(round(float(eff.pip.pos_y) * h))
        else:
            m = _BROLL_MARGIN
            corner = eff.pip.corner
            if corner == "top-left":
                rx, ry = m, m
            elif corner == "top-right":
                rx, ry = w - rect_w - m, m
            elif corner == "bottom-left":
                rx, ry = m, h - rect_h - m
            else:   # bottom-right (기본)
                rx, ry = w - rect_w - m, h - rect_h - m
        # frame 좌표 → widget 좌표.
        rx += frame.x()
        ry += frame.y()
        # hit-test bbox 등록.
        self._overlay_hits.append((QRect(rx, ry, rect_w, rect_h), "broll", eff.id))

        # 채움 + 외곽선.
        p.fillRect(rx, ry, rect_w, rect_h, _BROLL_FILL_COLOR)
        pen = QPen(_BROLL_GUIDE_COLOR)
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(rx, ry, rect_w, rect_h)

        # 중앙 라벨 — 🎞 + 파일명 basename.
        basename = Path(eff.src).name if eff.src else ""
        label = f"🎞 {basename or '?'}"
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(_BROLL_LABEL_FG)
        p.drawText(rx, ry, rect_w, rect_h,
                   Qt.AlignCenter, label)

    # ---------- mouse (캡션·줌·곁들임 드래그) ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._sidecar is None:
            event.ignore()
            return
        pos = event.position().toPoint()
        frame = self._frame_rect()
        fw = max(1, frame.width())
        fh = max(1, frame.height())
        # 캡션 hit-test 우선 — 캡션 텍스트는 보통 가이드 위에 그려진다고 가정.
        for cid, bbox in reversed(list(self._caption_bboxes.items())):
            if bbox.contains(pos):
                self._drag_caption_id = cid
                self._drag_start_pos = pos
                cx = (bbox.left() + bbox.right()) / 2.0 - frame.x()
                cy = (bbox.top() + bbox.bottom()) / 2.0 - frame.y()
                self._drag_start_offset_norm = (cx / fw, cy / fh)
                self._drag_override_offset = self._drag_start_offset_norm
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        # 줌·곁들임 가이드 hit-test — 그려진 역순 (위에 있는 것 먼저).
        for bbox, kind, eff_id in reversed(self._overlay_hits):
            if not bbox.contains(pos):
                continue
            self._drag_kind = kind
            self._drag_eff_id = eff_id
            self._drag_start_pos = pos
            if kind == "zoom":
                # 줌은 사각형 중심 = (cx_norm * w + frame.x, ...).
                cx = (bbox.left() + bbox.right()) / 2.0 - frame.x()
                cy = (bbox.top() + bbox.bottom()) / 2.0 - frame.y()
                self._drag_start_norm = (cx / fw, cy / fh)
            else:
                # 곁들임은 좌상단 = (pos_x * w + frame.x, ...).
                self._drag_start_norm = (
                    (bbox.left() - frame.x()) / fw,
                    (bbox.top() - frame.y()) / fh,
                )
            self._drag_clamp = self._compute_drag_clamp(kind, eff_id)
            self._drag_override_norm = self._clamp_norm(self._drag_start_norm)
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        # hit 없음 → 하부 영상 surface 로 통과.
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._drag_caption_id is None and self._drag_kind is None:
            # 드래그 중 아니면 호버 커서 갱신: 캡션 / 가이드 위면 OpenHand.
            for bbox in self._caption_bboxes.values():
                if bbox.contains(pos):
                    self.setCursor(Qt.OpenHandCursor)
                    event.accept()
                    return
            for bbox, _kind, _id in self._overlay_hits:
                if bbox.contains(pos):
                    self.setCursor(Qt.OpenHandCursor)
                    event.accept()
                    return
            self.unsetCursor()
            event.ignore()
            return
        frame = self._frame_rect()
        fw = max(1, frame.width())
        fh = max(1, frame.height())
        delta_x = pos.x() - self._drag_start_pos.x()
        delta_y = pos.y() - self._drag_start_pos.y()
        if self._drag_caption_id is not None:
            new_x = max(0.0, min(1.0, self._drag_start_offset_norm[0] + delta_x / fw))
            new_y = max(0.0, min(1.0, self._drag_start_offset_norm[1] + delta_y / fh))
            self._drag_override_offset = (new_x, new_y)
        else:
            raw = (self._drag_start_norm[0] + delta_x / fw,
                   self._drag_start_norm[1] + delta_y / fh)
            self._drag_override_norm = self._clamp_norm(raw)
        self.update()
        event.accept()

    def _compute_drag_clamp(self, kind: str, eff_id: str) -> tuple[float, float, float, float]:
        """드래그 정규화 좌표 (사각형 표현 점) 의 허용 범위 계산.

        줌: cx, cy 가 사각형 중심 — 모서리가 frame 안에 있으려면
        cx ∈ [half_w, 1 - half_w], 같은 식으로 cy. half_w = 0.5/scale.
        scale < 1 (사각형이 frame 보다 큼) 인 경우 범위가 음수가 되는데, 그땐 0.5 로 잠금.

        곁들임: pos_x, pos_y 가 좌상단 — 우/하 모서리가 frame 안에 있으려면
        pos_x ∈ [0, 1 - size_ratio], 같은 식으로 pos_y.

        eff 를 못 찾으면 [0, 1] 폴백.
        """
        if self._sidecar is None:
            return (0.0, 1.0, 0.0, 1.0)
        eff = next((e for e in self._sidecar.effects if e.id == eff_id), None)
        if eff is None:
            return (0.0, 1.0, 0.0, 1.0)
        if kind == "zoom" and isinstance(eff, ZoomEffect):
            scale = max(0.1, float(eff.start.scale))
            half = 0.5 / scale
            if half >= 0.5:
                # 사각형이 frame 보다 크거나 같음 — 가운데로 잠금.
                return (0.5, 0.5, 0.5, 0.5)
            return (half, 1.0 - half, half, 1.0 - half)
        if kind == "broll" and isinstance(eff, BrollEffect) and eff.pip is not None:
            ratio = max(0.05, min(0.9, float(eff.pip.size_ratio)))
            return (0.0, 1.0 - ratio, 0.0, 1.0 - ratio)
        return (0.0, 1.0, 0.0, 1.0)

    def _clamp_norm(self, norm: tuple[float, float]) -> tuple[float, float]:
        """현재 _drag_clamp 로 정규화 좌표 를 잘라낸다."""
        xmin, xmax, ymin, ymax = self._drag_clamp
        nx = max(xmin, min(xmax, norm[0]))
        ny = max(ymin, min(ymax, norm[1]))
        return (nx, ny)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # 캡션 드래그 종료
        if self._drag_caption_id is not None:
            if self._sidecar is not None and self._drag_override_offset is not None:
                for eff in self._sidecar.effects:
                    if eff.id == self._drag_caption_id and eff.type == "caption":
                        new_pos = Position(anchor="free",
                                           offset_x=self._drag_override_offset[0],
                                           offset_y=self._drag_override_offset[1])
                        new_eff = replace(eff, position=new_pos)
                        self.caption_position_changed.emit(new_eff)
                        break
            self._drag_caption_id = None
            self._drag_start_pos = None
            self._drag_override_offset = None
            self.unsetCursor()
            event.accept()
            return
        # 줌·곁들임 드래그 종료
        if self._drag_kind is not None and self._sidecar is not None:
            kind = self._drag_kind
            eff_id = self._drag_eff_id
            override = self._drag_override_norm
            self._drag_kind = None
            self._drag_eff_id = None
            self._drag_start_pos = None
            self._drag_override_norm = None
            self.unsetCursor()
            if override is not None:
                for eff in self._sidecar.effects:
                    if eff.id != eff_id:
                        continue
                    new_eff = self._apply_drag_to_effect(kind, eff, override)
                    if new_eff is not None:
                        self.effect_drag_changed.emit(new_eff)
                    break
            event.accept()
            return
        event.ignore()

    def _apply_drag_to_effect(self, kind: str, eff, norm: tuple[float, float]):
        """드래그 결과 정규화 좌표를 effect 에 반영한 새 effect 반환. 실패면 None."""
        nx, ny = norm
        if kind == "zoom" and isinstance(eff, ZoomEffect):
            new_start = replace(eff.start, cx=nx, cy=ny)
            new_end = replace(eff.end, cx=nx, cy=ny)
            return replace(eff, start=new_start, end=new_end)
        if kind == "broll" and isinstance(eff, BrollEffect) and eff.pip is not None:
            new_pip = replace(eff.pip, pos_x=nx, pos_y=ny)
            return replace(eff, pip=new_pip)
        return None

