"""BrollPipPlayer — broll 효과의 PIP 영상 재생.

한 영상 탭마다 인스턴스 1 개. 동시 활성 broll 은 모델상 1 개
(EditController 의 overlaps_existing 가 같은 type 시간 겹침 차단).
오디오 출력 없음 (v1 preview 무음).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink


class BrollPipPlayer(QObject):
    """broll PIP 미리보기용 별도 QMediaPlayer 래퍼.

    main player 와 독립적으로 broll 영상을 재생해 PIP 박스에 실시간 frame 을
    공급한다. 시간창 매칭·재생 미러·drift 보정은 후속 task 에서 추가.
    """

    frame_ready = Signal(str, object)   # (effect_id, QImage)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        # 오디오 출력 미설정 = 무음 (preview 무음 정책).
        self._active_eff_id: Optional[str] = None
        self._loaded_src: Optional[str] = None

    # ---------- 상태 조회 ----------
    def active_effect_id(self) -> Optional[str]:
        return self._active_eff_id

    def loaded_src(self) -> Optional[str]:
        return self._loaded_src

    # ---------- 활성/비활성 ----------
    def activate(self, src: str, effect_id: str) -> None:
        """broll src 로드 + 활성 id 설정. src 동일이면 setSource 재호출 안 함.

        eff_id 만 바뀌는 경우 (드물지만 같은 src 를 두 효과가 공유) 도 지원.
        """
        self._active_eff_id = str(effect_id)
        src = str(src)
        if src != self._loaded_src:
            self._loaded_src = src
            self._player.setSource(QUrl.fromLocalFile(src))

    def deactivate(self) -> None:
        """활성 broll 없음. pause + 처음으로 seek."""
        self._active_eff_id = None
        self._player.pause()
        self._player.setPosition(0)

    # ---------- 내부 ----------
    def _on_frame(self, frame) -> None:
        if self._active_eff_id is None:
            return
        # .copy() — Qt 6 ffmpeg 백엔드의 QVideoFrame.toImage() 는 frame 내부 버퍼
        # 공유 QImage 반환. detach 안 하면 frame 버퍼 누적 (메인 player 에서
        # 41s 재생 시 +19.8GB 누수 관측 — Phase 19.6 fix 와 동일 패턴).
        img = frame.toImage().copy()
        if img.isNull():
            return
        self.frame_ready.emit(self._active_eff_id, img)
