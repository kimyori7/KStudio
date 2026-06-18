"""AudioWaveformEditor — 오디오 파일 트림 편집 표면.

큰 전체 파형을 그리고, 양끝 트림 / 중간 컷 / 재생 헤드 / 클릭 seek 를 지원한다.
모든 ms↔x 계산은 순수 모듈 ``audio_edit_geometry`` 에 위임한다(이 파일은 그리기·입력만).

상호작용(왼쪽 버튼):
- 트림 핸들(±6px) 근처에서 눌러 드래그 → 해당 트림 이동(``trim_changed``).
- 빈 파형에서 같은 x 클릭(드래그 ≤4px) → ``seek_request``.
- 빈 파형에서 눌러 드래그(>4px) → ``add_cut_ms`` 로 컷 생성(``cuts_changed``).
- 기존 컷 위 클릭 → 그 컷 제거(``remove_cut_at`` → ``cuts_changed``).

왼쪽 헤더 오프셋 없음 — 파일명은 좌상단 텍스트로 오버레이, 파형은 전체 폭 사용
(=> x↔ms 가 단순, seek 테스트 견고).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from . import audio_edit_geometry as geometry

_BG = QColor(24, 24, 24)
_WAVE = QColor(90, 200, 250)            # 시안 파형 (audio_track_lane 와 동일)
_BASELINE = QColor(70, 70, 70)
_DIM = QColor(0, 0, 0, 150)             # 트림 밖 반투명 검정
_CUT = QColor(220, 60, 60, 110)        # 컷(잘라낸 구간) 반투명 빨강
_CUT_EDGE = QColor(230, 90, 90)
_SEL = QColor(120, 175, 255, 95)       # 선택(아직 안 자른) 반투명 파랑
_SEL_EDGE = QColor(150, 195, 255)
_TRIM_EDGE = QColor(250, 210, 90)       # 트림 핸들 노랑
_TRIM_GRIP = QColor(250, 210, 90)       # 트림 핸들 그립(손잡이) 채움
_TRIM_GRIP_LINE = QColor(60, 50, 10)    # 그립 위 손잡이 텍스처 선(어두운)
_PLAYHEAD = QColor(255, 255, 255)
_FILENAME_FG = QColor(220, 220, 220)
_HINT_FG = QColor(225, 225, 225)
_HINT_BG = QColor(0, 0, 0, 130)         # 힌트 가독용 반투명 알약 배경

_EDGE_GRAB_PX = 7       # 트림 핸들 히트 반경(라인 기준)
_GRIP_W = 9             # 트림 핸들 그립 폭(핸들 라인에서 안쪽으로)
_GRIP_H = 34            # 트림 핸들 그립 높이
_DRAG_THRESHOLD = 4     # 클릭 vs 드래그 구분
_HINT_TEXT = "양끝을 끌어 앞·뒤 자르기 · 드래그로 구간 선택 후 오른클릭 → 자르기 · 클릭으로 이동"


class AudioWaveformEditor(QWidget):
    """오디오 파일 트림 편집 위젯.

    set_peaks / set_total_ms / set_position_ms / set_trim / set_cuts /
    set_filename / add_cut_ms 로 상태를 갱신한다.
    """

    trim_changed = Signal(int, int)     # (in_ms, out_ms)
    cuts_changed = Signal(list)         # list[tuple[int, int]]
    seek_request = Signal(int)          # ms

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setMouseTracking(True)   # 버튼 안 눌러도 hover 커서 갱신
        self.setToolTip(
            "• 양끝 노란 손잡이를 끌어 앞/뒤 자르기\n"
            "• 가운데를 드래그해 구간 선택 → 오른클릭 → ✂ 자르기\n"
            "• 자른 구간은 내보내기·재생에서 이어붙습니다 (Ctrl+Z 실행 취소)"
        )
        self._peaks: list = []
        self._total_ms = 0
        self._position_ms = 0
        self._trim_in_ms = 0
        self._trim_out_ms = 0           # 0 → 끝까지
        self._cuts: list[tuple[int, int]] = []
        self._selection: tuple[int, int] | None = None   # 드래그로 잡은 '아직 안 자른' 구간
        self._filename = ""
        # 드래그 상태
        self._press_x: int | None = None
        self._drag_mode: str | None = None     # None | "seek" | "cut" | "trim_in" | "trim_out"
        self._moved = False

    # ---------- public state ----------
    def set_peaks(self, peaks: list) -> None:
        self._peaks = list(peaks)
        self.update()

    def set_total_ms(self, ms: int) -> None:
        self._total_ms = max(0, int(ms))
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self.update()

    def set_trim(self, in_ms: int, out_ms: int) -> None:
        a, b = int(in_ms), int(out_ms)
        # 정상 순서 보장(out 가 0이면 '끝까지' 의미라 그대로 둔다).
        if b != 0 and a > b:
            a, b = b, a
        self._trim_in_ms = max(0, a)
        self._trim_out_ms = max(0, b)
        self.update()

    def trim(self) -> tuple[int, int]:
        return (self._trim_in_ms, self._trim_out_ms)

    def set_cuts(self, cuts: list) -> None:
        self._cuts = geometry.add_cut(list(cuts), (0, 0))  # _normalize 경유로 정리
        # add_cut((0,0)) 은 0폭이라 입력만 정규화해서 돌려준다.
        self.update()

    def cuts(self) -> list:
        return list(self._cuts)

    def set_filename(self, name: str) -> None:
        self._filename = str(name)
        self.update()

    def add_cut_ms(self, s: int, e: int) -> None:
        """컷 추가 — geometry.add_cut 적용 후 상태 갱신 + cuts_changed."""
        self._cuts = geometry.add_cut(self._cuts, (int(s), int(e)))
        self.update()
        self.cuts_changed.emit(list(self._cuts))

    # ---------- geometry helpers ----------
    def _trim_out_effective(self) -> int:
        return self._trim_out_ms if self._trim_out_ms > 0 else self._total_ms

    def _x_of_ms(self, ms: int) -> int:
        return geometry.ms_to_x(ms, total_ms=self._total_ms, width=self.width())

    def _ms_of_x(self, x: int) -> int:
        return geometry.x_to_ms(x, total_ms=self._total_ms, width=self.width())

    def _cut_at_ms(self, ms: int) -> tuple[int, int] | None:
        for s, e in self._cuts:
            if s <= ms <= e:
                return (s, e)
        return None

    def _grip_y_band(self) -> tuple[int, int]:
        """트림 핸들 그립(손잡이)의 세로 범위 (top, bottom) — 그리기·히트테스트가 공유."""
        h = self.height()
        top = max(0, (h - _GRIP_H) // 2)
        return top, top + min(_GRIP_H, h)

    def _trim_hit(self, x: int, y: int) -> str | None:
        """(x, y) 가 어느 트림 핸들 그립에 걸리는지 — 그립이 **실제로 그려진 영역**
        (가로=안쪽 grip_w, 세로=가운데 grip 밴드)에서만 잡힌다. 라인 전체(세로 전 구간)로
        잡혀 불편하던 것 해소(WYSIWYG-grab — 잡는 위치 주변에서만 반응).

        in 핸들: [in_x - grab, in_x + grip_w + grab], out 핸들: 대칭으로 안쪽.
        둘 다 걸리면(짧은 오디오·과트림) 라인에 더 가까운 쪽."""
        g = _EDGE_GRAB_PX
        top, bottom = self._grip_y_band()
        if not (top - g <= y <= bottom + g):
            return None   # 그립 세로 밴드 밖 → 트림 안 잡음(클릭은 seek/선택으로 흐름)
        in_x = self._x_of_ms(self._trim_in_ms)
        out_x = self._x_of_ms(self._trim_out_effective())
        in_hit = (in_x - g) <= x <= (in_x + _GRIP_W + g)
        out_hit = (out_x - _GRIP_W - g) <= x <= (out_x + g)
        if in_hit and out_hit:
            return "trim_in" if abs(x - in_x) <= abs(x - out_x) else "trim_out"
        if in_hit:
            return "trim_in"
        if out_hit:
            return "trim_out"
        return None

    def _should_show_hint(self) -> bool:
        """편집 안내 힌트를 보일 조건: 준비됨(파형+길이) + 아직 아무 편집도 안 함.

        상호작용이 죽어 있을 때(길이 0)나 사용자가 편집을 시작한 뒤엔 숨긴다."""
        return (
            bool(self._peaks) and self._total_ms > 0
            and self._trim_in_ms == 0 and self._trim_out_ms == 0
            and not self._cuts and self._selection is None
        )

    # ---------- mouse ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._total_ms <= 0:
            super().mousePressEvent(event)
            return
        x = int(event.position().x())
        y = int(event.position().y())
        self._press_x = x
        self._moved = False
        # 트림 핸들 히트 테스트 — 그립이 그려진 영역(안쪽 grip_w × 가운데 세로 밴드)에서만
        # 잡힌다(WYSIWYG-grab). 가장자리(in_x=0, out_x=width)에서도 그립 부근이면 집힌다.
        hit = self._trim_hit(x, y)
        self._drag_mode = hit if hit else "seek"  # seek 는 release 에서 cut 으로 승격 가능
        if hit:
            self.setCursor(Qt.ClosedHandCursor)   # 트림 잡는 중 = 쥔 손
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        y = int(event.position().y())
        # 버튼 안 누른 hover 이동 → 커서 모양으로 무엇을 잡을 수 있는지 알림.
        if self._press_x is None:
            self._update_hover_cursor(x, y)
            super().mouseMoveEvent(event)
            return
        if self._total_ms <= 0:
            super().mouseMoveEvent(event)
            return
        if abs(x - self._press_x) > _DRAG_THRESHOLD:
            self._moved = True
        if self._drag_mode in ("trim_in", "trim_out"):
            self._apply_trim_drag(x)
        event.accept()

    def _update_hover_cursor(self, x: int, y: int) -> None:
        """마우스 위치에 따라 커서 모양 — 트림 그립=손(잡기), 컷/선택=손가락(클릭), 그 외=기본."""
        if self._total_ms <= 0:
            self.unsetCursor()
            return
        if self._trim_hit(x, y) is not None:
            self.setCursor(Qt.OpenHandCursor)        # 잡을 수 있는 손잡이
            return
        ms = self._ms_of_x(x)
        if self._cut_at_ms(ms) is not None or self._selection is not None:
            self.setCursor(Qt.PointingHandCursor)    # 컷/선택 = 클릭·우클릭 가능
            return
        self.unsetCursor()

    def leaveEvent(self, event) -> None:
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._press_x is None or self._total_ms <= 0:
            super().mouseReleaseEvent(event)
            return
        x = int(event.position().x())
        mode = self._drag_mode
        press_x = self._press_x
        moved = self._moved or abs(x - press_x) > _DRAG_THRESHOLD
        # 상태 리셋(다음 제스처 대비) — 분기 전에.
        self._press_x = None
        self._drag_mode = None
        self._moved = False

        if mode in ("trim_in", "trim_out"):
            self._apply_trim_drag(x, mode)   # mode 명시 — release 에서 drag_mode 는 이미 None
            self.trim_changed.emit(self._trim_in_ms, self._trim_out_ms)
            self._update_hover_cursor(x, int(event.position().y()))  # 쥔 손 → hover 복귀
            event.accept()
            return

        # body 영역 — 드래그는 '선택'(아직 안 자름). 오른클릭 메뉴 → 자르기 로 확정.
        if moved:
            s = self._ms_of_x(press_x)
            e = self._ms_of_x(x)
            self._selection = (min(s, e), max(s, e))
            self.update()
            event.accept()
            return

        # 같은 자리 클릭 → 컷 위면 제거(빠른 길), 아니면 선택 해제 + seek.
        ms = self._ms_of_x(x)
        if self._cut_at_ms(ms) is not None:
            self.remove_cut_at_ms(ms)
        else:
            self._selection = None
            self.update()
            self.seek_request.emit(ms)
        event.accept()

    # ---------- 선택 → 자르기 (오른클릭 메뉴) ----------
    def selection(self) -> "tuple[int, int] | None":
        return self._selection

    def set_selection(self, sel: "tuple[int, int] | None") -> None:
        self._selection = sel
        self.update()

    def cut_selection(self) -> bool:
        """현재 선택 구간을 컷으로 확정(잘라내기). 선택 없으면 no-op."""
        if self._selection is None:
            return False
        s, e = self._selection
        self._selection = None
        self.add_cut_ms(s, e)     # cuts_changed emit + update
        return True

    def remove_cut_at_ms(self, ms: int) -> bool:
        """ms 가 걸친 컷을 제거(자르기 취소). 없으면 no-op."""
        if self._cut_at_ms(ms) is None:
            return False
        self._cuts = geometry.remove_cut_at(self._cuts, ms)
        self.update()
        self.cuts_changed.emit(list(self._cuts))
        return True

    def _context_menu_for(self, ms: int) -> QMenu:
        """ms 위치의 우클릭 메뉴 — 컷 위면 '자르기 취소', 선택 있으면 '선택 영역 자르기'."""
        menu = QMenu(self)
        if self._cut_at_ms(ms) is not None:
            menu.addAction("↩ 자르기 취소").triggered.connect(
                lambda: self.remove_cut_at_ms(ms))
        if self._selection is not None:
            menu.addAction("✂ 선택 영역 자르기").triggered.connect(self.cut_selection)
        return menu

    def contextMenuEvent(self, event) -> None:
        if self._total_ms <= 0:
            return
        ms = self._ms_of_x(int(event.pos().x()))
        menu = self._context_menu_for(ms)
        if menu.isEmpty():
            hint = menu.addAction("ℹ 파형을 드래그해 구간을 선택한 뒤 오른클릭하세요")
            hint.setEnabled(False)
        menu.exec(event.globalPos())

    def _apply_trim_drag(self, x: int, mode: str | None = None) -> None:
        # mode 명시 가능 — mouseReleaseEvent 는 drag_mode 를 이미 None 으로 리셋한 뒤
        # 호출하므로(안 그러면 항상 trim_out 분기로 빠져 왼쪽 핸들이 release 에서 붕괴).
        mode = mode or self._drag_mode
        ms = self._ms_of_x(x)
        if mode == "trim_in":
            cap = self._trim_out_effective()
            self._trim_in_ms = max(0, min(ms, max(0, cap - 1)))
        else:  # trim_out
            self._trim_out_ms = max(self._trim_in_ms + 1, min(ms, self._total_ms))
        self.update()

    # ---------- paint ----------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        w = self.width()
        h = self.height()
        cy = h // 2
        half = max(1, (h - 8) // 2)

        self._draw_waveform(p, w, cy, half)
        self._draw_trim_dim(p, w, h)
        self._draw_cuts(p, h)
        self._draw_selection(p, h)
        self._draw_playhead(p, h)
        self._draw_filename(p)
        if self._should_show_hint():
            self._draw_hint(p, w, h)

    def _draw_waveform(self, p: QPainter, w: int, cy: int, half: int) -> None:
        peaks = self._peaks
        if not peaks:
            p.setPen(QPen(_BASELINE, 1))
            p.drawLine(0, cy, w, cy)
            return
        n = len(peaks)
        p.setPen(QPen(_WAVE, 1))
        for px in range(w):
            idx = min(n - 1, int(px * n / w)) if w > 0 else 0
            try:
                val = float(peaks[idx])
            except (TypeError, ValueError):
                val = 0.0
            ph = int(max(0.0, min(1.0, val)) * half)
            p.drawLine(px, cy - ph, px, cy + ph)

    def _draw_trim_dim(self, p: QPainter, w: int, h: int) -> None:
        if self._total_ms <= 0:
            return
        in_x = self._x_of_ms(self._trim_in_ms)
        out_x = self._x_of_ms(self._trim_out_effective())
        # 트림 밖 영역(좌/우)을 어둡게.
        if in_x > 0:
            p.fillRect(0, 0, in_x, h, _DIM)
        if out_x < w:
            p.fillRect(out_x, 0, w - out_x, h, _DIM)
        # 핸들 선(논리 위치 정확) + 안쪽으로 그려지는 그립(손잡이) — 가장자리에서도 보이고 집힌다.
        p.setPen(QPen(_TRIM_EDGE, 2))
        p.drawLine(in_x, 0, in_x, h)
        p.drawLine(out_x, 0, out_x, h)
        self._draw_grip(p, in_x, h, inward=+1)    # 왼쪽: 안쪽=오른쪽
        self._draw_grip(p, out_x, h, inward=-1)   # 오른쪽: 안쪽=왼쪽

    def _draw_grip(self, p: QPainter, x: int, h: int, *, inward: int) -> None:
        gx = x if inward > 0 else x - _GRIP_W
        gy, gy2 = self._grip_y_band()   # 히트테스트와 동일 밴드 (drift 방지)
        gh = gy2 - gy
        p.fillRect(gx, gy, _GRIP_W, gh, _TRIM_GRIP)
        # 손잡이 텍스처 — 세로 짧은 선 2개.
        p.setPen(QPen(_TRIM_GRIP_LINE, 1))
        cx = gx + _GRIP_W // 2
        p.drawLine(cx - 1, gy + 6, cx - 1, gy + gh - 6)
        p.drawLine(cx + 1, gy + 6, cx + 1, gy + gh - 6)

    def _draw_cuts(self, p: QPainter, h: int) -> None:
        if self._total_ms <= 0:
            return
        for s, e in self._cuts:
            sx = self._x_of_ms(s)
            ex = self._x_of_ms(e)
            p.fillRect(sx, 0, max(1, ex - sx), h, _CUT)
            p.setPen(QPen(_CUT_EDGE, 1))
            p.drawLine(sx, 0, sx, h)
            p.drawLine(ex, 0, ex, h)

    def _draw_selection(self, p: QPainter, h: int) -> None:
        """드래그로 잡은 '아직 안 자른' 선택 구간 — 파랑(컷=빨강과 구분). 오른클릭 → 자르기."""
        if self._total_ms <= 0 or self._selection is None:
            return
        s, e = self._selection
        sx = self._x_of_ms(s)
        ex = self._x_of_ms(e)
        p.fillRect(sx, 0, max(1, ex - sx), h, _SEL)
        p.setPen(QPen(_SEL_EDGE, 1, Qt.DashLine))
        p.drawLine(sx, 0, sx, h)
        p.drawLine(ex, 0, ex, h)

    def _draw_playhead(self, p: QPainter, h: int) -> None:
        if self._total_ms <= 0:
            return
        x = self._x_of_ms(self._position_ms)
        p.setPen(QPen(_PLAYHEAD, 1))
        p.drawLine(x, 0, x, h)

    def _draw_filename(self, p: QPainter) -> None:
        if not self._filename:
            return
        p.setPen(_FILENAME_FG)
        p.drawText(6, 16, self._filename)

    def _draw_hint(self, p: QPainter, w: int, h: int) -> None:
        """편집 방법 안내 — 가운데 알약 배경 위 한 줄. 사용자가 '편집 버튼이 없다'고
        느끼지 않도록 파형 자체가 편집 면임을 알린다(첫 진입·미편집 상태에서만)."""
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(_HINT_TEXT)
        th = fm.height()
        pad = 10
        bx = (w - tw) // 2 - pad
        by = h // 2 - th // 2 - 4
        bw = tw + pad * 2
        bh = th + 8
        p.setPen(Qt.NoPen)
        p.setBrush(_HINT_BG)
        p.drawRoundedRect(bx, by, bw, bh, 6, 6)
        p.setBrush(Qt.NoBrush)
        p.setPen(_HINT_FG)
        p.drawText(bx + pad, by + bh - 7, _HINT_TEXT)
