"""BrollPipPlayer — broll 효과의 PIP 영상 재생.

한 영상 탭마다 인스턴스 1 개. 동시 활성 broll 은 모델상 1 개
(EditController 의 overlaps_existing 가 같은 type 시간 겹침 차단).
오디오 출력 없음 (v1 preview 무음).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

from ...effects import Sidecar
from ...effects.types.broll import BrollEffect


_DRIFT_THRESHOLD_MS = 300
"""PIP player 의 실제 position 과 main 의 expected position(broll 시간창 안
상대 ms) 차이 임계값. 사용자 시크는 물론, 자연 재생 중 디코더 lag 등으로
누적되는 drift 도 잡아 setPosition 재동기."""

# v1 broll 미리보기 대상 확장자. 이외 (.jpg, .png, .gif 등) 는 정지 이미지
# fallback (PreviewOverlay 의 thumbnail) 만 — QMediaPlayer 의 이미지 직접
# 재생 path 는 v2 보류.
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv"}


class BrollPipPlayer(QObject):
    """broll PIP 미리보기용 별도 QMediaPlayer 래퍼.

    main player 와 독립적으로 broll 영상을 재생해 PIP 박스에 실시간 frame 을
    공급한다. 시간창 매칭·재생 미러·drift 보정은 후속 task 에서 추가.
    """

    frame_ready = Signal(str, object)        # (effect_id, QImage)
    effect_deactivated = Signal(str)         # 직전 활성이었던 effect_id (cache 정리용)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        # 오디오 출력 미설정 = 무음 (preview 무음 정책).
        self._active_eff_id: Optional[str] = None
        self._loaded_src: Optional[str] = None
        self._intended_playing: bool = False   # main 의 play 상태 의도
        self._current_speed: float = 1.0
        self._last_seek_ms: int = -1
        self._sidecar: Optional[Sidecar] = None
        self._last_combined_ms: int = -1

    # ---------- 상태 조회 ----------
    def active_effect_id(self) -> Optional[str]:
        return self._active_eff_id

    def loaded_src(self) -> Optional[str]:
        return self._loaded_src

    # ---------- 활성/비활성 ----------
    def activate(self, src: str, effect_id: str) -> None:
        """broll src 로드 + 활성 id 설정. src 동일이면 setSource 재호출 안 함.

        직전 활성이 있던 채로 새 effect 로 전환되면 effect_deactivated(prev_id)
        emit — PreviewOverlay 가 stale live frame 캐시 정리.
        """
        prev = self._active_eff_id
        new_id = str(effect_id)
        self._active_eff_id = new_id
        src = str(src)
        if src != self._loaded_src:
            self._loaded_src = src
            self._player.setSource(QUrl.fromLocalFile(src))
        if prev is not None and prev != new_id:
            self.effect_deactivated.emit(prev)

    def deactivate(self) -> None:
        """활성 broll 없음. pause + 처음으로 seek. 직전 id 가 있으면 시그널 emit."""
        prev = self._active_eff_id
        self._active_eff_id = None
        self._player.pause()
        self._player.setPosition(0)
        if prev is not None:
            self.effect_deactivated.emit(prev)

    # ---------- main 미러 ----------
    def set_playing(self, on: bool) -> None:
        """main player 의 playing 상태 mirror. 활성 broll 없으면 pause 유지."""
        self._intended_playing = bool(on)
        if self._active_eff_id is None:
            self._player.pause()
            return
        if on:
            self._player.play()
        else:
            self._player.pause()

    def is_playing(self) -> bool:
        return self._intended_playing

    def set_speed(self, rate: float) -> None:
        """main 의 speed_changed mirror."""
        self._current_speed = max(0.1, float(rate))
        self._player.setPlaybackRate(self._current_speed)

    def current_speed(self) -> float:
        return self._current_speed

    def seek_to(self, broll_local_ms: int) -> None:
        """broll 영상 안 절대 위치(ms) 로 시크. broll.in_ms 변환은 호출자 책임."""
        ms = max(0, int(broll_local_ms))
        self._last_seek_ms = ms
        self._player.setPosition(ms)

    def last_seek_ms(self) -> int:
        return self._last_seek_ms

    # ---------- 사이드카 + 시간창 매칭 ----------
    def set_sidecar(self, sc: Sidecar) -> None:
        """현재 영상의 사이드카 갱신. 기존 활성 broll 이 새 사이드카에 없으면 deactivate."""
        self._sidecar = sc
        if self._active_eff_id is not None:
            found = any(
                isinstance(e, BrollEffect) and e.id == self._active_eff_id
                for e in sc.effects
            )
            if not found:
                self.deactivate()

    def on_combined_position_changed(self, combined_ms: int) -> None:
        """결합 시간축 현재 위치 → 활성 broll 결정 + 시크.

        - 시간창 진입: activate(src, id) + seek_to(combined - in_ms) + 의도가 play 면 play()
        - 시간창 이탈: deactivate()
        - 같은 broll 안에서 자연 재생: drift 보정은 Task 5.
        """
        if self._sidecar is None:
            return
        ms = int(combined_ms)
        self._last_combined_ms = ms
        active = self._find_active_broll(ms)
        if active is None:
            if self._active_eff_id is not None:
                self.deactivate()
            return
        if self._active_eff_id != active.id:
            # 새 진입.
            self.activate(active.src, active.id)
            self.seek_to(ms - active.in_ms)
            if self._intended_playing:
                self._player.play()
            return
        # 같은 broll. PIP 의 실제 position 과 expected (combined - in_ms) 의 차이가
        # 임계값을 넘으면 재시크. 사용자 슬라이더 jump 와 자연 재생 중 디코더 lag
        # (긴 broll 에서 누적되는 drift) 둘 다 잡힘. _player.position() 은 비동기
        # 디코딩 안 되면 0 — unit test 는 monkeypatch 로 inject.
        expected = ms - active.in_ms
        actual = self._player.position()
        if abs(expected - actual) > _DRIFT_THRESHOLD_MS:
            self.seek_to(expected)

    def _find_active_broll(self, combined_ms: int) -> Optional[BrollEffect]:
        if self._sidecar is None:
            return None
        # 2026-05-20: 전체/개별 토글 OFF 면 broll PIP 재생 안 함.
        for eff in self._sidecar.active_effects():
            if not isinstance(eff, BrollEffect):
                continue
            if eff.placement != "pip" or eff.pip is None:
                continue
            if not (eff.in_ms <= combined_ms < eff.out_ms):
                continue
            if not eff.src:
                continue
            # v1: 영상 확장자만 PIP player 가 처리. 이미지는 PreviewOverlay 의
            # thumbnail 로 fallback (BrollPipPlayer 가 활성화 안 되면 frame_ready
            # 도 안 옴 → live frame cache 비어 thumbnail 그려짐).
            from pathlib import Path
            if Path(eff.src).suffix.lower() not in _VIDEO_SUFFIXES:
                continue
            return eff
        return None

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
