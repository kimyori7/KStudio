"""사용자가 드래그/리사이즈로 조정하는 영역 테두리.

- 대기(standby): 녹색 얇은 사각형 + 라벨 ◇ 대기 중
- 영상 녹화: 빨강 얇은 사각형 + 라벨 ● REC hh:mm:ss
- GIF 녹화:  주황 "긴 선 + 짧은 간격" 점선 사각형 + 라벨 ◆ GIF hh:mm:ss

굵은 모서리 L자(꺽쇠)는 캡처 경계를 걸쳐 그려져 "포함/제외"가 헷갈렸기에 제거하고,
대신 바깥 프레임 모서리에 '살짝 연한 색'의 짧은 L자 손잡이 힌트만 남겼다 — 잡으면
크기 조절됨을 알리는 신호(캡처 영역 안쪽이 아니라 바깥 프레임에 얹어 헷갈리지 않음).
캡처 경계는 안쪽 사각형 테두리가 그대로 표시한다.

대기 상태에서는 테두리/타이틀바 영역으로 이동·크기 조절 가능.
네 모서리 모두 대각선 리사이즈(상단 코너 포함 — 타이틀바 이동보다 우선).
내부는 투명(클릭 통과)이라 아래 어플과 상호작용 가능.
녹화 상태에서는 전체 클릭 통과(움직임 봉인) + 화면 캡처 제외.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QRegion
from PySide6.QtWidgets import QWidget, QPushButton


_COLOR_STANDBY_VIDEO = QColor("#2E7D32")  # 녹색 — 영상 대기
_COLOR_STANDBY_GIF = QColor("#0277BD")    # 파랑/청록 — GIF 대기
_COLOR_VIDEO = QColor("#E53935")          # 빨강 — 영상 녹화 중
_COLOR_GIF = QColor("#FFB300")            # 주황 — GIF 녹화 중


class AdjustableRegionBorder(QWidget):
    rect_changed = Signal(int, int, int, int)  # x, y, w, h (geometry 변경)
    close_requested = Signal()                 # 타이틀바 X 버튼 클릭 (대기 상태)
    stop_requested = Signal()                  # 우상단 ⏹ 버튼 클릭 (녹화 중)

    BORDER_THICKNESS = 4
    LABEL_HEIGHT = 26              # 좌상단 라벨 영역 높이
    EDGE_GRIP = 8                  # 에지 리사이즈 감지 범위
    CORNER_GRIP = 16               # 코너 리사이즈 감지 범위 (대각선)
    MOVE_STRIP = 18                # 이동 드래그 가능한 테두리 폭
    MIN_SIZE = 80

    def __init__(self, initial_rect: tuple[int, int, int, int], mode: str = "video"):
        super().__init__()
        self.mode = mode              # "video" | "gif"
        self._state = "standby"       # "standby" | "recording"
        self._elapsed = 0
        self._drag_mode: str | None = None
        self._drag_origin = None
        self._drag_start_geom = None

        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        x, y, w, h = initial_rect
        w = max(self.MIN_SIZE, int(w))
        h = max(self.MIN_SIZE, int(h))
        self.setGeometry(int(x), int(y), w, h)

        self._sec_timer = QTimer(self)
        self._sec_timer.setInterval(1000)
        self._sec_timer.timeout.connect(self._tick_sec)

        # 타이틀바 우상단 X 버튼 (전체화면으로 복귀)
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setObjectName("RegionCloseBtn")
        self.close_btn.setFixedSize(self.LABEL_HEIGHT, self.LABEL_HEIGHT)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("전체 화면으로 전환")
        # 전역 다크 테마 QSS가 QPushButton 을 회색으로 잡아먹지 않도록 ID 셀렉터 사용
        self.close_btn.setStyleSheet(
            "QPushButton#RegionCloseBtn { "
            "  background-color: transparent; "
            "  color: white; "
            "  border: none; "
            "  font-weight: 900; "
            "  font-size: 14pt; "
            "  padding: 0; "
            "} "
            "QPushButton#RegionCloseBtn:hover { "
            "  background-color: rgba(255, 255, 255, 60); "
            "} "
            "QPushButton#RegionCloseBtn:pressed { "
            "  background-color: rgba(255, 255, 255, 100); "
            "}"
        )
        self.close_btn.clicked.connect(self.close_requested.emit)

        # 우상단 ⏹ 정지 버튼 (녹화 중에만 표시, X 버튼 자리에 들어감)
        self.stop_btn = QPushButton("⏹", self)
        self.stop_btn.setObjectName("RegionStopBtn")
        self.stop_btn.setFixedSize(self.LABEL_HEIGHT, self.LABEL_HEIGHT)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setToolTip("녹화 정지")
        self.stop_btn.setStyleSheet(
            "QPushButton#RegionStopBtn { "
            "  background-color: transparent; "
            "  color: white; "
            "  border: none; "
            "  font-weight: 900; "
            "  font-size: 14pt; "
            "  padding: 0; "
            "} "
            "QPushButton#RegionStopBtn:hover { "
            "  background-color: rgba(255, 255, 255, 60); "
            "} "
            "QPushButton#RegionStopBtn:pressed { "
            "  background-color: rgba(255, 255, 255, 100); "
            "}"
        )
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.hide()
        self._position_close_button()

    # ---------- Public API (CaptureTarget 호환 일부) ----------

    def current_geometry(self) -> tuple[int, int, int, int]:
        return self.x(), self.y(), self.width(), self.height()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()

    def start_recording(self) -> None:
        self._state = "recording"
        self._elapsed = 0
        self._sec_timer.start()
        # 녹화 중에도 타이틀바 이동은 허용 (크기 변경은 _hit_test에서 차단).
        # 내부는 마스크로 클릭 통과 유지 → 녹화 대상 어플 조작 가능.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._update_mask()
        # 녹화 중에는 X (전체화면 복귀) 대신 ⏹ (정지) 버튼
        self.close_btn.hide()
        self.stop_btn.show()
        self.stop_btn.raise_()
        self.update()

    def stop_recording(self) -> None:
        self._state = "standby"
        self._sec_timer.stop()
        self._elapsed = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._update_mask()
        self.stop_btn.hide()
        self.close_btn.show()
        self.update()

    def stop(self) -> None:
        """완전히 닫기."""
        self._sec_timer.stop()
        self.close()

    # ---------- 이벤트 ----------

    def showEvent(self, e):
        super().showEvent(e)
        self._update_mask()
        self._position_close_button()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_mask()
        self._position_close_button()

    def _position_close_button(self) -> None:
        # 우상단 코너(CORNER_GRIP × CORNER_GRIP)를 'ne' 대각선 리사이즈 손잡이로
        # 비워두기 위해 버튼을 코너폭만큼 왼쪽으로 들인다. (버튼이 코너를 덮으면
        # QPushButton 이 마우스를 먼저 먹어 코너 리사이즈가 안 됨.)
        size = self.LABEL_HEIGHT
        x = self.width() - size - self.CORNER_GRIP
        self.close_btn.move(x, 0)
        self.close_btn.raise_()
        self.stop_btn.move(x, 0)
        self.stop_btn.raise_()

    def _update_mask(self):
        """테두리/타이틀바 영역만 마우스 받고, 내부는 클릭 통과 (대기/녹화 공통)."""
        w, h = self.width(), self.height()
        ms = self.MOVE_STRIP
        lh = self.LABEL_HEIGHT
        full = QRegion(0, 0, w, h)
        # 내부 구멍(타이틀바 아래쪽부터, 좌우/하단 ms 폭은 마우스 받음)
        hole_top = max(ms, lh)
        hole_x = ms
        hole_y = hole_top
        hole_w = max(0, w - 2 * ms)
        hole_h = max(0, h - hole_top - ms)
        if hole_w > 0 and hole_h > 0:
            hole = QRegion(hole_x, hole_y, hole_w, hole_h)
            self.setMask(full.subtracted(hole))
        else:
            self.setMask(full)

    def _hit_test(self, pos) -> str:
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        cg = self.CORNER_GRIP
        eg = self.EDGE_GRIP
        lh = self.LABEL_HEIGHT
        # 녹화 중에는 크기 변경 금지 → 이동만 허용 (인코더 입력 해상도 고정)
        if self._state == "recording":
            return "move"
        # 네 모서리 코너 리사이즈 — 타이틀바 이동 판정보다 먼저 둬야 상단 코너가
        # 'move' 에 먹히지 않고 대각선 리사이즈로 동작한다 (상단 코너 우선).
        if x < cg and y < cg: return "nw"
        if x > w - cg and y < cg: return "ne"
        if x < cg and y > h - cg: return "sw"
        if x > w - cg and y > h - cg: return "se"
        # 타이틀바 영역(코너 제외)은 이동. ✕/⏹ 버튼은 코너 밖으로 비켜둠.
        if y < lh: return "move"
        # 좌우/하단 에지 리사이즈
        if x < eg: return "w"
        if x > w - eg: return "e"
        if y > h - eg: return "s"
        # 나머지(마스크 영역 안쪽): 이동
        return "move"

    def _cursor_for(self, mode: str):
        return {
            "move": Qt.SizeAllCursor,
            "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
            "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
            "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
            "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
        }.get(mode, Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_mode = self._hit_test(e.position().toPoint())
            self._drag_origin = e.globalPosition().toPoint()
            self._drag_start_geom = self.geometry()

    def mouseMoveEvent(self, e):
        if self._drag_mode is None:
            mode = self._hit_test(e.position().toPoint())
            self.setCursor(self._cursor_for(mode))
            return
        delta = e.globalPosition().toPoint() - self._drag_origin
        g = self._drag_start_geom
        dx, dy = delta.x(), delta.y()
        ms = self.MIN_SIZE
        new_x, new_y, new_w, new_h = g.x(), g.y(), g.width(), g.height()
        m = self._drag_mode
        if m == "move":
            new_x = g.x() + dx
            new_y = g.y() + dy
        else:
            # 각 방향 처리
            if "w" in m:
                cap = g.right() - ms + 1
                new_x = min(cap, g.x() + dx)
                new_w = g.width() - (new_x - g.x())
            if "e" in m:
                new_w = max(ms, g.width() + dx)
            if "n" in m:
                cap = g.bottom() - ms + 1
                new_y = min(cap, g.y() + dy)
                new_h = g.height() - (new_y - g.y())
            if "s" in m:
                new_h = max(ms, g.height() + dy)
        self.setGeometry(new_x, new_y, new_w, new_h)

    def mouseReleaseEvent(self, e):
        if self._drag_mode is not None:
            self._drag_mode = None
            self.rect_changed.emit(self.x(), self.y(), self.width(), self.height())

    def _tick_sec(self):
        self._elapsed += 1
        self.update()

    # ---------- 캡처 영역 ----------

    def current_capture_rect(self) -> tuple[int, int, int, int]:
        """
        실제 녹화 대상 사각형 (타이틀바/테두리 제외).
        = 화면상 위젯 위치 + 내부 여백을 감안한 '내부 영역' 절대 좌표.
        """
        bt = self.BORDER_THICKNESS
        lh = self.LABEL_HEIGHT
        return (
            self.x() + bt,
            self.y() + lh,
            max(1, self.width() - 2 * bt),
            max(1, self.height() - lh - bt),
        )

    # ---------- 그리기 ----------

    def _current_color(self) -> QColor:
        if self._state == "standby":
            return _COLOR_STANDBY_GIF if self.mode == "gif" else _COLOR_STANDBY_VIDEO
        if self.mode == "gif":
            return _COLOR_GIF
        return _COLOR_VIDEO

    def _use_dash(self) -> bool:
        """녹화 중 + GIF 일 때만 점선."""
        return self._state == "recording" and self.mode == "gif"

    def paintEvent(self, _):
        p = QPainter(self)
        color = self._current_color()
        w, h = self.width(), self.height()
        bt = self.BORDER_THICKNESS
        lh = self.LABEL_HEIGHT

        # 1) 전체 폭 상단 타이틀바 (라벨/버튼 영역)
        p.fillRect(QRect(0, 0, w, lh), color)

        # 2) 좌·우·하단 테두리 — 모서리 장식(꺽쇠) 없이 끊김 없는 얇은 사각형.
        #    안쪽 테두리 모서리가 곧 캡처 경계(current_capture_rect)다.
        if self._use_dash():
            pen = QPen(color, bt)
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([8, 2])
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            half = bt // 2
            p.drawLine(half, lh, half, h - 1)                    # 좌
            p.drawLine(w - 1 - half, lh, w - 1 - half, h - 1)    # 우
            p.drawLine(0, h - 1 - half, w - 1, h - 1 - half)     # 하
        else:
            # 실선은 fillRect로 (깔끔한 두께 보장)
            p.fillRect(0, lh, bt, h - lh, color)                 # 좌
            p.fillRect(w - bt, lh, bt, h - lh, color)            # 우
            p.fillRect(0, h - bt, w, bt, color)                  # 하

        # 3) 네 모서리 코너 손잡이 힌트 — 테두리보다 살짝 연한 색의 짧은 L자.
        #    "여기 잡아서 크기 조절" 신호. 캡처 영역(안쪽)이 아니라 바깥 프레임
        #    모서리에 얹어 캡처 경계와 헷갈리지 않는다. 길이=CORNER_GRIP(잡는
        #    영역과 일치), 두께=BORDER_THICKNESS. ✕/⏹ 버튼은 코너 밖으로 비켜둬
        #    우상단 가로 팔이 버튼에 가리지 않는다.
        accent = color.lighter(150)
        al = self.CORNER_GRIP
        at = bt
        p.fillRect(0, 0, al, at, accent)              # 좌상 가로
        p.fillRect(0, 0, at, al, accent)              # 좌상 세로
        p.fillRect(w - al, 0, al, at, accent)         # 우상 가로
        p.fillRect(w - at, 0, at, al, accent)         # 우상 세로
        p.fillRect(0, h - at, al, at, accent)         # 좌하 가로
        p.fillRect(0, h - al, at, al, accent)         # 좌하 세로
        p.fillRect(w - al, h - at, al, at, accent)    # 우하 가로
        p.fillRect(w - at, h - al, at, al, accent)    # 우하 세로

        # 4) 타이틀바 라벨 텍스트
        inner_w = w - 2 * bt
        inner_h = h - lh - bt
        if self._state == "standby":
            label = f"◇ 대기 중  {inner_w}×{inner_h}"
        else:
            hh, rem = divmod(self._elapsed, 3600)
            mm, ss = divmod(rem, 60)
            prefix = "● REC" if self.mode == "video" else "◆ GIF"
            label = f"{prefix}  {hh:02d}:{mm:02d}:{ss:02d}   {inner_w}×{inner_h}"
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        p.setFont(font)
        p.setPen(Qt.white)
        p.drawText(QRect(10, 0, w - 20, lh), Qt.AlignVCenter | Qt.AlignLeft, label)
