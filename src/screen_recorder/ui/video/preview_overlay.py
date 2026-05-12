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

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent, QFont, QImage, QMouseEvent,
    QPainter, QPaintEvent, QPen,
)
from PySide6.QtWidgets import QWidget

from ...effects import Sidecar
from ...effects.types.broll import BrollEffect
from ...effects.types.arrow import ArrowEffect
from ...effects.types.caption import CaptionEffect, Position
from . import arrow_renderer
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

# Stage 2 (2026-05-08) — 공통 모서리 리사이즈 핸들 (zoom/broll 공유).
_HANDLE_SIZE = 10        # 시각 그리기용 (작게)
_HANDLE_HIT_SIZE = 24    # hit-test 용 (사용자가 모서리 근처 클릭 시도 흡수). Phase 19.5
                         # 사용자 보고 — 시각 10x10 만 hit 으로 두면 정확히 안 누르면
                         # 박스 본체 drag 로 처리되어 위치가 같이 움직임.
_HANDLE_FILL = QColor(255, 255, 255, 240)
_HANDLE_BORDER = QColor(20, 20, 20, 220)
_CORNERS = ("tl", "tr", "bl", "br")


def _corner_rects(box: QRect, size: int = _HANDLE_HIT_SIZE) -> dict[str, QRect]:
    """box 의 네 모서리에 핸들 사각형. 기본 size 는 hit-test 용 (24x24).

    시각 그리기 시엔 _draw_corner_handles 가 size=_HANDLE_SIZE 명시.
    """
    half = size // 2
    return {
        "tl": QRect(box.left() - half, box.top() - half, size, size),
        "tr": QRect(box.right() - half, box.top() - half, size, size),
        "bl": QRect(box.left() - half, box.bottom() - half, size, size),
        "br": QRect(box.right() - half, box.bottom() - half, size, size),
    }


def _cursor_for_corner(c: str) -> Qt.CursorShape:
    """tl/br = ↘ (FDiag), tr/bl = ↙ (BDiag)."""
    return {
        "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
    }.get(c, Qt.ArrowCursor)


def _draw_corner_handles(p: QPainter, box: QRect) -> None:
    """box 네 모서리에 흰 사각 핸들 그림 (시각 — 작은 10x10)."""
    for r in _corner_rects(box, size=_HANDLE_SIZE).values():
        p.fillRect(r, _HANDLE_FILL)
        p.setPen(QPen(_HANDLE_BORDER, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)


class PreviewOverlay(QWidget):
    """투명 위젯 — paintEvent 에서 캡션을 그린다.

    어느 anchor 든 캡션은 화면 위에서 드래그 가능. 드래그 시작 시 자동으로
    anchor='free' 로 전환됨. 캡션 외 영역의 마우스 이벤트는 ignore() 통과.
    """

    caption_position_changed = Signal(object)   # CaptionEffect — 드래그 후 새 position
    effect_drag_changed = Signal(object)        # ZoomEffect / BrollEffect — 드래그 후 갱신
    # Phase 19.4: 영상 위 박스를 클릭하면 그 effect 가 활성 선택이 되어 Del 키로 삭제 가능.
    # None = 빈 영역 클릭(선택 해제). 핸들·박스·캡션 hit 모두 emit.
    overlay_effect_clicked = Signal(object)     # Effect | None
    # Phase 19.5: broll PIP 박스 위에 외부 파일을 드롭하면 그 box 의 src 가 갱신됨.
    overlay_broll_file_dropped = Signal(str, str)   # (effect_id, path)

    def __init__(self) -> None:
        super().__init__()
        # WA_TransparentForMouseEvents 를 끄고 hit-test 로 직접 처리해야 캡션
        # 드래그가 가능. 비-hit 영역은 mousePressEvent 에서 ignore() → 부모로 전달.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 호버 커서 변경 위해 mouseTracking ON.
        self.setMouseTracking(True)
        # broll PIP 박스 위에 외부 파일 드롭 가능 (Phase 19.5).
        self.setAcceptDrops(True)
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
        # Stage 2: 모서리 리사이즈 모드 — drag_kind 와 동시 활성 안 함.
        # resize_corner in _CORNERS, resize_kind in {"zoom","broll"}.
        self._resize_corner: Optional[str] = None
        self._resize_kind: Optional[str] = None
        self._resize_eff_id: Optional[str] = None
        self._resize_start_pos = None        # QPoint (영상 좌표)
        # 리사이즈 시작 시점의 box 원본 (화면 widget 좌표 기준).
        self._resize_orig_box: Optional[QRect] = None
        # 리사이즈 중인 새 (cx_norm, cy_norm, scale_or_ratio) 임시 override.
        # zoom 일 땐 (cx, cy, scale), broll 일 땐 (pos_x, pos_y, size_ratio).
        self._resize_override: Optional[tuple[float, float, float]] = None
        # 드래그 정규화 좌표의 허용 범위 (xmin, xmax, ymin, ymax) — 사각형의 모서리가
        # 영상 frame 안에 머물도록 효과별 크기를 고려해 mousePress 시 계산.
        # 줌(scale=2) → cx/cy 가능 범위 = [0.25, 0.75], 곁들임(size_ratio=0.3) → pos_x/y = [0, 0.7].
        self._drag_clamp: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0)
        # 영상 프레임 rect provider — letterbox 시 검은 띠를 제외한 실제 영상 영역.
        # None 이면 self.rect() (위젯 전체) 사용. 이 rect 안에서만 그리고 드래그한다.
        self._frame_rect_provider: Optional[Callable[[], QRect]] = None
        # 영상 source 픽셀 크기 provider — caption painter scale 용. None / (0,0) 이면
        # 기존 frame 좌표계로 fallback (테스트 / 영상 미로딩 호환).
        self._source_size_provider: Optional[Callable[[], tuple[int, int]]] = None
        # broll PIP 가이드 안에 표시할 대표 썸네일 (src path 별). VideoTab 이 채워줌.
        self._broll_thumbs: dict[str, "QImage"] = {}
        # broll PIP 실시간 frame (effect_id 별). BrollPipPlayer.frame_ready 가 채움.
        # thumbnail 보다 우선 — 없으면 thumbnail, 둘 다 없으면 주황 fill (3단 fallback).
        self._broll_live_frames: dict[str, "QImage"] = {}
        # paintEvent 의 마지막 호출 시각 — 5× 같은 고배속에서 매 position tick 마다
        # update() 호출하면 paint 가 30Hz 이상으로 폭주해 누적 부하 발생. wall-clock
        # 33ms 이내의 연속 호출은 합쳐 paint 1 회로 (사용자가 인지하는 부드러움은 유지).
        self._last_paint_request_ms: int = 0
        self._paint_throttle = QTimer(self)
        self._paint_throttle.setSingleShot(True)
        self._paint_throttle.timeout.connect(self.update)

    # ---------- public ----------
    def set_sidecar(self, sc: Optional[Sidecar]) -> None:
        self._sidecar = sc
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self._request_paint()

    def _request_paint(self) -> None:
        """30Hz 캡 update() — 직전 paint 로부터 33ms 이상 지났으면 즉시,
        아니면 짧은 타이머로 합침."""
        from PySide6.QtCore import QDateTime
        now = QDateTime.currentMSecsSinceEpoch()
        elapsed = now - self._last_paint_request_ms
        if elapsed >= 33:
            self._last_paint_request_ms = now
            self.update()
        elif not self._paint_throttle.isActive():
            self._paint_throttle.start(33 - elapsed)

    def set_broll_thumbnail(self, src: str, img: Optional[QImage]) -> None:
        """broll PIP 가이드 안에 그릴 대표 썸네일을 src 단위로 저장. 빈 src 면 no-op.

        VideoTab 이 ThumbnailService 결과를 받아 호출. 같은 src 면 덮어쓰기.
        """
        if not src or img is None or img.isNull():
            return
        self._broll_thumbs[str(src)] = img
        self.update()

    def set_broll_live_frame(self, effect_id: str, img: Optional[QImage]) -> None:
        """BrollPipPlayer.frame_ready 의 최신 frame 을 effect_id 단위로 저장.

        thumbnail 보다 우선 표시. 빈 id 또는 null QImage 는 no-op (방어).
        """
        if not effect_id or img is None or img.isNull():
            return
        self._broll_live_frames[str(effect_id)] = img
        self._request_paint()

    def clear_broll_live_frame(self, effect_id: str) -> None:
        """시간창 이탈 시 호출. cache 비움 → thumbnail fallback 으로 복귀."""
        self._broll_live_frames.pop(str(effect_id), None)
        self.update()

    def set_video_frame_rect_provider(self, fn: Optional[Callable[[], QRect]]) -> None:
        """영상 프레임 rect (letterbox 영역 제외) 를 매번 조회하는 콜백 설치.

        호출자(VideoTab) 가 player.video_frame_rect 를 lambda 로 넘긴다.
        None 이면 위젯 전체를 영상 프레임으로 간주 (테스트 호환).
        """
        self._frame_rect_provider = fn

    def set_video_source_size_provider(self, fn: Optional[Callable[[], tuple[int, int]]]) -> None:
        """현재 영상의 source 픽셀 (w, h) provider. 캡션 painter scale 에 사용.

        font 가 절대 px 라 surface 크기에 따라 bbox spread 가 달라지던 회귀의 fix —
        preview 가 export 와 같은 source 좌표계에서 그리고 painter scale 로 frame 에
        맞춤. 결과: 창모드/풀스크린/export 모두 캡션이 같은 *상대 위치*에 표시.
        None 이거나 (0, 0) 반환 시 기존 frame 좌표계 사용 (테스트 / 영상 없을 때).
        """
        self._source_size_provider = fn
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

        # 화살표 — caption 과 같은 painter scale 패턴 (source 좌표계).
        for eff in self._sidecar.effects:
            if eff.type != "arrow":
                continue
            self._draw_arrow_effect(p, eff)

        # Stage 6 — 활성 ZoomEffect 가 있으면 가이드 사각형 그리기.
        # v1: 실제 픽셀 줌은 export 에서만 적용. 미리보기는 사각형으로 영역 표시.
        # Phase 19.4: preview=True (실제 화면 줌인 적용) 이면 가이드 박스 자체는 숨김 —
        # 화면이 이미 줌인되어 있어 외곽선이 보이면 시각적 혼동.
        for eff in self._sidecar.effects:
            if not isinstance(eff, ZoomEffect):
                continue
            if not (eff.in_ms <= self._position_ms < eff.out_ms):
                continue
            if getattr(eff, "preview", False):
                continue
            self._draw_zoom_guide(p, eff)

        # Phase 19.4 (2026-05-11): BrollEffect 가이드는 in_ms ~ out_ms 시간창 안에서만 표시.
        # 이전 Stage 4 (항상 미리보기) 결정은 뒤집힘 — 사용자가 "곁들임 영상이 없는 구간에서도
        # 테두리가 떠 있다" 며 반전 요구. 시간 범위 안에 들어가면 가이드 외곽선이 더 진한
        # 강조 색으로 바뀌어 "지금 재생 중" 임을 시각화 (강조 처리는 _draw_broll_guide 내부).
        for eff in self._sidecar.effects:
            if not isinstance(eff, BrollEffect):
                continue
            if eff.placement != "pip" or eff.pip is None:
                continue
            if not (eff.in_ms <= self._position_ms < eff.out_ms):
                continue
            self._draw_broll_guide(p, eff)

    def _draw_caption(self, p: QPainter, c: CaptionEffect) -> None:
        # 드래그 중인 경우 임시 override position 사용
        position = c.position
        if c.id == self._drag_caption_id and self._drag_override_offset is not None:
            position = Position(anchor="free",
                                offset_x=self._drag_override_offset[0],
                                offset_y=self._drag_override_offset[1])

        frame = self._frame_rect()
        # source 좌표계 결정 — provider 가 (w, h) 반환하면 그 픽셀 공간에서 그린 뒤
        # painter scale 로 frame 에 맞춤. 없으면 (legacy) frame 픽셀 공간에서 직접.
        src_size = self._source_size_provider() if self._source_size_provider else (0, 0)
        source_w, source_h = src_size
        if source_w > 0 and source_h > 0 and frame.width() > 0 and frame.height() > 0:
            # source 좌표계에서 그리기 (export 와 동일). scale 은 frame/source 비율.
            surface_w = source_w
            surface_h = source_h
            scale_x = frame.width() / source_w
            scale_y = frame.height() / source_h
        else:
            # 영상 size 미정 — 기존 frame 좌표계.
            surface_w = max(1, frame.width())
            surface_h = max(1, frame.height())
            scale_x = 1.0
            scale_y = 1.0

        # 텍스트 측정 — caption_renderer.measure_text 와 동일 (multi-line 의 max line
        # width × total height). 이전엔 single-line `fm.horizontalAdvance(c.text)` /
        # `fm.height()` 를 써서 multi-line 캡션의 bbox 가 첫 줄만 잡혀 drag 시 정확하지
        # 않던 회귀.
        text_w, text_h = caption_renderer.measure_text(c)
        pad = 8

        # anchor_xy 는 surface (source 또는 frame) 좌표계의 (x, y) 반환.
        x_src, y_src = caption_renderer.anchor_xy(
            position, text_w=text_w, text_h=text_h, pad=pad,
            surface_w=surface_w, surface_h=surface_h,
        )
        if position.anchor != "free":
            x_src += int(position.offset_x)
            y_src += int(position.offset_y)

        # hit-test bbox 는 위젯(widget) 좌표 — mouse event 가 그 공간이므로 scale 변환.
        if c.in_ms <= self._position_ms < c.out_ms:
            bbox_left = frame.x() + (x_src - pad) * scale_x
            bbox_top = frame.y() + (y_src - text_h - pad) * scale_y
            bbox_w = (text_w + 2 * pad) * scale_x
            bbox_h = (text_h + 2 * pad) * scale_y
            self._caption_bboxes[c.id] = QRect(
                int(bbox_left), int(bbox_top), int(bbox_w), int(bbox_h),
            )

        # 그리기 — frame.x/y 평행이동 후 source→frame scale.
        p.save()
        p.translate(frame.x(), frame.y())
        p.scale(scale_x, scale_y)
        eff_for_draw = replace(c, position=position) if position is not c.position else c
        caption_renderer.draw_caption(
            p, eff_for_draw, position_ms=self._position_ms,
            surface_w=surface_w, surface_h=surface_h,
        )
        p.restore()

    def _draw_arrow_effect(self, p: QPainter, a: ArrowEffect) -> None:
        """화살표 — caption 과 동일 좌표계 패턴 (painter scale 로 source 공간)."""
        frame = self._frame_rect()
        src_size = self._source_size_provider() if self._source_size_provider else (0, 0)
        source_w, source_h = src_size
        if source_w > 0 and source_h > 0 and frame.width() > 0 and frame.height() > 0:
            surface_w = source_w
            surface_h = source_h
            scale_x = frame.width() / source_w
            scale_y = frame.height() / source_h
        else:
            surface_w = max(1, frame.width())
            surface_h = max(1, frame.height())
            scale_x = 1.0
            scale_y = 1.0
        p.save()
        p.translate(frame.x(), frame.y())
        p.scale(scale_x, scale_y)
        arrow_renderer.draw_arrow(
            p, a, position_ms=self._position_ms,
            surface_w=surface_w, surface_h=surface_h,
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
        # 드래그/리사이즈 override 적용 우선순위: resize > drag > effect 원본.
        cx_n = float(eff.start.cx)
        cy_n = float(eff.start.cy)
        scale = max(0.1, float(eff.start.scale))
        if (self._resize_kind == "zoom" and self._resize_eff_id == eff.id
                and self._resize_override is not None):
            cx_n, cy_n, scale = self._resize_override
        elif (self._drag_kind == "zoom" and self._drag_eff_id == eff.id
                and self._drag_override_norm is not None):
            cx_n, cy_n = self._drag_override_norm
        cx_px = cx_n * w
        cy_px = cy_n * h
        rect_w = w / max(0.1, scale)
        rect_h = h / max(0.1, scale)
        rx = int(round(cx_px - rect_w / 2.0)) + frame.x()
        ry = int(round(cy_px - rect_h / 2.0)) + frame.y()
        rw = int(round(rect_w))
        rh = int(round(rect_h))
        # hit-test bbox 등록 — 그려진 순서대로 push (이론적 사각형 크기, 시각적 inset 전).
        self._overlay_hits.append((QRect(rx, ry, rw, rh), "zoom", eff.id))
        # 외곽선만 (내부는 투명) — 사각형이 영상을 덮지 않도록.
        pen = QPen(_ZOOM_GUIDE_COLOR)
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(rx + 1, ry + 1, max(1, rw - 2), max(1, rh - 2))
        # Stage 2: 네 모서리에 리사이즈 핸들.
        # 자유 이동 중(드래그로 박스 위치 변경) 에는 핸들이 따라다니면 어색하므로 숨김.
        is_moving = (self._drag_kind == "zoom" and self._drag_eff_id == eff.id)
        if not is_moving:
            _draw_corner_handles(p, QRect(rx, ry, rw, rh))
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
        # 리사이즈 override 가 있으면 임시 ratio 적용.
        if (self._resize_kind == "broll" and self._resize_eff_id == eff.id
                and self._resize_override is not None):
            nx, ny, ratio = self._resize_override
            rx = int(round(nx * w))
            ry = int(round(ny * h))
        elif (self._drag_kind == "broll"
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
                rx, ry = w - int(round(w * ratio)) - m, m
            elif corner == "bottom-left":
                rx, ry = m, h - int(round(h * ratio)) - m
            else:   # bottom-right (기본)
                rx, ry = w - int(round(w * ratio)) - m, h - int(round(h * ratio)) - m
        rect_w = int(round(w * ratio))
        rect_h = int(round(h * ratio))
        # frame 좌표 → widget 좌표.
        rx += frame.x()
        ry += frame.y()
        # hit-test bbox 등록.
        self._overlay_hits.append((QRect(rx, ry, rect_w, rect_h), "broll", eff.id))

        # 우선순위: live frame (실시간 재생) > thumbnail (정지 프레임) > 주황 fill.
        live = self._broll_live_frames.get(eff.id)
        if live is not None and not live.isNull():
            p.drawImage(QRect(rx, ry, rect_w, rect_h), live)
        else:
            thumb = self._broll_thumbs.get(eff.src) if eff.src else None
            if thumb is not None and not thumb.isNull():
                p.drawImage(QRect(rx, ry, rect_w, rect_h), thumb)
            else:
                p.fillRect(rx, ry, rect_w, rect_h, _BROLL_FILL_COLOR)
        pen = QPen(_BROLL_GUIDE_COLOR)
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(rx + 1, ry + 1, max(1, rect_w - 2), max(1, rect_h - 2))
        # Stage 2: 모서리 리사이즈 핸들. 자유 이동 중에는 숨김.
        is_moving = (self._drag_kind == "broll" and self._drag_eff_id == eff.id)
        if not is_moving:
            _draw_corner_handles(p, QRect(rx, ry, rect_w, rect_h))

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

    # ---------- mouse (캡션·줌·곁들임 드래그/리사이즈) ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._sidecar is None:
            event.ignore()
            return
        pos = event.position().toPoint()
        frame = self._frame_rect()
        fw = max(1, frame.width())
        fh = max(1, frame.height())
        # 1. 가이드 모서리 핸들 hit-test (zoom/broll) — 박스 안 hit 보다 우선.
        for bbox, kind, eff_id in reversed(self._overlay_hits):
            for c, hr in _corner_rects(bbox).items():
                if hr.contains(pos):
                    self._resize_corner = c
                    self._resize_kind = kind
                    self._resize_eff_id = eff_id
                    self._resize_start_pos = pos
                    self._resize_orig_box = QRect(bbox)
                    self._resize_override = self._initial_resize_override(kind, eff_id)
                    self.setCursor(_cursor_for_corner(c))
                    self._emit_effect_clicked(eff_id)
                    event.accept()
                    return
        # 2. 캡션 hit-test.
        for cid, bbox in reversed(list(self._caption_bboxes.items())):
            if bbox.contains(pos):
                self._drag_caption_id = cid
                self._drag_start_pos = pos
                # drag start 의 normalized 중심점. free 캡션이면 사이드카의 offset
                # 을 그대로 사용 — bbox 중심 round-trip (int 트런케이션, 9-zone↔free
                # 변환 시 text_h/pad 차이) 으로 인한 위치 점프 회피.
                cap_eff = next(
                    (e for e in self._sidecar.effects if e.id == cid),
                    None,
                )
                if (cap_eff is not None and cap_eff.type == "caption"
                        and cap_eff.position.anchor == "free"):
                    self._drag_start_offset_norm = (
                        float(cap_eff.position.offset_x),
                        float(cap_eff.position.offset_y),
                    )
                else:
                    cx = (bbox.left() + bbox.right()) / 2.0 - frame.x()
                    cy = (bbox.top() + bbox.bottom()) / 2.0 - frame.y()
                    self._drag_start_offset_norm = (cx / fw, cy / fh)
                self._drag_override_offset = self._drag_start_offset_norm
                self.setCursor(Qt.ClosedHandCursor)
                self._emit_effect_clicked(cid)
                event.accept()
                return
        # 3. 줌·곁들임 박스 본체 (이동) hit-test.
        for bbox, kind, eff_id in reversed(self._overlay_hits):
            if not bbox.contains(pos):
                continue
            self._drag_kind = kind
            self._drag_eff_id = eff_id
            self._drag_start_pos = pos
            if kind == "zoom":
                cx = (bbox.left() + bbox.right()) / 2.0 - frame.x()
                cy = (bbox.top() + bbox.bottom()) / 2.0 - frame.y()
                self._drag_start_norm = (cx / fw, cy / fh)
            else:
                self._drag_start_norm = (
                    (bbox.left() - frame.x()) / fw,
                    (bbox.top() - frame.y()) / fh,
                )
            self._drag_clamp = self._compute_drag_clamp(kind, eff_id)
            self._drag_override_norm = self._clamp_norm(self._drag_start_norm)
            self.setCursor(Qt.ClosedHandCursor)
            self._emit_effect_clicked(eff_id)
            event.accept()
            return
        # hit 없음 → 활성 선택 해제 후 하부 영상 surface 로 통과.
        self.overlay_effect_clicked.emit(None)
        event.ignore()

    def _emit_effect_clicked(self, eff_id: str) -> None:
        """id 로 effect 찾아 overlay_effect_clicked 발화. 없으면 no-op."""
        if self._sidecar is None:
            return
        eff = next((e for e in self._sidecar.effects if e.id == eff_id), None)
        if eff is not None:
            self.overlay_effect_clicked.emit(eff)

    # ---------- drag-and-drop (broll PIP 박스 위 파일 드롭) ----------
    @staticmethod
    def _first_supported_path(urls) -> Optional[str]:
        # BrollInspector 와 같은 확장자 화이트리스트.
        accepted = {".mp4", ".mov", ".avi", ".gif", ".png", ".jpg",
                    ".jpeg", ".mkv", ".webm"}
        from pathlib import Path
        for u in urls:
            if not u.isLocalFile():
                continue
            p = u.toLocalFile()
            if Path(p).suffix.lower() in accepted:
                return p
        return None

    def _broll_hit_at(self, pos) -> Optional[str]:
        """pos 좌표에서 broll 박스 hit — effect id 반환, 없으면 None."""
        for bbox, kind, eff_id in reversed(self._overlay_hits):
            if kind == "broll" and bbox.contains(pos):
                return eff_id
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        md = event.mimeData()
        if not md.hasUrls() or self._first_supported_path(md.urls()) is None:
            event.ignore()
            return
        if self._broll_hit_at(event.position().toPoint()) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        # 박스 위를 벗어나면 거절 (커서가 stop 모양으로).
        if self._broll_hit_at(event.position().toPoint()) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        pos = event.position().toPoint()
        eff_id = self._broll_hit_at(pos)
        if eff_id is None:
            event.ignore()
            return
        path = self._first_supported_path(event.mimeData().urls())
        if path is None:
            event.ignore()
            return
        self.overlay_broll_file_dropped.emit(eff_id, path)
        event.acceptProposedAction()

    def _initial_resize_override(self, kind: str, eff_id: str) -> "tuple[float, float, float]":
        """리사이즈 시작 시점의 효과 기존값 → resize_override 초기화."""
        if self._sidecar is None:
            return (0.5, 0.5, 1.0)
        eff = next((e for e in self._sidecar.effects if e.id == eff_id), None)
        if eff is None:
            return (0.5, 0.5, 1.0)
        if kind == "zoom" and isinstance(eff, ZoomEffect):
            return (float(eff.start.cx), float(eff.start.cy), float(eff.start.scale))
        if kind == "broll" and isinstance(eff, BrollEffect) and eff.pip is not None:
            px = float(eff.pip.pos_x) if eff.pip.pos_x is not None else 0.0
            py = float(eff.pip.pos_y) if eff.pip.pos_y is not None else 0.0
            return (px, py, float(eff.pip.size_ratio))
        return (0.5, 0.5, 1.0)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if (self._drag_caption_id is None and self._drag_kind is None
                and self._resize_corner is None):
            # 드래그/리사이즈 안 함 — 호버 커서.
            # 코너 핸들 위 호버 → 사이즈 커서 (가장 위 hit 우선).
            for bbox, _kind, _id in reversed(self._overlay_hits):
                for c, hr in _corner_rects(bbox).items():
                    if hr.contains(pos):
                        self.setCursor(_cursor_for_corner(c))
                        event.accept()
                        return
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
        # 리사이즈 중 우선 처리.
        if self._resize_corner is not None:
            self._update_resize_override(pos)
            self.update()
            event.accept()
            return
        frame = self._frame_rect()
        fw = max(1, frame.width())
        fh = max(1, frame.height())
        delta_x = pos.x() - self._drag_start_pos.x()
        delta_y = pos.y() - self._drag_start_pos.y()
        if self._drag_caption_id is not None:
            raw_x = self._drag_start_offset_norm[0] + delta_x / fw
            raw_y = self._drag_start_offset_norm[1] + delta_y / fh
            # anchor 좌표만 [0, 1] 클램프하면 free 의 텍스트 *중심* 가정 때문에 절반이
            # 화면 밖으로 나감. 텍스트 bbox 가 frame 안에 머물도록 measure 후 clamp.
            # 측정 / 클램프 모두 source 좌표계 (caption_renderer 와 일관) — frame 픽셀
            # 기반이면 창 크기에 따라 클램프 결과가 달라짐.
            cap_eff = next(
                (e for e in self._sidecar.effects if e.id == self._drag_caption_id),
                None,
            ) if self._sidecar is not None else None
            if cap_eff is not None and cap_eff.type == "caption":
                tw, th = caption_renderer.measure_text(cap_eff)
                src_size = self._source_size_provider() if self._source_size_provider else (0, 0)
                if src_size[0] > 0 and src_size[1] > 0:
                    cw, ch = src_size
                else:
                    cw, ch = fw, fh
                new_x, new_y = caption_renderer.clamp_free_offset(
                    tw, th, cw, ch, raw_x, raw_y,
                )
            else:
                new_x = max(0.0, min(1.0, raw_x))
                new_y = max(0.0, min(1.0, raw_y))
            self._drag_override_offset = (new_x, new_y)
        else:
            raw = (self._drag_start_norm[0] + delta_x / fw,
                   self._drag_start_norm[1] + delta_y / fh)
            self._drag_override_norm = self._clamp_norm(raw)
        self.update()
        event.accept()

    def _update_resize_override(self, pos) -> None:
        """모서리 드래그 → 새 (cx/cy/scale) 또는 (pos_x/y/size_ratio) 계산.

        zoom·broll 둘 다 **대각 반대편 anchor** — 잡은 모서리의 대각 끝점이 고정,
        잡은 쪽 모서리가 마우스를 따라옴. 사용자 결정 (2026-05-11 Phase 19.5):
        일반적인 리사이즈 동작과 일치 (Photoshop / 도형 핸들 등). 박스가 같이 옮겨지는
        것은 의도된 동작 — 모서리를 잡고 끌면 그 모서리만 움직이는 게 자연스러움.

        zoom 은 cx,cy = 박스 중심이므로 새 중심을 다시 계산. broll 은 pos_x,pos_y =
        좌상단이라 그대로 사용.
        """
        if self._resize_orig_box is None or self._resize_kind is None:
            return
        frame = self._frame_rect()
        fw = max(1, frame.width())
        fh = max(1, frame.height())
        orig = self._resize_orig_box
        if self._resize_kind == "zoom":
            # zoom 은 scale 하나로 표현 → paint 시 박스 종횡비가 frame 의 것으로 강제됨.
            # 따라서 corner anchor + 종횡비 매칭 둘 다 필요. mouse 가 임의 비율로 가도
            # 박스는 frame 종횡비 유지하면서 잡은 corner 의 대각 anchor 점을 고정.
            aspect = fw / max(1.0, fh)
            if self._resize_corner == "br":
                anchor = (orig.left(), orig.top())
                raw_w = max(8.0, pos.x() - anchor[0])
                raw_h = max(8.0, pos.y() - anchor[1])
            elif self._resize_corner == "tr":
                anchor = (orig.left(), orig.bottom())
                raw_w = max(8.0, pos.x() - anchor[0])
                raw_h = max(8.0, anchor[1] - pos.y())
            elif self._resize_corner == "bl":
                anchor = (orig.right(), orig.top())
                raw_w = max(8.0, anchor[0] - pos.x())
                raw_h = max(8.0, pos.y() - anchor[1])
            else:   # tl
                anchor = (orig.right(), orig.bottom())
                raw_w = max(8.0, anchor[0] - pos.x())
                raw_h = max(8.0, anchor[1] - pos.y())
            # 종횡비 강제 — outer max (박스가 mouse 위치를 포함하도록 확장).
            if raw_w / aspect >= raw_h:
                new_w = raw_w
                new_h = raw_w / aspect
            else:
                new_h = raw_h
                new_w = raw_h * aspect
            # corner 별 box 좌상단 계산 — anchor 가 고정 끝점.
            if self._resize_corner == "br":
                new_left, new_top = anchor[0], anchor[1]
            elif self._resize_corner == "tr":
                new_left, new_top = anchor[0], anchor[1] - new_h
            elif self._resize_corner == "bl":
                new_left, new_top = anchor[0] - new_w, anchor[1]
            else:   # tl
                new_left, new_top = anchor[0] - new_w, anchor[1] - new_h
            # frame 안 clamp — 한쪽 벗어나면 그쪽 크기 줄임. 종횡비 재강제.
            if new_left < frame.left():
                new_w -= (frame.left() - new_left)
                new_left = frame.left()
            if new_top < frame.top():
                new_h -= (frame.top() - new_top)
                new_top = frame.top()
            if new_left + new_w > frame.right():
                new_w = frame.right() - new_left
            if new_top + new_h > frame.bottom():
                new_h = frame.bottom() - new_top
            new_w = max(8.0, new_w)
            new_h = max(8.0, new_h)
            if new_w / aspect < new_h:
                new_h = new_w / aspect
            else:
                new_w = new_h * aspect
            # 새 중심 + scale.
            new_cx_px = new_left + new_w / 2.0
            new_cy_px = new_top + new_h / 2.0
            cx_n = (new_cx_px - frame.x()) / fw
            cy_n = (new_cy_px - frame.y()) / fh
            scale = max(0.1, fw / max(1.0, new_w))
            cx_n = max(0.0, min(1.0, cx_n))
            cy_n = max(0.0, min(1.0, cy_n))
            self._resize_override = (cx_n, cy_n, scale)
            return
        # broll — frame 종횡비 강제. _draw_broll_guide 가 rect_h = h × ratio,
        # rect_w = w × ratio 로 그려서 시각상 항상 frame 비율이므로 resize 수학도
        # 그에 맞춰야 대각 anchor 가 정확히 고정된다. (이전: new_w / new_h 따로
        # 계산 후 ratio = new_w / fw 만 저장 → 화면상 height 가 따라 변하면서
        # 대각 모서리의 y 좌표가 함께 이동하던 회귀.)
        aspect = fw / max(1.0, fh)
        if self._resize_corner == "br":
            anchor = (orig.left(), orig.top())
            raw_w = max(8.0, pos.x() - anchor[0])
            raw_h = max(8.0, pos.y() - anchor[1])
        elif self._resize_corner == "tr":
            anchor = (orig.left(), orig.bottom())
            raw_w = max(8.0, pos.x() - anchor[0])
            raw_h = max(8.0, anchor[1] - pos.y())
        elif self._resize_corner == "bl":
            anchor = (orig.right(), orig.top())
            raw_w = max(8.0, anchor[0] - pos.x())
            raw_h = max(8.0, pos.y() - anchor[1])
        else:   # tl
            anchor = (orig.right(), orig.bottom())
            raw_w = max(8.0, anchor[0] - pos.x())
            raw_h = max(8.0, anchor[1] - pos.y())
        # 종횡비 강제 — 마우스 위치 포함하도록 outer max (zoom 과 동일 패턴).
        if raw_w / aspect >= raw_h:
            new_w = raw_w
            new_h = raw_w / aspect
        else:
            new_h = raw_h
            new_w = raw_h * aspect
        # corner 별 new_left/new_top 계산 — anchor 가 고정 끝점.
        if self._resize_corner == "br":
            new_left, new_top = anchor[0], anchor[1]
        elif self._resize_corner == "tr":
            new_left, new_top = anchor[0], anchor[1] - new_h
        elif self._resize_corner == "bl":
            new_left, new_top = anchor[0] - new_w, anchor[1]
        else:   # tl
            new_left, new_top = anchor[0] - new_w, anchor[1] - new_h
        # frame 안 clamp — 한쪽 벗어나면 그쪽 크기 줄임. 종횡비 재강제.
        if new_left < frame.left():
            new_w -= (frame.left() - new_left)
            new_left = frame.left()
        if new_top < frame.top():
            new_h -= (frame.top() - new_top)
            new_top = frame.top()
        if new_left + new_w > frame.right():
            new_w = frame.right() - new_left
        if new_top + new_h > frame.bottom():
            new_h = frame.bottom() - new_top
        new_w = max(8.0, new_w)
        new_h = max(8.0, new_h)
        if new_w / aspect < new_h:
            new_h = new_w / aspect
        else:
            new_w = new_h * aspect
        ratio = max(0.05, min(0.9, new_w / fw))
        # ratio 가 clamp 된 경우 new_w/new_h 재계산 — anchor 우선 유지.
        clamped_w = ratio * fw
        clamped_h = ratio * fh
        if self._resize_corner == "br":
            new_left, new_top = anchor[0], anchor[1]
        elif self._resize_corner == "tr":
            new_left, new_top = anchor[0], anchor[1] - clamped_h
        elif self._resize_corner == "bl":
            new_left, new_top = anchor[0] - clamped_w, anchor[1]
        else:   # tl
            new_left, new_top = anchor[0] - clamped_w, anchor[1] - clamped_h
        px_n = (new_left - frame.x()) / fw
        py_n = (new_top - frame.y()) / fh
        px_n = max(0.0, min(1.0 - ratio, px_n))
        py_n = max(0.0, min(1.0 - ratio, py_n))
        self._resize_override = (px_n, py_n, ratio)

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
        # Stage 2: 리사이즈 종료 우선 처리.
        if self._resize_corner is not None and self._sidecar is not None:
            kind = self._resize_kind
            eff_id = self._resize_eff_id
            override = self._resize_override
            self._resize_corner = None
            self._resize_kind = None
            self._resize_eff_id = None
            self._resize_start_pos = None
            self._resize_orig_box = None
            self._resize_override = None
            self.unsetCursor()
            if override is not None and kind and eff_id:
                for eff in self._sidecar.effects:
                    if eff.id != eff_id:
                        continue
                    new_eff = self._apply_resize_to_effect(kind, eff, override)
                    if new_eff is not None:
                        self.effect_drag_changed.emit(new_eff)
                    break
            event.accept()
            return
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

    def _apply_resize_to_effect(self, kind: str, eff, override: tuple[float, float, float]):
        """리사이즈 override (cx/cy/scale 또는 pos_x/y/size_ratio) 를 effect 에 반영."""
        a, b, c = override
        if kind == "zoom" and isinstance(eff, ZoomEffect):
            new_start = replace(eff.start, cx=a, cy=b, scale=c)
            new_end = replace(eff.end, cx=a, cy=b, scale=c)
            return replace(eff, start=new_start, end=new_end)
        if kind == "broll" and isinstance(eff, BrollEffect) and eff.pip is not None:
            new_pip = replace(eff.pip, pos_x=a, pos_y=b, size_ratio=c)
            return replace(eff, pip=new_pip)
        return None

