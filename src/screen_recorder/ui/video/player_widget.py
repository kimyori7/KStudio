"""MP4/MKV/WebM (QMediaPlayer) + GIF (QMovie) 통합 플레이어 위젯."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

import os
from PySide6.QtCore import Qt, QRect, QUrl, Signal, QTimer
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QMovie, QPainter, QPainterPath, QPen,
    QPixmap,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
from PySide6.QtWidgets import QStackedWidget, QLabel, QWidget


class _OutlinedLabel(QWidget):
    """배경 없이 외곽선이 둘러진 흰 글씨 라벨 — 영상 위 HUD 가시성 확보용.

    QLabel + CSS 로는 text-stroke 표현 불가 → QPainterPath.addText 로 path 를 만든 뒤
    먼저 굵은 검정 펜으로 stroke, 다음 흰 fill — 클래식 game-HUD 스타일.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._font = QFont()
        self._font.setBold(True)
        self._font.setPointSize(14)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # 드래그 가능 모드 — set_draggable(True) 시 마우스 받기 + 사용자 위치 기억.
        self._draggable: bool = False
        self._press_offset = None     # QPoint — mousePress 시 라벨 안 클릭 위치
        # 사용자가 드래그로 옮긴 위치. None 이면 부모의 reposition 로직(기본 좌표) 사용.
        self.custom_pos = None        # QPoint | None

    def set_draggable(self, on: bool) -> None:
        """드래그 가능 토글. ON 이면 마우스 이벤트 받음 + 손 모양 커서."""
        self._draggable = bool(on)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self._draggable)
        if self._draggable:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event) -> None:   # type: ignore[override]
        if not self._draggable or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._press_offset = event.position().toPoint()
        self.setCursor(Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:   # type: ignore[override]
        if not self._draggable or self._press_offset is None:
            super().mouseMoveEvent(event)
            return
        parent = self.parentWidget()
        if parent is None:
            return
        new_global = event.globalPosition().toPoint() - self._press_offset
        new_in_parent = parent.mapFromGlobal(new_global)
        # 부모 영역 안으로 clamp.
        max_x = max(0, parent.width() - self.width())
        max_y = max(0, parent.height() - self.height())
        new_in_parent.setX(max(0, min(max_x, new_in_parent.x())))
        new_in_parent.setY(max(0, min(max_y, new_in_parent.y())))
        self.move(new_in_parent)
        self.custom_pos = new_in_parent
        event.accept()

    def mouseReleaseEvent(self, event) -> None:   # type: ignore[override]
        if not self._draggable or event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        self._press_offset = None
        self.setCursor(Qt.OpenHandCursor)
        event.accept()

    def setText(self, text: str) -> None:
        self._text = str(text)
        self.adjustSize()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self):
        fm = QFontMetrics(self._font)
        w = fm.horizontalAdvance(self._text) + 12
        h = fm.height() + 6
        return self.size().__class__(w, h) if hasattr(self.size().__class__, "__call__") else self.size()

    def adjustSize(self) -> None:
        fm = QFontMetrics(self._font)
        w = fm.horizontalAdvance(self._text) + 12
        h = fm.height() + 6
        self.resize(max(20, w), max(20, h))

    def paintEvent(self, event) -> None:   # type: ignore[override]
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        path = QPainterPath()
        fm = QFontMetrics(self._font)
        baseline_y = fm.ascent() + 3
        path.addText(6, baseline_y, self._font, self._text)
        # 외곽선 — 굵은 검정 (3px), 라운드 join.
        pen = QPen(QColor(0, 0, 0, 230))
        pen.setWidth(3)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # 채움 — 흰색.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(path)


GIF_EXTS = {".gif"}


class _VideoSurface(QWidget):
    """QVideoSink → QPainter 소프트 렌더.

    QVideoWidget 은 Windows D3D11 native HWND 를 생성해 QLabel HUD 가 가려지므로,
    모든 렌더링을 Qt raster pipeline 으로 통일해 오버레이를 가능하게 한다.

    프레임 입력 방식 (Phase 19.5 hotfix7):
    - **poll mode (기본)**: 30Hz QTimer 가 sink.videoFrame() 를 풀링.
      videoFrameChanged 시그널 미사용 — 5배속 시 decoder 가 초당 150 emit 으로
      메인 스레드 이벤트 큐를 폭주시켜 QTimer 가 55초까지 늦게 fire 되던 문제 해결.
    - **signal mode (KSTUDIO_VIDEO_SIGNAL_MODE=1)**: 기존 videoFrameChanged 경로.
      비교 / fallback 용.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._frame: QImage = QImage()
        self._thumbnail: QImage = QImage()
        self._sink = QVideoSink(self)
        # Stage 3: zoom 미리보기 transform — (cx, cy, scale) 정규화. None 이면 그대로.
        self._zoom_preview: "tuple[float, float, float] | None" = None

        if os.environ.get("KSTUDIO_VIDEO_SIGNAL_MODE") == "1":
            # 레거시 / 비교용 경로.
            self._sink.videoFrameChanged.connect(self._on_frame)
        else:
            # 폴링 모드 — sink.videoFrame() 를 30Hz 로 읽어 paint. decoder 가 빠른
            # 배속에서 emit 폭주해도 main thread 는 이 timer 만 보면 됨.
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(33)
            self._poll_timer.timeout.connect(self._poll_frame)
            self._poll_timer.start()

    @property
    def video_sink(self) -> QVideoSink:
        return self._sink

    def set_thumbnail(self, img: QImage) -> None:
        self._thumbnail = img
        if self._frame.isNull():
            self.update()

    def clear_frame(self) -> None:
        self._frame = QImage()
        self.update()

    def current_image(self) -> QImage:
        return self._frame.copy() if not self._frame.isNull() else QImage()

    def video_frame_rect(self) -> QRect:
        """현재 영상 프레임이 surface 안에서 차지하는 letterbox 사각형.

        영상 native size 와 surface size 의 aspect ratio 가 다를 때 위/아래 또는 좌/우에
        검은 띠가 생긴다. 오버레이를 영상 안에만 그리거나 드래그하기 위해 이 rect 가 필요.
        프레임이 아직 없으면 surface 전체를 반환 (화면 비율 정보가 없을 때의 기본값).
        """
        src = self._frame if not self._frame.isNull() else self._thumbnail
        if src.isNull():
            return self.rect()
        scaled = src.size().scaled(self.size(), Qt.KeepAspectRatio)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return QRect(x, y, scaled.width(), scaled.height())

    def _poll_frame(self) -> None:
        """30Hz 폴링 — sink 의 현재 프레임만 읽어 paint. videoFrameChanged
        이벤트 큐 폭주 회피.
        """
        from ...core.perf_diag import inc as _perf_inc
        frame = self._sink.videoFrame()
        if not frame.isValid():
            return
        _perf_inc("frame_changed")
        # .copy() — Qt 6 ffmpeg 백엔드에서 QVideoFrame.toImage() 는 frame 의 내부
        # 버퍼를 공유하는 QImage 를 반환. detach 안 하면 frame 버퍼 누적 (41s 재생
        # 시 RSS +19.8GB 관측). copy() 한 줄로 분리.
        img = frame.toImage().copy()
        if not img.isNull():
            self._frame = img
            self.update()

    def _on_frame(self, frame) -> None:
        """레거시 signal-mode 진입점 (KSTUDIO_VIDEO_SIGNAL_MODE=1 일 때만)."""
        from ...core.perf_diag import inc as _perf_inc
        _perf_inc("frame_changed")
        img = frame.toImage().copy()
        if not img.isNull():
            self._frame = img
            self.update()

    def set_zoom_preview(self, params: "tuple | None") -> None:
        """Stage 3: zoom 미리보기 transform 설정. None 이면 해제.

        params: (cx, cy, scale) — 기존 fit_screen 호환,
                또는 (cx, cy, scale, mode, region_w, region_h) — Phase 24.
        scale 1.0 = 그대로. 2.0 = 2× 확대 후 (cx, cy) 점이 화면 중앙.
        VideoTab 의 _on_position_for_zoom 가 매 position_changed 마다 호출.
        """
        if params == self._zoom_preview:
            return
        self._zoom_preview = params
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        src = self._frame if not self._frame.isNull() else self._thumbnail
        if not src.isNull():
            # FastTransformation — 매 프레임 HD 영상 스케일링이 메인 스레드 핫패스.
            # 5배속 시 frame_changed 가 100fps 도달, SmoothTransformation 으로는
            # 점진적으로 메인 스레드가 막힘 (관측됨 — 진단 dump 가 5s → 33s → 119s
            # 으로 점점 지연). 미리보기 화질 손실은 사용자 인지 불가능.
            scaled = src.scaled(self.size(), Qt.KeepAspectRatio, Qt.FastTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            if self._zoom_preview is not None:
                # 10-튜플(Phase 27) > 6-튜플(Phase 24) > 3-튜플(legacy) — 뒤로 호환.
                if len(self._zoom_preview) >= 10:
                    (cx_n, cy_n, scale, mode, region_w, region_h,
                     dest_cx_n, dest_cy_n, dest_w_n, dest_h_n) = self._zoom_preview
                elif len(self._zoom_preview) >= 6:
                    cx_n, cy_n, scale, mode, region_w, region_h = self._zoom_preview
                    dest_cx_n, dest_cy_n = cx_n, cy_n
                    dest_w_n = region_w * max(1.0, float(scale))
                    dest_h_n = region_h * max(1.0, float(scale))
                else:
                    cx_n, cy_n, scale = self._zoom_preview
                    mode, region_w, region_h = "fit_screen", 0.3, 0.3
                    dest_cx_n, dest_cy_n = cx_n, cy_n
                    dest_w_n = region_w * max(1.0, float(scale))
                    dest_h_n = region_h * max(1.0, float(scale))
                scale = max(1.0, float(scale))   # zoom out (<1) 은 미리보기에서 미지원
                sw = scaled.width()
                sh = scaled.height()
                if mode == "magnify_region":
                    # Phase 27/28 — source/dest 별도. 매 frame paint 가 핫패스이므로
                    # Qt.FastTransformation 사용 (preview 품질 손실 인지 어려움 + 5×
                    # 같은 고배속에서 freeze 회피). export 는 lanczos 유지.
                    src_w = max(1, int(round(region_w * sw)))
                    src_h = max(1, int(round(region_h * sh)))
                    src_x = max(0, min(sw - src_w,
                                       int(round(cx_n * sw - src_w / 2.0))))
                    src_y = max(0, min(sh - src_h,
                                       int(round(cy_n * sh - src_h / 2.0))))
                    p.drawImage(x, y, scaled)
                    dst_w = max(1, int(round(dest_w_n * sw)))
                    dst_h = max(1, int(round(dest_h_n * sh)))
                    dst_x = int(round(dest_cx_n * sw - dst_w / 2.0))
                    dst_y = int(round(dest_cy_n * sh - dst_h / 2.0))
                    # 화면 안 영역만 처리 — frame 밖으로 나간 부분의 큰 메모리/시간 절약.
                    visible_x1 = max(0, dst_x)
                    visible_y1 = max(0, dst_y)
                    visible_x2 = min(sw, dst_x + dst_w)
                    visible_y2 = min(sh, dst_y + dst_h)
                    if visible_x2 <= visible_x1 or visible_y2 <= visible_y1:
                        return
                    cropped = scaled.copy(src_x, src_y, src_w, src_h)
                    if cropped.isNull():
                        return
                    magnified = cropped.scaled(dst_w, dst_h, Qt.IgnoreAspectRatio,
                                               Qt.FastTransformation)
                    p.drawImage(x + dst_x, y + dst_y, magnified)
                else:
                    # fit_screen — 기존 동작 — 1/scale 영역을 전체 화면으로 stretch.
                    src_w = max(1, min(sw, int(round(sw / scale))))
                    src_h = max(1, min(sh, int(round(sh / scale))))
                    src_x = max(0, min(sw - src_w,
                                        int(round(cx_n * sw - src_w / 2.0))))
                    src_y = max(0, min(sh - src_h,
                                        int(round(cy_n * sh - src_h / 2.0))))
                    cropped = scaled.copy(src_x, src_y, src_w, src_h)
                    if not cropped.isNull():
                        final = cropped.scaled(sw, sh, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation)
                        p.drawImage(x, y, final)
                    else:
                        p.drawImage(x, y, scaled)
            else:
                p.drawImage(x, y, scaled)


class PlayerWidget(QStackedWidget):
    """파일을 로드하면 종류에 맞춰 내부 재생기를 자동 선택한다."""

    playing_changed = Signal(bool)
    position_changed = Signal(int)   # ms
    duration_changed = Signal(int)   # ms
    insert_position_changed = Signal(int)    # ms — 보조 player
    insert_duration_changed = Signal(int)    # ms

    def __init__(self) -> None:
        super().__init__()
        self._path: Optional[Path] = None
        self._is_gif = False

        # MP4 백엔드
        self._video_surface = _VideoSurface()
        self._media = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._media.setAudioOutput(self._audio)
        self._media.setVideoSink(self._video_surface.video_sink)
        self._media.playbackStateChanged.connect(self._on_media_state)
        # seek 시 paused-frame 갱신용 짧은 play/pause 사이클 동안 외부에 playing_changed
        # 가 깜빡거리는 걸 막는 가드.
        self._suppress_state_signal: bool = False
        self._media.positionChanged.connect(lambda v: self.position_changed.emit(int(v)))
        self._media.durationChanged.connect(lambda v: self.duration_changed.emit(int(v)))

        # GIF 백엔드
        self._gif_label = QLabel()
        self._gif_label.setAlignment(Qt.AlignCenter)
        self._gif_label.setStyleSheet("background-color: black;")
        self._movie: Optional[QMovie] = None

        self.addWidget(self._video_surface)  # index 0
        self.addWidget(self._gif_label)      # index 1

        # ---- 보조 player (CutEffect 의 B 영상 끼워넣기 — Stage 4d) ----
        self._insert_surface = _VideoSurface()
        self._insert_media = QMediaPlayer(self)
        self._insert_audio = QAudioOutput(self)
        self._insert_media.setAudioOutput(self._insert_audio)
        self._insert_media.setVideoSink(self._insert_surface.video_sink)
        self._insert_media.positionChanged.connect(
            lambda v: self.insert_position_changed.emit(int(v))
        )
        self._insert_media.durationChanged.connect(
            lambda v: self.insert_duration_changed.emit(int(v))
        )
        self._insert_media.mediaStatusChanged.connect(self._on_insert_media_status)
        self._insert_pending_seek_ms: int = -1   # setSource 후 mediaStatus 가 LoadedMedia 되면 seek
        self._insert_pending_play: bool = False
        self.addWidget(self._insert_surface)     # index 2

        # PreviewOverlay 자리 — 외부(VideoTab)가 set_overlay() 로 설치
        self._overlay: QWidget | None = None

        # ---------- HUD 오버레이 (좌상: 액션 토스트, 우상: 현재 시각) ----------
        # 영상 위에 떠있는 작은 라벨들 — QStackedWidget 의 자식으로 두고 raise_() 로 항상 위.
        hud_style = (
            "QLabel { background: rgba(0,0,0,170); color: white; "
            "padding: 4px 10px; border-radius: 6px; font-weight: bold; "
            "font-size: 12pt; }"
        )
        self._action_hud = QLabel(self)
        self._action_hud.setStyleSheet(hud_style)
        self._action_hud.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._action_hud.hide()
        self._action_hud_timer = QTimer(self)
        self._action_hud_timer.setSingleShot(True)
        self._action_hud_timer.setInterval(900)
        self._action_hud_timer.timeout.connect(self._action_hud.hide)

        self._time_hud = QLabel("0.00초", self)
        self._time_hud.setStyleSheet(hud_style)
        self._time_hud.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._time_hud.hide()  # 영상 로드 전엔 숨김

        # 배속 (speed) HUD — 구간 안에서 계속 표시 (flash 아님). 1× 일 땐 안 보임.
        # 사용자 결정 (2026-05-11): 배경 제거 + 흰 글씨 + 외곽선 (영상 위 가시성 확보).
        # QLabel CSS 로는 text-stroke 가 안 되므로 paintEvent override 가 필요한 별도
        # 위젯 _OutlinedLabel 사용.
        self._speed_hud = _OutlinedLabel(self)
        # Phase 19.5: 사용자가 마우스로 위치를 옮길 수 있게 드래그 활성.
        self._speed_hud.set_draggable(True)
        self._speed_hud.hide()

        # 시각 HUD 자동 갱신
        self.position_changed.connect(self._on_position_for_hud)
        self.duration_changed.connect(self._on_duration_for_hud)

    # ---------- HUD ----------
    def flash_action(self, text: str) -> None:
        """좌상단에 액션 토스트를 잠깐 띄운다 (앞으로/뒤로/프레임 등)."""
        self._action_hud.setText(text)
        self._action_hud.adjustSize()
        self._reposition_huds()
        self._action_hud.show()
        self._action_hud.raise_()
        self._action_hud_timer.start()

    def _on_position_for_hud(self, ms: int) -> None:
        seconds = max(0, ms) / 1000.0
        self._time_hud.setText(f"{seconds:.2f}초")
        self._time_hud.adjustSize()
        self._reposition_huds()

    def _on_duration_for_hud(self, ms: int) -> None:
        if ms > 0:
            self._time_hud.show()
            self._time_hud.raise_()

    def _reposition_huds(self) -> None:
        margin = 12
        self._action_hud.move(margin, margin)
        self._time_hud.move(
            max(margin, self.width() - self._time_hud.width() - margin),
            margin,
        )
        # 배속 HUD 는 시각 HUD 바로 아래. 사용자가 드래그로 옮겼다면 그 위치 우선.
        # 매 reposition 마다 새 텍스트로 adjustSize 한 폭으로 다시 계산 — 풀스크린
        # 전환 / 텍스트 길이 변경 후에도 안전한 위치.
        hud_w = self._speed_hud.sizeHint().width() or self._speed_hud.width()
        hud_h = self._speed_hud.sizeHint().height() or self._speed_hud.height()
        if self._speed_hud.isVisible():
            cp = self._speed_hud.custom_pos
            if cp is not None:
                # 풀스크린 등으로 부모 크기가 크게 변하거나 텍스트가 길어진 경우
                # custom_pos 가 화면 밖일 수 있다. clamp 후 화면 안에 보이지 않으면
                # default 위치로 폴백.
                cx = max(margin, min(self.width() - hud_w - margin, cp.x()))
                cy = max(margin, min(self.height() - hud_h - margin, cp.y()))
                # 폭이 부모보다 크면 단순히 좌측 margin 으로.
                if self.width() < hud_w + 2 * margin:
                    cx = margin
                if self.height() < hud_h + 2 * margin:
                    cy = margin
                self._speed_hud.move(cx, cy)
            else:
                self._speed_hud.move(
                    max(margin, self.width() - hud_w - margin),
                    margin + self._time_hud.height() + 6,
                )
        self._action_hud.raise_()
        self._time_hud.raise_()
        self._speed_hud.raise_()

    def show_speed_hud(self, rate: float, font_pt: int = 14) -> None:
        """배속 구간 진입 시 우상단(시각 HUD 바로 아래)에 지속 표시. 1× 면 hide."""
        if abs(float(rate) - 1.0) < 1e-3:
            self._speed_hud.hide()
            return
        self._speed_hud._font.setPointSize(max(8, int(font_pt)))
        # 1.5 → "1.5", 2.0 → "2", 10.0 → "10". rstrip("0") 은 소수점이 있을 때만
        # 안전 — 정수 "10" 에 적용하면 trailing 0 까지 깎여 "1" 이 되던 회귀.
        formatted = f"{float(rate):g}"
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        rate_label = formatted
        # ▶▶ = 더블 트라이앵글 (배속 의미). 텍스트로 SVG-feel.
        self._speed_hud.setText(f"▶▶  {rate_label}× 배속")
        self._speed_hud.adjustSize()
        # show() 를 먼저 호출해야 _reposition_huds 의 isVisible 가드 통과. 안 그러면
        # 이전 텍스트("2× 배속") 위치 그대로 두고 길어진 텍스트("10× 배속") 가
        # 그 자리에 그려져 화면 밖으로 삐져나감. 사용자 보고 회귀.
        self._speed_hud.show()
        self._reposition_huds()
        self._speed_hud.raise_()

    def hide_speed_hud(self) -> None:
        self._speed_hud.hide()

    def set_overlay(self, overlay: QWidget) -> None:
        """투명 오버레이 위젯을 비디오 surface 위에 자식으로 띄움."""
        if self._overlay is not None:
            self._overlay.setParent(None)
            self._overlay.deleteLater()
        self._overlay = overlay
        if overlay is not None:
            overlay.setParent(self)
            overlay.setGeometry(0, 0, self.width(), self.height())
            overlay.show()
            overlay.raise_()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition_huds()
        if self._overlay is not None:
            self._overlay.setGeometry(0, 0, self.width(), self.height())

    def load(self, path: Path) -> None:
        if self._movie is not None:
            self._movie.stop()
            try:
                self._movie.frameChanged.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._movie = None
        self._path = Path(path)
        self._is_gif = self._path.suffix.lower() in GIF_EXTS
        if self._is_gif:
            self._movie = QMovie(str(self._path))
            # CacheAll 은 RGBA 전체 프레임을 메모리에 보관 — native-res 스크린 녹화
            # GIF (예: 1920×1080×50프레임 ≈ 400MB) 에서 UI 가 응답 불가능해짐.
            # 기본 CacheNone 사용 — 역방향 스크럽 시 재디코드 비용은 감수.
            self._movie.frameChanged.connect(lambda _i: self._emit_position())
            self._gif_label.setMovie(self._movie)
            self._movie.jumpToFrame(0)
            self.setCurrentIndex(1)
            # frameCount() 는 GIF 전체 선형 스캔을 강제 — load() 반환 후 다음 이벤트
            # 루프 turn 에서 보내 메인 스레드 차단 시간을 끊는다.
            # 3-arg singleShot: self 가 destroy 되면 슬롯 취소 → 테스트 격리.
            QTimer.singleShot(0, self, lambda: self.duration_changed.emit(self._gif_total_ms()))
        else:
            self._video_surface.clear_frame()
            self._media.setSource(QUrl.fromLocalFile(str(self._path)))
            self.setCurrentIndex(0)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """위젯 닫힐 때 QMovie 를 확실히 정지·연결 해제해 dangling signal 방지."""
        self.release_file_handles()
        super().closeEvent(event)

    def release_file_handles(self) -> None:
        """현재 로드된 미디어의 OS 파일 핸들을 즉시 해제.

        Windows 에서 send2trash / os.remove 직전에 호출 — QMediaPlayer 와
        QMovie 가 둘 다 파일을 잡고 있으면 sharing violation 발생. closeEvent
        는 deleteLater→destruct 경로에서 발화하지 않으므로 명시 호출 필요.
        """
        try:
            self._media.stop()
            self._media.setSource(QUrl())
        except (RuntimeError, AttributeError):
            pass
        if self._movie is not None:
            try:
                self._movie.stop()
                self._movie.frameChanged.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._gif_label.setMovie(None)
            # Python ref 해제만으로는 Qt 가 QImageReader 의 QFile 을 즉시 안 닫음.
            # deleteLater + 호출자에서 processEvents/sendPostedEvents 로 강제해야 GIF
            # 파일 핸들이 풀려 send2trash 가 sharing violation 없이 통과.
            try:
                self._movie.deleteLater()
            except RuntimeError:
                pass
            self._movie = None

    def is_loaded(self) -> bool:
        return self._path is not None

    def set_thumbnail(self, img: QImage) -> None:
        """재생 전 미리보기 이미지 설정. 첫 프레임 도착 전까지 표시."""
        self._video_surface.set_thumbnail(img)

    def show_black_frame(self) -> None:
        """현재 영상 프레임을 검은 화면으로 즉시 갱신.

        SegmentPlaybackController 가 갭(gap) 구간 진입 시 호출. 일시정지 상태에서
        시각적으로 segment 가 끝났음을 보여줌. 다음 segment 활성화 시 새 프레임이
        도착하면 자동 복원.
        """
        self._video_surface.clear_frame()

    def set_zoom_preview(self, params: "tuple[float, float, float] | None") -> None:
        """Stage 3: zoom 미리보기 transform — _VideoSurface 에 위임."""
        self._video_surface.set_zoom_preview(params)

    def is_gif(self) -> bool:
        return self._is_gif

    def play(self) -> None:
        if not self.is_loaded():
            return
        if self._is_gif:
            assert self._movie is not None
            if self._movie.state() != QMovie.Running:
                self._movie.start()
                self.playing_changed.emit(True)
        else:
            self._media.play()

    def pause(self) -> None:
        if not self.is_loaded():
            return
        if self._is_gif:
            assert self._movie is not None
            if self._movie.state() == QMovie.Running:
                self._movie.setPaused(True)
                self.playing_changed.emit(False)
        else:
            self._media.pause()

    def toggle_play(self) -> None:
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def is_playing(self) -> bool:
        if not self.is_loaded():
            return False
        if self._is_gif:
            assert self._movie is not None
            return self._movie.state() == QMovie.Running
        return self._media.playbackState() == QMediaPlayer.PlayingState

    def stop(self) -> None:
        if self._is_gif and self._movie is not None:
            self._movie.stop()
            self.playing_changed.emit(False)
        else:
            self._media.stop()

    def position_ms(self) -> int:
        if not self.is_loaded():
            return 0
        if self._is_gif:
            assert self._movie is not None
            return self._gif_position_ms()
        return self._media.position()

    def duration_ms(self) -> int:
        if not self.is_loaded():
            return 0
        if self._is_gif:
            return self._gif_total_ms()
        return self._media.duration()

    def seek_ms(self, ms: int) -> None:
        if not self.is_loaded():
            return
        ms = max(0, min(ms, self.duration_ms()))
        if self._is_gif:
            assert self._movie is not None
            self._movie.jumpToFrame(self._gif_frame_at_ms(ms))
            return
        was_paused = self._media.playbackState() != QMediaPlayer.PlayingState
        self._media.setPosition(ms)
        # Qt6/WMF 회귀: 일시정지 상태에서 setPosition 만으론 새 프레임이 video sink
        # 에 도착하지 않을 때가 있다 → 사용자 입장에선 "재생 바 옮겨도 영상이 안 바뀜".
        # play()/pause() 한 사이클로 새 프레임 강제. 짧은 사이클이라 audio mute 임시.
        #
        # 단, 미디어가 아직 LoadedMedia 상태가 아닐 때 (setSource 직후 비동기 로딩 중)
        # play 를 호출하면 백엔드가 불안정해질 수 있다 → mediaStatus 확인 후 적용.
        if not was_paused:
            return
        try:
            status = self._media.mediaStatus()
        except (AttributeError, RuntimeError):
            return
        from PySide6.QtMultimedia import QMediaPlayer as _QMP
        ready = status in (
            _QMP.LoadedMedia, _QMP.BufferedMedia, _QMP.BufferingMedia, _QMP.EndOfMedia
        )
        if not ready:
            return
        prev_muted = self._audio.isMuted()
        self._suppress_state_signal = True
        try:
            self._audio.setMuted(True)
            self._media.play()
            self._media.pause()
        except RuntimeError:
            # Qt 객체 destroy 진행 중 — 무시.
            pass
        finally:
            try:
                self._audio.setMuted(prev_muted)
            except RuntimeError:
                pass
            self._suppress_state_signal = False

    def seek_seconds(self, delta_seconds: float) -> None:
        target = self.position_ms() + int(delta_seconds * 1000)
        self.seek_ms(target)

    def step_frame(self, direction: int) -> None:
        """direction = +1 다음, -1 이전. GIF·MP4 동일 인터페이스."""
        if not self.is_loaded():
            return
        if self._is_gif:
            assert self._movie is not None
            cur = self._movie.currentFrameNumber()
            total = self._movie.frameCount()
            if total <= 0:
                return
            self._movie.jumpToFrame((cur + direction) % total)
        else:
            # QMediaPlayer 는 정확한 프레임 단위 step 이 없음 — 33ms (~30fps) 점프로 근사
            step_ms = 33 if direction > 0 else -33
            self.seek_ms(self.position_ms() + step_ms)

    def set_playback_rate(self, rate: float) -> None:
        if self._is_gif:
            if self._movie is not None:
                self._movie.setSpeed(int(rate * 100))
        else:
            self._media.setPlaybackRate(rate)

    def set_volume(self, value: float) -> None:
        """0.0..1.0"""
        self._audio.setVolume(max(0.0, min(1.0, value)))

    def set_muted(self, muted: bool) -> None:
        self._audio.setMuted(muted)
        self._insert_audio.setMuted(muted)

    def is_muted(self) -> bool:
        return self._audio.isMuted()

    def has_audio(self) -> bool:
        return not self._is_gif

    def current_frame(self) -> QImage:
        """현재 표시 중인 프레임을 QImage 로 추출."""
        if self._is_gif and self._movie is not None:
            return self._movie.currentImage()
        return self._video_surface.current_image()

    def video_frame_rect(self) -> QRect:
        """비디오 프레임이 player 안에서 차지하는 letterbox 사각형 (player 좌표).

        오버레이를 영상 프레임 안에만 그리거나 드래그를 그 안에 가두기 위해 사용.
        GIF 의 경우 movie.scaledSize() 가 없어 단순화 — surface 전체를 반환.
        """
        if self._is_gif:
            return self.rect()
        return self._video_surface.video_frame_rect()

    def video_source_size(self) -> tuple[int, int]:
        """현재 영상 frame 의 원본 픽셀 크기 (w, h). 프레임 없으면 (0, 0).

        오버레이가 export 와 같은 source 좌표계에서 그리도록 painter 를 scale 할 때
        사용 — 창모드/풀스크린 사이 캡션 위치 일관성 (font 가 절대 픽셀이라 surface
        크기에 따라 bbox spread 가 달라지던 회귀) 해소.

        주의: 실제 decoded frame 만 source 로 인정. thumbnail 은 영상보다 작아
        (e.g., 320×180) source 좌표계로 쓰면 painter scale 이 5× 이상이 되어
        캡션이 일시적으로 거대하게 보이는 회귀 — 사용자가 seek 직후 캡션 진입 시
        보고함. frame 이 아직 없으면 (0, 0) 반환 → overlay 가 frame-px 좌표계 fallback.
        """
        if self._is_gif:
            return (self.width(), self.height())
        src = self._video_surface._frame
        if src.isNull():
            return (0, 0)
        return (src.width(), src.height())

    def _on_media_state(self, state) -> None:
        if self._suppress_state_signal:
            return
        self.playing_changed.emit(state == QMediaPlayer.PlayingState)

    def _gif_total_ms(self) -> int:
        # 가변 지연 GIF 미지원 — nextFrameDelay() 를 전체 공통 간격으로 간주
        if self._movie is None:
            return 0
        n = self._movie.frameCount()
        if n <= 0:
            return 1000
        per = self._movie.nextFrameDelay() if self._movie.nextFrameDelay() > 0 else 100
        return n * per

    def _gif_position_ms(self) -> int:
        if self._movie is None:
            return 0
        per = self._movie.nextFrameDelay() if self._movie.nextFrameDelay() > 0 else 100
        return self._movie.currentFrameNumber() * per

    def _gif_frame_at_ms(self, ms: int) -> int:
        if self._movie is None:
            return 0
        per = self._movie.nextFrameDelay() if self._movie.nextFrameDelay() > 0 else 100
        return max(0, min(ms // per, max(0, self._movie.frameCount() - 1)))

    def _emit_position(self) -> None:
        self.position_changed.emit(self.position_ms())

    # ---------- 보조 player API (Stage 4d — InsertPlaybackController 가 호출) ----------
    def set_insert_source(self, path, *, seek_ms: int = 0,
                           play_after_load: bool = False) -> None:
        """B 영상 로드. setSource 후 LoadedMedia 시그널이 와야 seek/play 가능하므로
        pending 값에 저장하고 _on_insert_media_status 에서 처리."""
        self._insert_pending_seek_ms = max(0, int(seek_ms))
        self._insert_pending_play = play_after_load
        self._insert_media.setSource(QUrl.fromLocalFile(str(path)))

    def play_insert(self) -> None:
        self._insert_media.play()

    def pause_insert(self) -> None:
        self._insert_media.pause()

    def stop_insert(self) -> None:
        self._insert_media.stop()
        self._insert_surface.clear_frame()

    def seek_insert_ms(self, ms: int) -> None:
        self._insert_media.setPosition(max(0, int(ms)))

    def show_insert_surface(self, on: bool) -> None:
        """index 2 (insert surface) 활성화 / 비활성화. 비활성 시 메인 surface 로 복귀."""
        if on:
            self.setCurrentIndex(2)
        else:
            # GIF 모드면 1, 아니면 0 (메인 영상).
            self.setCurrentIndex(1 if self._is_gif else 0)

    def insert_position_ms(self) -> int:
        return int(self._insert_media.position())

    def insert_duration_ms(self) -> int:
        return int(self._insert_media.duration())

    def _on_insert_media_status(self, status) -> None:
        """setSource 후 LoadedMedia 가 오면 pending 시크/재생 적용."""
        from PySide6.QtMultimedia import QMediaPlayer as _QMP
        if status != _QMP.MediaStatus.LoadedMedia:
            return
        if self._insert_pending_seek_ms >= 0:
            self._insert_media.setPosition(self._insert_pending_seek_ms)
            self._insert_pending_seek_ms = -1
        if self._insert_pending_play:
            self._insert_media.play()
            self._insert_pending_play = False
