"""MP4/MKV/WebM (QMediaPlayer) + GIF (QMovie) 통합 플레이어 위젯."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QImage, QMovie, QPixmap, QPainter
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
from PySide6.QtWidgets import QStackedWidget, QLabel, QWidget


GIF_EXTS = {".gif"}


class _VideoSurface(QWidget):
    """QVideoSink → QPainter 소프트 렌더.

    QVideoWidget 은 Windows D3D11 native HWND 를 생성해 QLabel HUD 가 가려지므로,
    모든 렌더링을 Qt raster pipeline 으로 통일해 오버레이를 가능하게 한다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._frame: QImage = QImage()
        self._thumbnail: QImage = QImage()
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)

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

    def _on_frame(self, frame) -> None:
        img = frame.toImage()
        if not img.isNull():
            self._frame = img
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        src = self._frame if not self._frame.isNull() else self._thumbnail
        if not src.isNull():
            # SmoothTransformation = bilinear. Fast(=nearest neighbor) 로 두면 같은
            # mp4 인데도 플레이어에서만 픽셀이 깨져 보이는 회귀 (스크린샷은 원본
            # QImage 그대로라 선명). 화면 크기로 축소되는 일반 케이스에서 CPU 비용
            # 차이는 작고, 화질 차이는 즉시 체감됨.
            scaled = src.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
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
        self._action_hud.raise_()
        self._time_hud.raise_()

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
            self._movie.setCacheMode(QMovie.CacheAll)   # ← gotcha fix (see below)
            self._movie.frameChanged.connect(lambda _i: self._emit_position())
            self._gif_label.setMovie(self._movie)
            self._movie.jumpToFrame(0)
            self.setCurrentIndex(1)
            self.duration_changed.emit(self._gif_total_ms())
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
        else:
            self._media.setPosition(ms)

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

    def is_muted(self) -> bool:
        return self._audio.isMuted()

    def has_audio(self) -> bool:
        return not self._is_gif

    def current_frame(self) -> QImage:
        """현재 표시 중인 프레임을 QImage 로 추출."""
        if self._is_gif and self._movie is not None:
            return self._movie.currentImage()
        return self._video_surface.current_image()

    def _on_media_state(self, state) -> None:
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
