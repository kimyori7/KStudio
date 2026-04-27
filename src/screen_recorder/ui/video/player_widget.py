"""MP4/MKV/WebM (QMediaPlayer) + GIF (QMovie) 통합 플레이어 위젯."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, QSize
from PySide6.QtGui import QImage, QMovie, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QStackedWidget, QLabel


GIF_EXTS = {".gif"}


class PlayerWidget(QStackedWidget):
    """파일을 로드하면 종류에 맞춰 내부 재생기를 자동 선택한다."""

    playing_changed = Signal(bool)
    position_changed = Signal(int)   # ms
    duration_changed = Signal(int)   # ms

    def __init__(self) -> None:
        super().__init__()
        self._path: Optional[Path] = None
        self._is_gif = False

        # MP4 백엔드
        self._video_widget = QVideoWidget()
        self._media = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._media.setAudioOutput(self._audio)
        self._media.setVideoOutput(self._video_widget)
        self._media.playbackStateChanged.connect(self._on_media_state)
        self._media.positionChanged.connect(lambda v: self.position_changed.emit(int(v)))
        self._media.durationChanged.connect(lambda v: self.duration_changed.emit(int(v)))

        # GIF 백엔드
        self._gif_label = QLabel()
        self._gif_label.setAlignment(Qt.AlignCenter)
        self._gif_label.setStyleSheet("background-color: black;")
        self._movie: Optional[QMovie] = None

        self.addWidget(self._video_widget)  # index 0
        self.addWidget(self._gif_label)     # index 1

    def load(self, path: Path) -> None:
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
            self._media.setSource(QUrl.fromLocalFile(str(self._path)))
            self.setCurrentIndex(0)

    def is_loaded(self) -> bool:
        return self._path is not None

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
        pix: QPixmap = self._video_widget.grab()
        return pix.toImage()

    def _on_media_state(self, state) -> None:
        self.playing_changed.emit(state == QMediaPlayer.PlayingState)

    def _gif_total_ms(self) -> int:
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
