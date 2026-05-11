"""영상 탭 — PlayerWidget + PlayerControls + 곰/팟식 단축키."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtGui import QCursor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ..core.settings import PlayerHotkeys, PlayerSettings
from ..effects.types.caption import CaptionEffect
from ..effects.types.cut import CutEffect
from ..effects.types.speed import SpeedEffect
from .video.player_widget import PlayerWidget
from .video.player_controls import PlayerControls
from .video.timeline import VideoTimeline


# 풀스크린 컨트롤 오버레이 동작 상수
_FS_HIDE_DELAY_MS = 1000          # 재생 중 마우스 idle 시 숨김 지연
_FS_BOTTOM_BAND_PX = 180          # 하단에서 이 높이 안에 마우스가 들어오면 다시 표시 (controls + timeline 두 줄)

# ThumbnailService 결과 라우팅 — segment_id 가 이 prefix 로 시작하면 broll PIP 미리보기용.
_BROLL_THUMB_PREFIX = "broll:"


def _format_ms_label(ms: int) -> str:
    s = max(0, ms // 1000)
    cs = (ms % 1000) // 100
    return f"{s // 60:02d}:{s % 60:02d}.{cs}"


class VideoTab(QWidget):
    """단일 영상 탭. 메인 창에 들어갈 때만 단축키가 동작."""

    snapshot_requested = Signal(QImage, str)   # (이미지, 원본@시각 라벨)
    duration_resolved = Signal(int)            # ms — 영상 로드 후 실제 길이 확정
    trim_requested = Signal(object, int, int)  # 보존: 외부 (MCP/CLI) 호출용 — 현재 발화 지점 없음
    edit_mode_toggled = Signal(bool)           # 편집 모드 ON/OFF (실제 적용 후)
    # 사용자가 편집 토글을 요청 — MainWindow 가 받아 *모든* 영상 탭에 동시 적용 (전역 모드).
    edit_mode_change_requested = Signal(bool)
    export_requested = Signal()                # 편집 모드 컨트롤바의 출력 버튼 → MainWindow.
    effect_selected = Signal(object)           # Effect | None — MainWindow 인스펙터 패널용

    _DEFAULT_DURATION_MS: dict[str, int] = {
        "caption": 3000, "speed": 5000, "zoom": 2000,
        "broll": 5000, "cut": 1000,
    }

    def __init__(self, *, path: Path, source_label: str, duration_ms: int,
                 player_settings: PlayerSettings,
                 thumbnail: QImage | None = None,
                 player_hotkeys: PlayerHotkeys | None = None,
                 sidecar_dir: Path | None = None,
                 sidecar_path: Path | None = None) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        # 영상 탭 자체는 텍스트 입력을 받지 않으므로 IME 비활성화.
        # 한글 IME ON 상태에서 알파벳 키(T/C/D/F 등) 가 IME 에 가로채여 단축키가
        # 안 먹히는 문제를 방지. 자식 위젯(인스펙터의 QTextEdit 등) 은 영향 없음.
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self._source_label = source_label
        self._source_path = Path(path)
        self._settings = player_settings
        # 영상 플레이어 키 — main_window 가 settings 의 인스턴스를 그대로 넘김.
        # 사용자가 환경설정에서 키를 바꾸면 같은 인스턴스가 자동으로 반영.
        self._player_hotkeys = player_hotkeys or PlayerHotkeys()

        # 배속 구간 진입/이탈 추적 (Stage 5 — preview).
        # 현재 활성 SpeedEffect 의 id (없으면 None). position_changed 시 갱신해
        # 진입 시 player.set_playback_rate(rate), 이탈 시 1.0 으로 복원.
        self._active_speed_id: Optional[str] = None
        # 'mute' audio 모드 진입 시 이전 mute 상태를 보존했다가 이탈 시 복원.
        self._speed_prev_muted: Optional[bool] = None

        # 활성 선택 — Del 키가 무엇을 지울지 라우팅. 마지막에 클릭된 lane/segment 가 활성.
        # kind ∈ {"segment", "effect", None}. id 는 해당 객체의 id.
        self._active_kind: Optional[str] = None
        self._active_id: Optional[str] = None

        # 프레임 스킵 누적 — D/F 키와 ◀/▶ 버튼으로 프레임 단위 이동할 때마다 누적,
        # 다른 종류의 시크(슬라이더 드래그, 화살표 초단위 이동, Home/End) 가 일어나면 0 으로 리셋.
        # delta_ms 는 실제 player.position_ms 차이의 누적이라 단순히 N * 1/fps 가 아닌
        # 실제 영상 fps 와 정합하는 값.
        self._frame_step_accum: int = 0
        self._frame_step_accum_ms: int = 0

        # 풀스크린 오버레이 상태 — 진입 전엔 None, 진입 시 holder 위젯 + 타이머 세팅.
        # eventFilter 가 풀스크린이 아닐 때도 호출되므로 반드시 __init__ 에서 정의.
        self._fullscreen_holder: QWidget | None = None
        self._fs_hide_timer: QTimer | None = None

        self.player = PlayerWidget()
        self.controls = PlayerControls()

        # ---- 편집 모드 통합 (Stage 2) ----
        from .video.edit_controller import EditController
        from ..effects import default_sidecar_dir

        sc_dir = Path(sidecar_dir) if sidecar_dir is not None else default_sidecar_dir()
        # sidecar_path 명시 시 hash 매칭 우회하고 그 파일 직접 load — 사용자가 사이드카
        # 파일을 파일 열기로 직접 골랐을 때.
        self._edit_controller = EditController(
            self._source_path, sc_dir,
            sidecar_path=Path(sidecar_path) if sidecar_path else None,
        )
        self._edit_controller.sidecar_replaced.connect(self._on_sidecar_replaced)
        self._edit_controller.sidecar_replaced.connect(self._warm_caption_fonts)
        self._edit_controller.edit_mode_toggled.connect(self.edit_mode_toggled.emit)
        # Stage A: 사이드카가 비어 있으면 source 1 segment 로 자동 채움
        # (history baseline 도 새 segment 상태로 reset — 사용자가 undo 로 빈 트랙까지 안 감).
        self._edit_controller.ensure_default_track(
            source_duration_ms=int(duration_ms or 0),
        )
        # 사이드카에 캡션이 있으면 그 폰트들을 미리 measure → Qt 가 디스크에서 폰트
        # 읽고 glyph cache 빌드해 두므로 재생 중 첫 caption 진입 시 stutter 안 남.
        self._warm_caption_fonts(self._edit_controller.sidecar())
        # Stage A: 썸네일 서비스 — 사이드카 변경마다 모든 segment 의 썸네일을 비동기 요청.
        from ..services.thumbnail_extractor import ThumbnailExtractor
        from ..services.thumbnail_worker import ThumbnailRequest, ThumbnailService
        self._thumb_extractor = ThumbnailExtractor()
        self._thumb_service = ThumbnailService(self._thumb_extractor)
        self._thumb_request_cls = ThumbnailRequest
        self._edit_controller.sidecar_replaced.connect(self._request_all_thumbnails)

        # ---- VideoTimeline (Task 3) ----
        self.timeline = VideoTimeline()
        self.timeline.set_sidecar(self._edit_controller.sidecar())
        if duration_ms > 0:
            self.timeline.set_duration_ms(duration_ms)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.player, stretch=1)
        layout.addWidget(self.controls)
        layout.addWidget(self.timeline)

        # 편집 모드 OFF 일 땐 trim/effects 숨김 (slider 만 보임)
        self.timeline.set_edit_mode(False)

        # 모델 → 컨트롤
        self.player.duration_changed.connect(self.duration_resolved.emit)
        self.player.duration_changed.connect(self.timeline.set_duration_ms)
        self.player.duration_changed.connect(self.controls.set_duration_ms)
        # 첫 segment 의 src_duration_ms 가 비어 있으면 (init 시 duration_ms=0 로 들어온 경우)
        # player 가 실제 길이 로드한 시점에 채워주고 segment_ctrl·track lane 갱신.
        self.player.duration_changed.connect(self._on_player_duration_for_segment)
        self.player.playing_changed.connect(self.controls.set_playing)

        # 컨트롤 → 모델
        self.controls.play_toggled.connect(self._on_user_play_toggle)
        self.controls.volume_changed.connect(self.player.set_volume)
        self.controls.mute_toggled.connect(self._toggle_mute)
        self.controls.speed_changed.connect(self.player.set_playback_rate)
        self.controls.frame_step.connect(self._on_frame_step_button)
        self.controls.snapshot_request.connect(self._on_snapshot)
        self.controls.fullscreen_toggled.connect(self._on_fullscreen_toggled)
        # 편집 토글 클릭 → MainWindow 가 받아 전역 적용 (직접 _edit_controller 에 안 보냄).
        # 전역 라우팅이라 모든 영상 탭이 같이 켜지고 같이 꺼짐.
        self.controls.edit_mode_change_requested.connect(self.edit_mode_change_requested.emit)
        # 출력 버튼 → MainWindow 의 _on_export_video 로 bubble.
        self.controls.export_requested.connect(self.export_requested.emit)
        self._edit_controller.edit_mode_toggled.connect(self.controls.set_edit_mode_button)
        self._edit_controller.edit_mode_toggled.connect(self.timeline.set_edit_mode)

        # 썸네일 서비스 → VideoTab 핸들러 (broll src 와 segment id 를 prefix 로 구분).
        self._thumb_service.thumbnail_ready.connect(self._on_thumbnail_ready)
        # 처음 채워진 segment 의 썸네일도 즉시 요청.
        self._request_all_thumbnails(self._edit_controller.sidecar())

        # Timeline 시그널
        self.timeline.seek_request.connect(self._on_user_seek_request)
        self.timeline.trim_changed.connect(self._on_timeline_trim_changed)
        self.timeline.request_add.connect(self._on_lane_request_add)
        self.timeline.effect_selected.connect(self._on_effect_selected)
        self.timeline.effect_changed.connect(self._edit_controller.update_effect)
        self.timeline.effect_deleted.connect(self._edit_controller.remove_effect)
        # Stage B: VideoTrackLane 시그널들.
        track = self.timeline.video_track_lane
        track.request_split.connect(self._edit_controller.split_segment)
        track.request_delete.connect(self._edit_controller.delete_segment)
        track.request_insert_at.connect(self._on_track_insert_at)
        track.request_insert_files.connect(self._on_track_insert_files)
        track.segment_selected.connect(self._on_segment_selected)
        # Stage 1: 박스 드래그 → start_ms 변경 (clamp 는 EditController 에서).
        track.segment_position_changed.connect(self._edit_controller.set_segment_start)

        self.player.load(path)
        if thumbnail is not None and not thumbnail.isNull():
            self.player.set_thumbnail(thumbnail)
        self.controls.set_audio_enabled(self.player.has_audio())
        if duration_ms > 0:
            self.controls.set_duration_ms(duration_ms)

        # ---- PreviewOverlay (Stage 3a) ----
        from .video.preview_overlay import PreviewOverlay
        self._preview_overlay = PreviewOverlay()
        self.player.set_overlay(self._preview_overlay)
        # 영상 프레임 rect (letterbox 영역 제외) 를 매 paint 마다 player 에서 조회.
        # 이 rect 안에서만 캡션·줌·곁들임 가이드가 그려지고 드래그도 그 안으로 갇힌다.
        self._preview_overlay.set_video_frame_rect_provider(
            self.player.video_frame_rect
        )
        self._preview_overlay.set_sidecar(self._edit_controller.sidecar())
        # position 은 SegmentPlaybackController 가 emit 하는 combined 시간을 써야
        # effect.in_ms/out_ms (combined 기준) 와 시간창 매칭이 맞음. raw player.position_ms
        # 는 segment-local src 시간이라 NLE 갭 모델에서 단위 불일치.
        # _segment_ctrl 는 이 블록 아래에서 생성 — connect 는 거기로 옮겨감.
        self._edit_controller.sidecar_replaced.connect(self._preview_overlay.set_sidecar)
        self._preview_overlay.caption_position_changed.connect(
            self._edit_controller.update_effect
        )
        # 줌·곁들임 가이드 드래그 후 새 effect → update_effect.
        self._preview_overlay.effect_drag_changed.connect(
            self._edit_controller.update_effect
        )
        # Phase 19.4: 영상 위 박스를 클릭하면 그 effect 가 활성 선택이 되어 Del 키로 삭제 가능.
        self._preview_overlay.overlay_effect_clicked.connect(self._on_effect_selected)
        # Phase 19.5: broll PIP 박스 위에 외부 파일을 드롭하면 그 box 의 src 갱신.
        self._preview_overlay.overlay_broll_file_dropped.connect(self._on_overlay_broll_dropped)

        # ---- SegmentPlaybackController (Stage C — 새 트랙 모델) ----
        from .video.segment_playback import SegmentPlaybackController
        self._segment_ctrl = SegmentPlaybackController(self.player)
        self.player.position_changed.connect(self._segment_ctrl.on_main_position_changed)
        self._segment_ctrl.combined_position_changed.connect(self.timeline.set_position_ms)
        self._segment_ctrl.combined_position_changed.connect(self.controls.set_position_ms)
        self._segment_ctrl.combined_duration_changed.connect(self.timeline.set_duration_ms)
        self._segment_ctrl.combined_duration_changed.connect(self.controls.set_duration_ms)
        self._segment_ctrl.active_segment_changed.connect(
            self.timeline.video_track_lane.set_selected_id
        )
        # 사이드카 변경 → controller 의 segment 리스트 갱신.
        self._edit_controller.sidecar_replaced.connect(self._segment_ctrl.set_sidecar)
        # 초기 segment 리스트 적용.
        self._segment_ctrl.set_sidecar(self._edit_controller.sidecar())
        # Preview overlay 의 position 도 combined 시간을 받아 caption/zoom/broll 시간창 매칭.
        self._segment_ctrl.combined_position_changed.connect(self._preview_overlay.set_position_ms)

        # ---- Speed preview (Stage 5) ----
        # combined_position_changed 마다 활성 SpeedEffect 를 찾아 진입/이탈 시 rate 전환.
        # Phase 19.4: player.position_changed (raw src ms) → combined ms 로 시그널 변경.
        # 갭 모델에서 effect.in_ms/out_ms 는 combined timeline 기준이라 단위 일치 필요.
        self._segment_ctrl.combined_position_changed.connect(self._on_position_for_speed)
        # ---- Zoom preview (Stage 3, 2026-05-08) ----
        # ZoomEffect.preview=True 인 효과만 활성 구간에서 화면 zoom transform 적용.
        self._segment_ctrl.combined_position_changed.connect(self._on_position_for_zoom)
        # 사이드카 변경 후 평가는 다음 combined_position_changed emit 시 자동 — 별도 트리거 불필요.

    # ---------- API ----------
    def source_label(self) -> str:
        return self._source_label

    # ---------- 편집 모드 API ----------
    def is_edit_mode_on(self) -> bool:
        return self._edit_controller.is_edit_mode_on()

    def set_edit_mode(self, on: bool) -> None:
        self._edit_controller.set_edit_mode(on)
        self.timeline.set_edit_mode(on)

    def sidecar(self):
        return self._edit_controller.sidecar()

    def lanes_widget(self):
        """효과 lane 컨테이너 — 하위 호환. 신규 코드는 timeline.effect_lanes 사용."""
        return self.timeline.effect_lanes

    def edit_controller(self):
        return self._edit_controller

    # ---------- 효과 추가 흐름 ----------
    def _on_lane_request_add(self, effect_type: str, in_ms: int) -> None:
        """Lane 우클릭 → 효과 추가 요청. 편집 모드 체크 후 위임."""
        if not self.is_edit_mode_on():
            return
        self._add_effect_at(effect_type, in_ms)

    def _add_effect_at(self, effect_type: str, in_ms: int) -> bool:
        """현재 사이드카에 effect_type 의 새 효과를 in_ms 위치에 추가.

        영상 끝 가까우면 길이를 영상 끝까지 clamp. 100ms 미만으로 작으면 거부.
        """
        duration_ms = self._get_duration_ms()
        if duration_ms <= 0:
            return False
        default_len = self._DEFAULT_DURATION_MS.get(effect_type, 3000)
        out_ms = min(in_ms + default_len, duration_ms)
        if out_ms - in_ms < 100:
            return False
        if effect_type == "caption":
            eff = CaptionEffect(in_ms=in_ms, out_ms=out_ms)
        elif effect_type in ("cut", "cut_splice"):
            # "cut" = lane 우클릭 add (modifier 없는 기본은 splice).
            # "cut_splice" = 단축키 C 명시.
            eff = CutEffect(in_ms=in_ms, out_ms=in_ms)
        elif effect_type == "cut_range":
            half = 500
            start = max(0, in_ms - half)
            end = min(in_ms + half, duration_ms)
            if end - start < 100:
                return False
            eff = CutEffect(in_ms=start, out_ms=end)
        elif effect_type == "speed":
            # 기본 2.0× 배속 — 사용자가 인스펙터에서 자유롭게 변경 가능.
            eff = SpeedEffect(in_ms=in_ms, out_ms=out_ms, rate=2.0)
        elif effect_type == "zoom":
            # v1: 정적 줌 — 화면 중앙 (cx=0.5, cy=0.5) 에 2.0× 배율. 사용자가
            # 인스펙터에서 자유롭게 변경 가능. start == end 가정 (키프레임은 v2).
            from ..effects.types.zoom import ZoomEffect, ZoomPoint
            pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
            eff = ZoomEffect(in_ms=in_ms, out_ms=out_ms, start=pt, end=pt)
        elif effect_type == "broll":
            # v1: PiP — 우하단 30% 크기 기본. src 는 빈 문자열로 시작 — 인스펙터에서
            # 파일 선택. fullscreen 은 인스펙터에서 placement 변경 가능 (export v2).
            from ..effects.types.broll import BrollEffect, PipConfig
            eff = BrollEffect(
                in_ms=in_ms, out_ms=out_ms,
                placement="pip",
                pip=PipConfig(corner="bottom-right", size_ratio=0.3),
            )
        else:
            return False
        ok = self._edit_controller.add_effect(eff)
        if ok:
            # 추가된 효과를 인스펙터에 자동 포커스 — 사용자가 막대를 다시 클릭하지 않아도
            # 바로 편집 가능. effect_selected 시그널이 InspectorPanel 까지 전파.
            self.effect_selected.emit(eff)
        return ok

    def _get_duration_ms(self) -> int:
        d = self.player.duration_ms()
        if d > 0:
            return d
        return self.timeline.slider_lane.duration_ms()

    def _get_position_ms(self) -> int:
        return self.timeline.slider_lane.position_ms() or self.player.position_ms()

    def _on_sidecar_replaced(self, sc) -> None:
        self.timeline.set_sidecar(sc)

    def _request_all_thumbnails(self, sc) -> None:
        """사이드카의 모든 segment 의 필름스트립 고정 슬롯 + 모든 broll src 의 대표 프레임을 비동기 요청.

        - segment 슬롯: 길이(1초당 1슬롯) 로 결정 — 박스 폭 무관.
        - broll: src 1개당 0ms 한 프레임만 — PreviewOverlay PIP 가이드 안에 채움.
        같은 src 는 ThumbnailService 의 dedup + LRU 캐시로 한 번만 추출.
        """
        lane = self.timeline.video_track_lane
        for seg in sc.video_track:
            for src_ms in lane.thumbnail_slots_for(seg):
                self._thumb_service.request(self._thumb_request_cls(
                    segment_id=seg.id, src=seg.src, ms=int(src_ms),
                ))
        # broll 효과의 대표 프레임 — segment_id 자리에 broll 전용 prefix.
        from ..effects.types.broll import BrollEffect
        seen: set[str] = set()
        for eff in sc.effects:
            if not isinstance(eff, BrollEffect):
                continue
            src = eff.src or ""
            if not src or src in seen:
                continue
            seen.add(src)
            self._thumb_service.request(self._thumb_request_cls(
                segment_id=_BROLL_THUMB_PREFIX + src, src=src, ms=0,
            ))

    def _on_overlay_broll_dropped(self, effect_id: str, path: str) -> None:
        """영상 위 broll PIP 박스 위에 외부 파일 드롭 → 그 effect 의 src 갱신.

        BrollInspector 의 드롭과 동등 경로 — update_effect 가 history.push + autosave
        트리거. drop 후 자동으로 썸네일도 다시 요청됨 (sidecar_replaced chain).
        """
        from dataclasses import replace
        from ..effects.types.broll import BrollEffect
        for eff in self.sidecar().effects:
            if not isinstance(eff, BrollEffect) or eff.id != effect_id:
                continue
            try:
                new_eff = replace(eff, src=str(path))
            except ValueError:
                return
            self._edit_controller.update_effect(new_eff)
            return

    def _on_thumbnail_ready(self, key: str, ms: int, img) -> None:
        """ThumbnailService 결과 분기: broll prefix 면 PreviewOverlay 로, 아니면 트랙 lane 으로."""
        if key.startswith(_BROLL_THUMB_PREFIX):
            # init 도중 결과 도달 가능성 — _preview_overlay 아직 없으면 skip.
            overlay = getattr(self, "_preview_overlay", None)
            if overlay is None:
                return
            src = key[len(_BROLL_THUMB_PREFIX):]
            overlay.set_broll_thumbnail(src, img)
            return
        self.timeline.video_track_lane.set_thumbnail(key, int(ms), img)

    def _warm_caption_fonts(self, sidecar) -> None:
        """사이드카의 캡션이 쓸 폰트들을 미리 measure — Qt 가 디스크에서 폰트 로드
        + glyph cache 를 빌드하게 해 첫 caption 진입 시 stutter 제거.

        같은 (family, size, bold) 조합은 한 번만 워밍. fontMetrics 의
        horizontalAdvance("a") 를 호출하면 Qt 가 폰트 파일을 메모리에 올린다.
        """
        try:
            from PySide6.QtGui import QFont, QFontMetrics
            seen: set[tuple] = set()
            for eff in sidecar.effects:
                if getattr(eff, "type", "") != "caption":
                    continue
                font_info = getattr(eff, "font", None)
                if font_info is None:
                    continue
                key = (font_info.family, font_info.size, bool(font_info.bold))
                if key in seen:
                    continue
                seen.add(key)
                f = QFont(font_info.family, font_info.size)
                f.setBold(bool(font_info.bold))
                _ = QFontMetrics(f).horizontalAdvance("a")
        except Exception:
            pass

    def _on_player_duration_for_segment(self, ms: int) -> None:
        """player 가 실제 길이를 로드한 시점에 첫 segment 의 src_duration_ms 채움.

        영상 탭 init 시 duration_ms=0 으로 들어오면 ensure_default_track 이 만든 segment
        의 src_duration_ms 도 0. → duration_ms 가 0 이라 트랙 박스가 안 그려짐 / segment
        playback 도 끝점 검출 못 함. player 의 duration_changed 가 양수로 도착할 때
        보정해 트랙 lane / segment_ctrl / 썸네일 동기화.
        """
        if ms <= 0:
            return
        # __init__ 도중 player.load(path) 가 즉시 duration_changed 를 발화하면 본 핸들러
        # 가 _segment_ctrl 생성 전에 호출될 수 있다. 그 경우엔 defer — 어차피 init 끝에
        # 다시 set_sidecar 가 호출되니 무시해도 됨.
        if not hasattr(self, "_segment_ctrl"):
            return
        from dataclasses import replace
        sc = self._edit_controller.sidecar()
        if not sc.video_track:
            return
        first = sc.video_track[0]
        if first.src_duration_ms > 0:
            return
        # 직접 mutate (history push 안 함 — duration 보정은 사용자 액션 아님).
        sc.video_track[0] = replace(first, src_duration_ms=int(ms))
        self._segment_ctrl.set_sidecar(sc)
        self.timeline.set_sidecar(sc)
        self._request_all_thumbnails(sc)

    # ---------- Stage B: 트랙 segment 흐름 ----------
    def _on_segment_selected(self, segment_id: str) -> None:
        """segment 선택 시 그 segment 의 트랙상 시작 ms 로 시크 (combined timeline).

        Stage 1: start_ms 가 트랙 위치를 결정. SegmentPlaybackController 가 갭/segment
        라우팅 처리.

        활성 선택 갱신 — Del 키가 segment 를 지우도록. effect lane 의 선택은 해제.
        """
        sid = segment_id or None
        self._active_kind = "segment" if sid else None
        self._active_id = sid
        if sid:
            self._clear_effect_lane_selections()
        for seg in self.sidecar().video_track:
            if seg.id == segment_id:
                self._segment_ctrl.seek_combined_ms(int(seg.start_ms))
                return

    def _on_effect_selected(self, eff) -> None:
        """effect lane 또는 영상 위 박스에서 효과 선택/해제. None 이면 해제.

        활성 선택 갱신 — Del 키가 그 effect 를 지우도록. segment 선택은 해제.
        외부 InspectorPanel 로 시그널 재전파 (기존 동작 유지).
        영상 위 박스 클릭 경로도 같은 이 핸들러로 들어와 lane 시각 강조까지 동기화.
        """
        if eff is None:
            self._active_kind = None
            self._active_id = None
            self._clear_effect_lane_selections()
        else:
            self._active_kind = "effect"
            self._active_id = getattr(eff, "id", None)
            try:
                self.timeline.video_track_lane.set_selected_id(None)
            except (RuntimeError, AttributeError):
                pass
            # 효과 타입의 lane 만 선택 강조 + 나머지 lane 은 해제. 영상 위 박스 클릭으로
            # 들어온 경우에도 timeline lane 시각이 자동 따라옴.
            self._sync_effect_lane_selection(eff)
        self.effect_selected.emit(eff)

    def _sync_effect_lane_selection(self, eff) -> None:
        """eff 타입과 일치하는 effect_lane 만 _selected_id 갱신, 나머지는 해제."""
        try:
            lanes_widget = self.timeline.effect_lanes
        except AttributeError:
            return
        eff_type = getattr(eff, "type", None)
        eff_id = getattr(eff, "id", None)
        for lane_type, lane in getattr(lanes_widget, "_lanes", {}).items():
            try:
                lane._selected_id = eff_id if lane_type == eff_type else None
                lane.update()
            except (RuntimeError, AttributeError):
                pass

    def _clear_effect_lane_selections(self) -> None:
        """effect_lanes 의 모든 lane 선택을 해제 — segment 클릭 시 시각 일관성."""
        try:
            lanes = self.timeline.effect_lanes
        except AttributeError:
            return
        for lane in getattr(lanes, "_lanes", {}).values():
            try:
                lane._selected_id = None
                lane.update()
            except (RuntimeError, AttributeError):
                pass

    def _on_track_insert_files(self, paths: list, at_combined_ms: int) -> None:
        """드래그-드롭 / 라이브러리 드롭 → 여러 파일을 at_combined_ms 부터 순서대로 삽입.

        Stage 1: idx → start_ms 로 contract 변경. 새 segment 의 start_ms 를 명시.
        EditController.insert_segment 가 free-slot clamp 처리.
        """
        from dataclasses import replace
        cursor_ms = max(0, int(at_combined_ms))
        for p in paths:
            seg = self._build_segment_for_path(str(p))
            if seg is None:
                continue
            seg = replace(seg, start_ms=cursor_ms)
            self._edit_controller.insert_segment(
                at_idx=len(self.sidecar().video_track), segment=seg,
            )
            cursor_ms += seg.duration_ms

    def _on_track_insert_at(self, at_combined_ms: int) -> None:
        """우클릭 메뉴 → 트랙의 at_combined_ms 위치에 영상/이미지 파일을 삽입."""
        from PySide6.QtWidgets import QFileDialog
        from dataclasses import replace
        path_str, _filter = QFileDialog.getOpenFileName(
            self, "삽입할 영상/이미지 선택", "",
            "영상·이미지 (*.mp4 *.mov *.avi *.mkv *.webm *.gif *.png *.jpg *.jpeg)",
        )
        if not path_str:
            return
        new_seg = self._build_segment_for_path(path_str)
        if new_seg is None:
            return
        new_seg = replace(new_seg, start_ms=max(0, int(at_combined_ms)))
        self._edit_controller.insert_segment(
            at_idx=len(self.sidecar().video_track), segment=new_seg,
        )

    def _split_at_current_position(self) -> bool:
        """현재 재생 위치 (combined ms) 가 들어 있는 segment 를 그 자리에서 split.

        Stage 1: start_ms 기반 — 갭에 들어 있으면 거부.
        """
        pos_ms = self._get_position_ms()
        for seg in self.sidecar().video_track:
            if seg.start_ms < pos_ms < seg.end_ms:
                local_ms = pos_ms - seg.start_ms
                return self._edit_controller.split_segment(seg.id, at_local_ms=local_ms)
        return False

    def _build_segment_for_path(self, path_str: str) -> "Optional[object]":
        """파일 경로 → VideoSegment. 영상은 ffprobe 로 길이 채움, 이미지는 default."""
        from pathlib import Path as _Path
        from ..effects.segment import VideoSegment
        from ..services.media_probe import probe_duration_ms
        ext = _Path(path_str).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg"}:
            return VideoSegment(
                src=path_str, media_kind="image", image_duration_ms=3000,
            )
        if ext == ".gif":
            return VideoSegment(src=path_str, media_kind="gif", src_duration_ms=0)
        # 영상 — ffprobe 로 길이 조회.
        dur = probe_duration_ms(path_str)
        return VideoSegment(
            src=path_str, src_in_ms=0, src_out_ms=0,
            src_duration_ms=int(dur or 0), media_kind="video",
        )

    # ---------- Zoom preview (Stage 3) ----------
    def _on_position_for_zoom(self, ms: int) -> None:
        """현재 재생 위치에 preview=True 인 ZoomEffect 가 활성이면 화면에 zoom 적용.

        in_anim_ms / out_anim_ms 동안 scale 1.0 ↔ target 보간 (선형 ease 기본).

        Phase 19.5 hotfix6: 고배속 (5×) 에서 이 핸들러가 매 position tick 마다 발화함.
        zoom 효과가 없으면 즉시 종료해 import + 전체 effects 순회를 회피.
        """
        effects = self.sidecar().effects
        if not any(getattr(e, "type", "") == "zoom" for e in effects):
            self.player.set_zoom_preview(None)
            return
        from ..effects.types.zoom import ZoomEffect
        active = None
        for eff in effects:
            if not isinstance(eff, ZoomEffect):
                continue
            if not bool(getattr(eff, "preview", False)):
                continue
            if eff.in_ms <= ms < eff.out_ms:
                active = eff
                break
        if active is None:
            self.player.set_zoom_preview(None)
            return
        # scale 보간: 진입 구간 [in_ms, in_ms+in_anim_ms] 동안 1.0 → target.
        # 이탈 구간 [out_ms - out_anim_ms, out_ms] 동안 target → 1.0.
        target_scale = float(active.start.scale)
        in_anim = max(0, int(active.in_anim_ms))
        out_anim = max(0, int(active.out_anim_ms))
        rel = ms - active.in_ms
        until_end = active.out_ms - ms
        if in_anim > 0 and rel < in_anim:
            t = max(0.0, min(1.0, rel / in_anim))
            scale = 1.0 + (target_scale - 1.0) * self._ease(t, active.ease)
        elif out_anim > 0 and until_end < out_anim:
            t = max(0.0, min(1.0, until_end / out_anim))
            scale = 1.0 + (target_scale - 1.0) * self._ease(t, active.ease)
        else:
            scale = target_scale
        self.player.set_zoom_preview((
            float(active.start.cx),
            float(active.start.cy),
            float(scale),
        ))

    @staticmethod
    def _ease(t: float, kind: str) -> float:
        """0~1 → 0~1 보간. kind ∈ {'linear', 'in', 'out', 'in-out'}."""
        if kind == "linear":
            return t
        if kind == "in":
            return t * t
        if kind == "out":
            return 1.0 - (1.0 - t) ** 2
        # in-out (기본) — smoothstep.
        return t * t * (3.0 - 2.0 * t)

    # ---------- Speed preview (Stage 5) ----------
    def _on_position_for_speed(self, ms: int) -> None:
        """현재 재생 위치 → 활성 SpeedEffect 결정.

        구간 진입: player.set_playback_rate(eff.rate). audio='mute' 면 set_muted(True),
        이탈 시: rate=1.0 으로 복원, mute 도 이전 상태로 복원.

        v1: Qt 의 setPlaybackRate 가 자동으로 atempo 를 적용하므로 'atempo' / 'auto' 는
        구분 없이 같은 동작 (rate 만 설정). 'mute' 만 set_muted 로 별도 처리.

        Phase 19.5 hotfix6: 고배속 (5×) 시 매 tick 호출되므로 SpeedEffect 자체가
        없으면 즉시 종료 (현재 활성 구간 복원만 처리하고 loop 회피).
        """
        effects = self.sidecar().effects
        if not any(getattr(e, "type", "") == "speed" for e in effects):
            if self._active_speed_id is not None:
                self.player.set_playback_rate(1.0)
                self.player.hide_speed_hud()
                if self._speed_prev_muted is not None:
                    self.player.set_muted(self._speed_prev_muted)
                    self._speed_prev_muted = None
                self._active_speed_id = None
            return
        active_eff = None
        for eff in effects:
            if eff.type != "speed":
                continue
            if eff.in_ms <= ms < eff.out_ms:
                active_eff = eff
                break
        if active_eff is not None:
            if self._active_speed_id != active_eff.id:
                # 새 구간 진입 — rate 적용 + 지속 HUD (1× 면 hide).
                self.player.set_playback_rate(active_eff.rate)
                self.player.show_speed_hud(active_eff.rate)
                if active_eff.audio == "mute":
                    if self._speed_prev_muted is None:
                        self._speed_prev_muted = self.player.is_muted()
                    self.player.set_muted(True)
                else:
                    if self._speed_prev_muted is not None:
                        self.player.set_muted(self._speed_prev_muted)
                        self._speed_prev_muted = None
                self._active_speed_id = active_eff.id
        else:
            if self._active_speed_id is not None:
                # 구간 이탈 — rate 복원 + HUD 숨김. 1× 토스트는 보이지 않음 (사용자 결정).
                self.player.set_playback_rate(1.0)
                self.player.hide_speed_hud()
                if self._speed_prev_muted is not None:
                    self.player.set_muted(self._speed_prev_muted)
                    self._speed_prev_muted = None
                self._active_speed_id = None

    # ---------- 단축키 ----------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        m = event.modifiers()
        # Ctrl+E — 편집 모드 토글 (전역 라우팅 — MainWindow 가 모든 탭에 적용).
        if k == Qt.Key_E and (m & Qt.ControlModifier):
            self.edit_mode_change_requested.emit(not self.is_edit_mode_on())
            event.accept(); return
        # Ctrl+Z / Ctrl+Shift+Z (또는 Ctrl+Y) — 영상 편집(자르기/삽입/삭제) undo·redo.
        # screenshot tab 은 main_window 의 _on_undo (QUndoStack) 로 가지만,
        # VideoTab 은 EditController 의 자체 History 를 직접 호출.
        if k == Qt.Key_Z and (m & Qt.ControlModifier) and not (m & Qt.ShiftModifier):
            if self._edit_controller.undo():
                self.player.flash_action("↶ 되돌리기")
            event.accept(); return
        if (k == Qt.Key_Z and (m & Qt.ControlModifier) and (m & Qt.ShiftModifier)) \
                or (k == Qt.Key_Y and (m & Qt.ControlModifier)):
            if self._edit_controller.redo():
                self.player.flash_action("↷ 다시 실행")
            event.accept(); return
        # T — 편집 모드 ON 일 때만 캡션 추가 (현재 위치 + 기본 길이)
        if self.is_edit_mode_on() and k == Qt.Key_T and m == Qt.NoModifier:
            self._add_effect_at("caption", self._get_position_ms())
            event.accept(); return
        # 기존 C / Shift+C (cut 효과 추가) 는 새 트랙 모델에서 제거됨 (Stage D).
        # 자르기는 트랙 lane 의 우클릭 메뉴 또는 단축키 S 로.
        # Stage B 단축키 — S = 현재 위치에서 트랙 자르기, Delete = 선택된 segment 삭제.
        if self.is_edit_mode_on() and k == Qt.Key_S and m == Qt.NoModifier:
            if self._split_at_current_position():
                event.accept(); return
        if self.is_edit_mode_on() and k in (Qt.Key_Delete, Qt.Key_Backspace) and m == Qt.NoModifier:
            # 활성 선택에 따라 분기. effect 가 활성이면 effect 만, segment 가 활성이면 segment.
            # 어느 쪽도 아니면 no-op — 사용자가 lane 클릭 없이 Del 누른 경우 영상 보호.
            if self._active_kind == "effect" and self._active_id:
                self._edit_controller.remove_effect(self._active_id)
                event.accept(); return
            if self._active_kind == "segment" and self._active_id:
                self._edit_controller.delete_segment(self._active_id)
                event.accept(); return
            event.accept(); return
        if k == Qt.Key_Space:
            self.player.toggle_play()
            self._reset_frame_step_accum()
            event.accept(); return
        if k == Qt.Key_Right:
            delta = self._delta_for_modifier(m, sign=+1)
            self.player.seek_seconds(delta)
            self.player.flash_action(f"▶▶ +{abs(delta):g}초")
            self._reset_frame_step_accum()
            event.accept(); return
        if k == Qt.Key_Left:
            delta = self._delta_for_modifier(m, sign=-1)
            self.player.seek_seconds(delta)
            self.player.flash_action(f"◀◀ -{abs(delta):g}초")
            self._reset_frame_step_accum()
            event.accept(); return
        # 프레임 단위 이동 — PlayerHotkeys 에서 동적으로 가져옴.
        # KStudio 기본: D=이전 / F=다음. 곰플 호환: A=이전 / D=다음.
        if self._matches_player_key(event, self._player_hotkeys.frame_forward):
            self._do_frame_step(+1)
            event.accept(); return
        if self._matches_player_key(event, self._player_hotkeys.frame_back):
            self._do_frame_step(-1)
            event.accept(); return
        # G = 누적 프레임 스킵 카운터 수동 초기화 (현재 위치는 유지).
        if k == Qt.Key_G:
            had_accum = self._frame_step_accum != 0 or self._frame_step_accum_ms != 0
            self._reset_frame_step_accum()
            self.player.flash_action(
                "↺ 누적 프레임 스킵 0 으로 초기화" if had_accum
                else "↺ 누적 프레임 스킵 (이미 0)"
            )
            event.accept(); return
        if k == Qt.Key_Up:
            self._bump_volume(+0.1); event.accept(); return
        if k == Qt.Key_Down:
            self._bump_volume(-0.1); event.accept(); return
        if k == Qt.Key_M:
            self._toggle_mute(); event.accept(); return
        if k == Qt.Key_Less:
            self._bump_speed(-1); event.accept(); return
        if k == Qt.Key_Greater:
            self._bump_speed(+1); event.accept(); return
        if k == Qt.Key_Home:
            self.player.seek_ms(0)
            self.player.flash_action("⏮ 처음으로")
            self._reset_frame_step_accum()
            event.accept(); return
        if k == Qt.Key_End:
            self.player.seek_ms(self.player.duration_ms())
            self.player.flash_action("⏭ 끝으로")
            self._reset_frame_step_accum()
            event.accept(); return
        # ===== 트림 단축키 (편집 모드 ON 에서만) =====
        if self.is_edit_mode_on() and k == Qt.Key_BracketLeft:
            self._mark_trim("in", self.player.position_ms())
            self.player.flash_action("[ 시작점")
            event.accept(); return
        if self.is_edit_mode_on() and k == Qt.Key_BracketRight:
            self._mark_trim("out", self.player.position_ms())
            self.player.flash_action("] 끝점")
            event.accept(); return
        if k == Qt.Key_Escape:
            t = self.sidecar().trim
            if t.in_ms != 0 or t.out_ms != 0:
                self._edit_controller.update_trim(0, 0)
                self.player.flash_action("✕ 트림 해제")
                event.accept(); return
        # Ctrl+Enter 트림 즉시 실행은 제거 — Ctrl+Shift+E (export) 가 통합 처리.
        super().keyPressEvent(event)

    def _matches_player_key(self, event: QKeyEvent, hotkey_str: str) -> bool:
        """이벤트가 settings 의 단일 글자 단축키와 일치하는지. modifier 없는 단일 키 한정."""
        if not hotkey_str or len(hotkey_str) != 1:
            return False
        # modifier 가 있으면 단일 글자 키와 매칭 안 함 (Ctrl+D 가 D 와 매칭되지 않도록).
        if event.modifiers() not in (Qt.NoModifier, Qt.KeypadModifier):
            return False
        text = event.text()
        if not text:
            return False
        return text.upper() == hotkey_str.upper()

    def _on_frame_step_button(self, direction: int) -> None:
        """컨트롤바의 ◀/▶ 프레임 버튼 → 단축키와 동일하게 프레임 step + 누적 HUD."""
        self._do_frame_step(direction)

    def _do_frame_step(self, direction: int) -> None:
        """프레임 단위 이동 + 누적 카운터 갱신 + HUD 표시 (D/F 키 / ◀▶ 버튼 공통)."""
        before_ms = self.player.position_ms()
        self.player.step_frame(direction)
        after_ms = self.player.position_ms()
        delta_ms = after_ms - before_ms
        self._frame_step_accum += direction
        self._frame_step_accum_ms += delta_ms
        # HUD: 단발 표시 + 누적 (스킵 횟수 + 시간). 부호는 +N / -N 로 직관적으로 보이게.
        single = "+1 프레임" if direction > 0 else "-1 프레임"
        arrow = "▶" if direction > 0 else "◀"
        accum_n = self._frame_step_accum
        accum_sign = "+" if accum_n >= 0 else ""
        sec = self._frame_step_accum_ms / 1000.0
        sec_str = f"{sec:+.2f}초"
        self.player.flash_action(
            f"{arrow} {single} (누적 프레임 스킵 {accum_sign}{accum_n}, {sec_str})"
        )

    def _reset_frame_step_accum(self) -> None:
        self._frame_step_accum = 0
        self._frame_step_accum_ms = 0

    def _on_user_seek_request(self, ms: int) -> None:
        """슬라이더 드래그/클릭 또는 트림 레인 시크 — segment 시간축에서 시크."""
        self._reset_frame_step_accum()
        self._segment_ctrl.seek_combined_ms(int(ms))

    def _on_user_play_toggle(self) -> None:
        """재생 토글 (스페이스 / 컨트롤바 ▶ 버튼) — 누적 카운터 초기화."""
        self.player.toggle_play()
        self._reset_frame_step_accum()

    def _delta_for_modifier(self, m: Qt.KeyboardModifier, sign: int) -> float:
        if m & Qt.ControlModifier:
            return sign * self._settings.skip_large_seconds
        if m & Qt.ShiftModifier:
            return sign * self._settings.skip_medium_seconds
        return sign * self._settings.skip_seconds

    def _bump_volume(self, delta: float) -> None:
        cur = self.controls.volume_slider.value() / 100.0
        new = max(0.0, min(1.0, cur + delta))
        self.controls.volume_slider.setValue(int(new * 100))

    def _toggle_mute(self) -> None:
        new_muted = not self.player.is_muted()
        self.player.set_muted(new_muted)
        self.controls.set_muted(new_muted)

    def _bump_speed(self, direction: int) -> None:
        cur = self.controls.speed_combo.currentIndex()
        target = max(0, min(self.controls.speed_combo.count() - 1, cur + direction))
        self.controls.speed_combo.setCurrentIndex(target)

    def _on_trim_execute(self, in_ms: int, out_ms: int) -> None:
        """트림 즉시 실행 — 현재 호출자 없음.

        Ctrl+Enter 단축키 / PlayerControls 트림 버튼은 timeline 통합 시 제거됨.
        trim_requested 시그널은 보존 — 미래 MCP/CLI 외부 호출 진입점.
        """
        self.trim_requested.emit(self._source_path, int(in_ms), int(out_ms))

    def _mark_trim(self, side: str, ms: int) -> None:
        """[ / ] 키로 in 또는 out 마크. swap 정규화 후 EditController 에 영구 저장."""
        cur = self.sidecar().trim
        if side == "in":
            new_in, new_out = int(ms), cur.out_ms
        else:
            new_in, new_out = cur.in_ms, int(ms)
        # in 이 out 보다 뒤로 가면 swap
        if new_in and new_out and new_out < new_in:
            new_in, new_out = new_out, new_in
        self._edit_controller.update_trim(new_in, new_out)

    def _on_timeline_trim_changed(self, in_ms: int, out_ms: int) -> None:
        """timeline 의 in/out marker drag 후 시그널 — 사이드카에 영구 저장."""
        self._edit_controller.update_trim(int(in_ms), int(out_ms))

    def _on_snapshot(self) -> None:
        img = self.player.current_frame()
        if img.isNull():
            return
        ts = _format_ms_label(self.player.position_ms())
        label = f"{self._source_label} @ {ts}"
        self.snapshot_requested.emit(img, label)

    def _on_fullscreen_toggled(self) -> None:
        """플레이어 위젯을 단독으로 풀스크린에 띄움. Esc 로 복귀.

        풀스크린에서도 PlayerControls(재생/시크/볼륨 등) 를 유지해야 사용자가 영상을
        조작할 수 있다. 컨트롤바는 holder 의 자식 오버레이로 띄우고, 재생 중에는
        1초간 마우스 움직임이 없으면 자동으로 숨고, 마우스가 화면 하단 영역에 진입
        하면 다시 나타나는 표준 동작 (YouTube/VLC 와 동일).
        """
        # 이미 분리된 풀스크린 창이 있으면 닫기 (토글)
        if self._fullscreen_holder is not None:
            self._fullscreen_holder.close()
            return

        # 복귀 시 layout 의 원래 순서를 보존하기 위해 인덱스를 *modify 전* 에 캡처.
        # 한쪽을 reparent 한 뒤 indexOf 를 부르면 이미 줄어든 인덱스가 나와 복귀 시
        # 순서가 뒤집힘 (player 가 controls 뒤로 들어감 → 컨트롤바가 화면 상단에 나옴).
        player_index = self.layout().indexOf(self.player)
        ctrl_index = self.layout().indexOf(self.controls)
        timeline_index = self.layout().indexOf(self.timeline)

        # 새 top-level 창에 player 를 일시적으로 reparent.
        # holder 자체엔 layout 을 두지 않는다 — player 는 fillRect 로 깔고, controls
        # 는 raise_() 한 floating overlay 로 관리한다. 마우스 트래킹은 위젯별
        # setMouseTracking 대신 QApplication 글로벌 eventFilter 로 처리 (아래).
        holder = QWidget()
        holder.setWindowTitle("KStudio - 풀스크린")
        holder.setStyleSheet("background-color: black;")

        # player 를 holder 로 옮김 (원래 layout 에서 자동 분리)
        self.player.setParent(holder)
        self.player.show()
        self.player.setGeometry(0, 0, 1, 1)  # showFullScreen 후 resizeEvent 에서 정확히 잡음

        # controls 도 holder 의 자식으로 reparent — layout 이 아닌 floating overlay
        # 로 두어야 player 위에 겹쳐 그릴 수 있다.
        self.layout().removeWidget(self.controls)
        self.controls.setParent(holder)
        self.controls.show()
        # timeline (재생 슬라이더) 도 풀스크린에서 보여줌 — 사용자가 위치/길이 확인
        # 못해 답답하다는 보고 (이전엔 hide 처리). controls 와 함께 화면 하단에
        # floating overlay 로 띄움.
        self.layout().removeWidget(self.timeline)
        self.timeline.setParent(holder)
        self.timeline.show()

        # 자동 숨김 타이머
        hide_timer = QTimer(holder)
        hide_timer.setSingleShot(True)
        hide_timer.setInterval(_FS_HIDE_DELAY_MS)
        hide_timer.timeout.connect(lambda: self._fs_maybe_hide_controls())
        self._fs_hide_timer = hide_timer

        def _reposition_controls():
            ctrl_h = self.controls.sizeHint().height()
            tl_h = self.timeline.sizeHint().height()
            self.controls.setGeometry(
                0, holder.height() - ctrl_h, holder.width(), ctrl_h,
            )
            self.controls.raise_()
            # timeline 은 controls 바로 위에.
            self.timeline.setGeometry(
                0, holder.height() - ctrl_h - tl_h, holder.width(), tl_h,
            )
            self.timeline.raise_()

        def _on_resize(ev):
            self.player.setGeometry(0, 0, holder.width(), holder.height())
            _reposition_controls()
        holder.resizeEvent = _on_resize  # type: ignore[assignment]

        # 마우스 위치 추적 — _VideoSurface 까지 mouseTracking 을 전파하고 후크하는
        # 것은 깨지기 쉽다 (페인트만 하던 위젯에 입력 이벤트 흐름이 추가됨). 대신
        # QApplication 에 eventFilter 를 달아 mouseMove 이벤트를 한 곳에서 처리.
        # 풀스크린 진입 → 등록, 종료 → 해제하는 lifecycle 이라 비용도 작다.
        QApplication.instance().installEventFilter(self)

        def _restore():
            # player + controls 를 원래 자리에 복귀. 멱등 — 한 번만 실행되도록 가드.
            if self._fullscreen_holder is None:
                return
            self._fullscreen_holder = None
            self._fs_hide_timer = None
            try:
                QApplication.instance().removeEventFilter(self)
            except (AttributeError, RuntimeError):
                pass
            try:
                self.player.setParent(None)
                self.controls.setParent(None)
            except RuntimeError:
                pass
            try:
                self.timeline.setParent(None)
            except RuntimeError:
                pass
            # 진입 전과 동일한 순서로 복귀 (player_index, ctrl_index, timeline_index 는
            # 모두 modify 전에 잡아둔 값). 보통 player_index=0, ctrl_index=1, timeline_index=2.
            self.layout().insertWidget(player_index, self.player, stretch=1)
            self.layout().insertWidget(ctrl_index, self.controls)
            self.layout().insertWidget(timeline_index, self.timeline)
            self.player.show()
            self.controls.show()
            self.timeline.show()
            self.player.setFocus()

        # 닫힐 때(Esc 등) 복귀 처리
        original_keyPressEvent = holder.keyPressEvent
        def _key(ev):
            if ev.key() == Qt.Key_Escape:
                holder.close()
                return
            # F = 다음 프레임, Space = 재생/일시정지 — 풀스크린에서도 단축키 유지
            # 위해 video_tab 의 keyPressEvent 로 위임.
            self.keyPressEvent(ev)
            if not ev.isAccepted():
                original_keyPressEvent(ev)
        holder.keyPressEvent = _key   # type: ignore[assignment]

        # WA_DeleteOnClose 미적용 + 강한 참조(self._fullscreen_holder) 때문에
        # destroyed 시그널은 절대 발화하지 않는다. close 직전(closeEvent)에 복귀시켜
        # player 가 holder 의 자식 상태로 남아 사라지는 일을 방지.
        original_closeEvent = holder.closeEvent
        def _close(ev):
            _restore()
            original_closeEvent(ev)
        holder.closeEvent = _close   # type: ignore[assignment]

        holder.showFullScreen()
        self._fullscreen_holder = holder
        # 진입 직후엔 컨트롤 보임 → 1초 후 (재생 중이면) 숨김 시작
        _reposition_controls()
        if self.player.is_playing():
            hide_timer.start()

    # ---------- 풀스크린 컨트롤 오버레이 ----------
    def eventFilter(self, obj, ev) -> bool:  # type: ignore[override]
        """QApplication 전역 필터 — 풀스크린 동안만 활성. 마우스가 holder 내부에서
        움직일 때 컨트롤 표시/숨김을 결정한다. 다른 이벤트는 모두 그대로 통과.
        """
        if (self._fullscreen_holder is not None
                and ev.type() == QEvent.MouseMove):
            self._fs_handle_global_mouse_move()
        return super().eventFilter(obj, ev)

    def _fs_handle_global_mouse_move(self) -> None:
        holder = self._fullscreen_holder
        if holder is None:
            return
        # 글로벌 커서 → holder 로컬 좌표 변환. 다른 모니터/창 위로 마우스가 가도
        # 안전하게 무시.
        pos = holder.mapFromGlobal(QCursor.pos())
        if not (0 <= pos.x() < holder.width() and 0 <= pos.y() < holder.height()):
            return
        in_bottom_band = pos.y() >= holder.height() - _FS_BOTTOM_BAND_PX
        if in_bottom_band:
            self.controls.show()
            self.controls.raise_()
            self.timeline.show()
            self.timeline.raise_()
            if self._fs_hide_timer is not None:
                self._fs_hide_timer.stop()
        else:
            # 하단 밖 — 재생 중이면 1초 후 숨김. 일시정지 상태면 그대로 둠.
            if self.player.is_playing() and self._fs_hide_timer is not None:
                self._fs_hide_timer.start()

    def _fs_maybe_hide_controls(self) -> None:
        if self._fullscreen_holder is None:
            return
        if not self.player.is_playing():
            return  # 일시정지 중엔 숨기지 않음
        self.controls.hide()
        self.timeline.hide()
