"""영상 탭 — PlayerWidget + PlayerControls + 곰/팟식 단축키."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QEvent, QSize, QTimer, Signal
from PySide6.QtGui import QCursor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication, QSplitter, QVBoxLayout, QWidget

from ..core.settings import PlayerHotkeys, PlayerSettings
from ..effects.types.caption import CaptionEffect
from ..effects.types.cut import CutEffect
from ..effects.types.speed import SpeedEffect
from .video.player_widget import PlayerWidget
from .video.player_controls import PlayerControls
from .video.timeline import VideoTimeline


# 풀스크린 컨트롤 오버레이 동작 상수
_FS_HIDE_DELAY_MS = 3000          # 재생 중 마우스 idle 3초 후 모든 바 숨김
_FS_BOTTOM_BAND_PX = 180          # 하단 이 높이 안(컨트롤 위)에 마우스가 있으면 숨김 보류 (controls + timeline 두 줄)

# ThumbnailService 결과 라우팅 — segment_id 가 이 prefix 로 시작하면 broll PIP 미리보기용.
_BROLL_THUMB_PREFIX = "broll:"

# Qt 의 QWIDGETSIZE_MAX — setMaximumHeight 제한 해제용 (편집 모드 진입 시).
_WIDGET_MAX_H = 16777215

# 새 효과의 비례 기본 길이 — 영상이 길수록 새 블록도 길게 만들어 타임라인에서 잡기
# 쉽게 한다. 타임라인은 전체 영상을 폭에 맞춰 그리므로(가로 줌 1.0 기준) "영상 길이의
# N%" == "화면 폭의 N%". 길이 있는 오버레이/효과에만 적용하고, 정밀해야 하는 cut 류
# (마커·구간 삭제)는 고정 길이를 유지한다(긴 영상에서 90초짜리 기본 삭제는 위험).
_PROPORTIONAL_TYPES = frozenset({"caption", "speed", "zoom", "broll", "arrow", "rect"})
_PROPORTIONAL_RATIO = 0.05        # 영상 전체 길이의 5%
_PROPORTIONAL_CAP_MS = 90_000     # 상한 90초 — 매우 긴 영상의 과도한 기본 길이 방지


def default_effect_duration_ms(
    effect_type: str, total_ms: int, fixed_defaults: dict[str, int]
) -> int:
    """새 효과 1개의 기본 길이(ms).

    길이 있는 효과(caption/speed/zoom/broll/arrow)는 `max(효과별 고정 최소값,
    total*5%)` 를 90초로 상한해 영상이 길수록 블록도 길어지게 한다. 짧은 영상은
    고정 최소값이 살아 기존 동작 그대로. cut 류 등 나머지는 고정값을 그대로 반환.
    """
    floor = fixed_defaults.get(effect_type, 3000)
    if effect_type not in _PROPORTIONAL_TYPES:
        return floor
    scaled = int(max(0, total_ms) * _PROPORTIONAL_RATIO)
    return max(floor, min(scaled, _PROPORTIONAL_CAP_MS))


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
    # 사용자가 ▶▶ ON/OFF 버튼 클릭 → MainWindow 가 settings 에 저장 + 모든 영상 탭에 동기화.
    speed_effects_change_requested = Signal(bool)
    effect_selected = Signal(object)           # Effect | None — MainWindow 인스펙터 패널용

    _DEFAULT_DURATION_MS: dict[str, int] = {
        "caption": 3000, "speed": 5000, "zoom": 2000,
        "broll": 5000, "cut": 1000, "arrow": 2000, "rect": 2000,
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
        # 외부 파일 드래그-드롭 — VideoTab 자체는 더 이상 수락 안 함 (2026-05-12 회귀).
        # 사용자 보고: 발표용 폴더 .mp4 를 미리보기 영역 위로 드롭 → 의도치 않게
        # video_track 끝에 append 되어 11:40 분량으로 늘어남. UX 단서 부족 (preview 영역이
        # 너무 넓고, 드롭 시 무슨 일이 일어나는지 미리 안 알려줌).
        # 사용자 요청: "정확히 영상 바에 올려야만 추가". video_track_lane 의 자체 dropEvent
        # 가 lane 위 정확한 위치 드롭만 수락. 다른 영역(미리보기 등) 드롭은 무시.
        self.setAcceptDrops(False)
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
        self._speed_muted: bool = False      # 배속 구간(audio='mute') 동안 True
        self._manual_muted: bool = False     # M키/컨트롤 음소거 토글 상태
        # 배속 효과 일괄 켜기/끄기 — 런타임 플래그, 사이드카 미포함.
        self._speed_effects_enabled: bool = True

        # 활성 선택 — Del 키가 무엇을 지울지 라우팅. 마지막에 클릭된 lane/segment 가 활성.
        # kind ∈ {"segment", "effect", None}. id 는 해당 객체의 id.
        self._active_kind: Optional[str] = None
        self._active_id: Optional[str] = None
        # 효과 복사붙여넣기 (Ctrl+C / Ctrl+V). 선택된 효과의 deep copy + id 비움.
        # 붙여넣기 시 마우스 위치를 ms 로 환산해 in_ms 로 설정, duration 보존.
        self._effect_clipboard: object | None = None

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
        # 풀스크린 하위 레이아웃 상태 (2026-06-22): 풀스크린엔 재생용 floating overlay 와
        # 편집용 splitter 두 모드가 있고 편집 토글 시 오간다. holder 의 QVBoxLayout 참조,
        # 현재 편집 레이아웃인지 여부, 복귀 시 원위치 인덱스를 보관.
        self._fs_holder_layout: QVBoxLayout | None = None
        self._fs_edit_layout: bool = False
        self._fs_player_index: int = 0
        self._fs_ctrl_index: int = 1
        self._fs_timeline_index: int = 1

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
        # 마지막으로 사용한 캡션 폰트/크기/굵기 — 새 캡션 추가 시 직전 값 상속.
        # 사이드카가 갱신될 때마다 가장 최근 (in_ms 가장 큰) 캡션의 font 를 기록.
        from ..effects.types.caption import Font as _Font
        self._last_caption_font: _Font | None = None
        self._edit_controller.sidecar_replaced.connect(self._track_last_caption_font)
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

        # 영상-수준 액션 헤더 (~32px) — 자동편집 등.
        # QSplitter — preview (player + controls) ↔ timeline 사이 위/아래 핸들.
        # 사용자가 핸들 드래그로 timeline 영역 비중 조절 (긴 효과 라인 / 영상 위주 보기 토글).
        # collapsible 비활성 — 어느 쪽도 0 px 로 접히지 않게 보호.
        self._preview_container = QWidget()
        preview_layout = QVBoxLayout(self._preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        preview_layout.addWidget(self.player, stretch=1)
        preview_layout.addWidget(self.controls)

        self._main_splitter = QSplitter(Qt.Vertical)
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.setHandleWidth(6)
        self._main_splitter.addWidget(self._preview_container)
        self._main_splitter.addWidget(self.timeline)
        # 초기 비중 — preview 4 : timeline 1. 사용자가 드래그로 자유 조절.
        self._main_splitter.setStretchFactor(0, 4)
        self._main_splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._main_splitter)

        # 편집 모드 OFF 일 땐 trim/effects 숨김 (시크 바만 보임 — 일반 플레이어 모습)
        self.timeline.set_edit_mode(False)
        # 타임라인은 항상 visible — 재생 모드엔 시크 바 한 줄만 보이도록 max 높이를 묶고,
        # 편집 모드 진입 시 그 제한을 풀어 영상 트랙·효과 줄까지 편다 (_apply_timeline_layout).
        self._apply_timeline_layout(False)

        # 모델 → 컨트롤
        self.player.duration_changed.connect(self.duration_resolved.emit)
        # 회귀 fix: player.duration_changed 는 segment 전환마다 그 segment 의 source
        # 영상 길이로 발화 → timeline 의 set_duration_ms 를 덮어쓰면 효과 lane 들의
        # 시간축이 활성 segment 의 길이로 좁아져 캡션·배속·줌 의 절대 in_ms 위치가
        # 어긋남. 권위 있는 source 는 _segment_ctrl.combined_duration_changed (트랙
        # 전체 길이) — 그 단일 source 만 timeline/controls 에 연결.
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
        # 오디오 출력 장치 (2026-06-17) — Qt 가 모니터 HDMI 를 기본으로 잡아 "이 앱만 무음"이
        # 나는 문제 대응. 저장값(전역 PlayerSettings)을 player 에 복원·적용. 장치 선택 UI 는
        # 환경설정 → "영상 플레이어" 패널에 있고, 거기서 바뀌면 main_window 가 player 에 적용.
        # 플러그/기본변경 추종은 player_widget 자체 QMediaDevices 리스너가 처리한다.
        self.player.set_audio_output_device(self._settings.audio_output_device)
        self._edit_controller.edit_mode_toggled.connect(self.controls.set_edit_mode_button)
        self._edit_controller.edit_mode_toggled.connect(self.timeline.set_edit_mode)
        # 편집 OFF 시 splitter 의 timeline 영역을 0 으로 — 일반 플레이어 모습.
        # setChildrenCollapsible(False) 가 켜져 있어도 setSizes 로 0 지정 가능.
        self._edit_controller.edit_mode_toggled.connect(self._on_edit_mode_for_splitter)

        # 썸네일 서비스 → VideoTab 핸들러 (broll src 와 segment id 를 prefix 로 구분).
        self._thumb_service.thumbnail_ready.connect(self._on_thumbnail_ready)
        # 2026-05-14: 초기 thumbnail 디스패치는 *탭이 처음 보일 때까지 defer* — 사용자가
        # 한 번에 여러 탭을 열면 비가시 탭의 ffmpeg storm 이 가시 탭 로딩까지 막던 회귀
        # (app.log 09:51:00 — 3 영상 × 32 slot ≈ 90+ ffmpeg call 15초간 폭주). showEvent
        # 가 첫 발화될 때 한 번만 요청. 그 이후 사이드카 변경은 항상 즉시 dispatch (이미
        # sidecar_replaced.connect 로 연결됨).
        self._initial_thumbs_requested = False

        # 2026-05-22: 라이브러리 "이것저것 클릭" → N개 탭 누적 회귀.
        # QMediaPlayer 디코더 파이프라인을 비활성 탭에서도 들고 있어 Windows MF
        # 디코더 contention → 점점 느려짐. 두 가지 lazy 정책 도입:
        # 1) 탭 생성 시 player.load() 를 호출하지 않음 — showEvent 첫 발화 때 load.
        # 2) hideEvent (다른 탭으로 전환) 시 release_file_handles + 다음 show 때 reload
        #    (position 보존). 같은 탭 다시 보면 ~200ms 재로드 비용. 새 탭 클릭 비용
        #    (수 초) 보다 훨씬 짧음.
        # _thumbnail_pending: __init__ 인자로 받은 미리보기 이미지를 load 후에 적용하기
        # 위해 보관. set_thumbnail 은 load 없이도 동작하지만, release 후 reload 사이
        # 에서 frame surface 가 비워지므로 thumbnail 다시 그려야 함.
        self._media_loaded = False
        self._saved_position_ms = 0
        self._thumbnail_pending = thumbnail if thumbnail is not None and not thumbnail.isNull() else None
        # set_duration_ms / set_audio_enabled 등 player 의존 controls 초기화도 _ensure_player_loaded
        # 안에서 수행. 단 duration_ms 는 caller 가 알려준 값이라 player 와 무관 — 즉시 적용.
        self._duration_ms_initial = duration_ms

        # Timeline 시그널
        self.timeline.seek_request.connect(self._on_user_seek_request)
        self.timeline.trim_changed.connect(self._on_timeline_trim_changed)
        self.timeline.request_add.connect(self._on_lane_request_add)
        self.timeline.effect_selected.connect(self._on_effect_selected)
        self.timeline.effect_changed.connect(self._edit_controller.update_effect)
        self.timeline.effect_deleted.connect(self._edit_controller.remove_effect)
        # 2026-05-20 (사용자 요청): row 별 활성/비활성 토글 — edit_controller 가 history + autosave 처리.
        self.timeline.request_toggle_row_enabled.connect(
            self._edit_controller.set_row_enabled
        )
        # Stage B: VideoTrackLane 시그널들.
        track = self.timeline.video_track_lane
        track.request_split.connect(self._edit_controller.split_segment)
        track.request_delete.connect(self._edit_controller.delete_segment)
        track.request_insert_at.connect(self._on_track_insert_at)
        track.request_insert_files.connect(self._on_track_insert_files)
        track.segment_selected.connect(self._on_segment_selected)
        # Stage 1: 박스 드래그 → start_ms 변경 (clamp 는 EditController 에서).
        track.segment_position_changed.connect(self._edit_controller.set_segment_start)

        # player.load() 는 첫 showEvent 까지 defer (lazy load 정책 — 위 _media_loaded 주석 참조).
        # duration 은 caller 가 알려준 값이라 player 와 무관 — 즉시 controls 에 표시.
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
        # source 픽셀 크기 provider — caption 이 source 좌표계에서 그려져 export 와
        # 일관 + 창모드/풀스크린 사이에서도 같은 상대 위치 유지.
        self._preview_overlay.set_video_source_size_provider(
            self.player.video_source_size
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
        # 소스 파일 끝(EndOfMedia) → 다음 클립으로 진행. position_changed 가 segment-끝=
        # 소스-끝 경계에서 advance 를 놓쳐 "마지막 직전 클립에서 멈춤"하던 회귀의 보완 경로.
        self.player.media_ended.connect(self._segment_ctrl.on_media_ended)
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
        # ---- Cut skip (2026-05-19) ----
        # 사용자 보고: cut 효과가 사이드카 마커만이라 preview 에서 cut 콘텐츠가 그대로
        # 재생됨 → 사용자가 export 결과와 다른 화면을 봄. preview_skip=True (기본) 인
        # cut 구간 진입 시 out_ms 로 자동 점프해 export 결과를 미리 체감.
        self._segment_ctrl.combined_position_changed.connect(self._on_position_for_cut_skip)

        # ---- Broll PIP 실시간 재생 (Phase 20) ----
        # main 과 별도의 QMediaPlayer 로 broll src 재생 → frame 을 PreviewOverlay
        # PIP 박스 안에 그림. position/play/speed 미러.
        from .video.broll_pip_player import BrollPipPlayer
        self._broll_pip = BrollPipPlayer(self)
        self._broll_pip.set_sidecar(self._edit_controller.sidecar())
        self._edit_controller.sidecar_replaced.connect(self._broll_pip.set_sidecar)
        self._segment_ctrl.combined_position_changed.connect(
            self._broll_pip.on_combined_position_changed
        )
        self.player.playing_changed.connect(self._broll_pip.set_playing)
        self.controls.speed_changed.connect(self._broll_pip.set_speed)
        self._broll_pip.frame_ready.connect(self._on_broll_pip_frame)
        self._broll_pip.effect_deactivated.connect(
            self._preview_overlay.clear_broll_live_frame
        )

        # ---- WaveformService (파형 레인) ----
        from ..services.waveform_service import WaveformService
        from ..core.ffmpeg_check import find_ffmpeg
        _ff = find_ffmpeg()
        self._waveform_service = WaveformService(
            ffmpeg_path=str(_ff) if _ff else "ffmpeg", parent=self)
        self._waveform_service.waveform_ready.connect(
            lambda src, peaks: self.timeline.audio_track_lane.set_peaks(src, peaks)
        )
        # 초기 로드 시 파형 요청 — 이게 없으면 첫 진입에서 파형이 안 그려지고, 사용자가
        # 음소거 토글 등 사이드카를 처음 바꿀 때(_on_sidecar_replaced)서야 요청됐다.
        # ensure_default_track 은 시그널을 emit 하지 않으므로 init 에서 직접 1회 요청한다.
        self._request_waveforms(self._edit_controller.sidecar())
        # 음소거 토글 — AudioTrackLane 🔇 버튼 → sidecar + 미리보기 동기화.
        self.timeline.audio_mute_toggled.connect(self._on_audio_mute_toggled)

        # 영상 재생 단축키(←/→ seek)를 포커스가 컨트롤·타임라인·풀스크린 holder 에 있어도
        # 받도록 앱 전역 이벤트 필터를 영구 설치. VideoTab.keyPressEvent 는 VideoTab 이
        # 직접 포커스일 때만 발화 → 편집 모드/풀스크린에서 방향키가 안 먹히던 회귀 해결.
        # (eventFilter 가 mouseMove 풀스크린 자동 숨김도 같이 처리.) QObject 파괴 시
        # Qt 가 필터를 자동 제거하므로 명시적 해제 불필요.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ---------- API ----------
    def source_label(self) -> str:
        return self._source_label

    # ---------- 편집 모드 API ----------
    def _on_edit_mode_for_splitter(self, on: bool) -> None:
        """편집 모드 토글 시 타임라인 레이아웃 갱신 — 단일 funnel(_apply_timeline_layout).

        재생 모드: 타임라인 = 시크 바 한 줄(작은 고정 높이). 편집 모드: 영상 트랙 +
        효과 줄까지 펼침. 시크 바 자체는 두 모드 모두에서 보임.

        2026-06-22: 풀스크린 중이면 splitter 가 holder 로 옮겨가 있으므로 일반
        _apply_timeline_layout 대신 풀스크린 하위 레이아웃 전환(_fs_apply_sublayout)을
        탄다 — 편집 OFF 면 floating overlay(playbar 가 하단 복귀), ON 이면 splitter
        레이아웃(편집 UI 가 잘리지 않고 핸들로 크기 조절).
        """
        if self._fullscreen_holder is not None:
            self._fs_apply_sublayout(on)
        else:
            self._apply_timeline_layout(on)

    def _apply_timeline_layout(self, edit_on: bool) -> None:
        """편집 모드에 따라 splitter 에서 타임라인이 차지할 세로 공간을 결정한다.

        타임라인 위젯 자체는 항상 visible — 시크 바는 재생/편집 공통이라 숨기면 안 됨.
        재생 모드에선 타임라인 max 높이를 시크 바 한 줄로 묶어 player 가 나머지 세로를
        모두 차지하게 하고(일반 플레이어 모습), 편집 모드에선 그 제한을 풀고
        preview:timeline 을 적당한 비율로 배분한다.

        2026-06-04 회귀 fix: 이전엔 편집 OFF 시 타임라인을 통째로 hide 해 시크 바까지
        사라졌다. 이 단일 funnel 이 init / 편집 토글 / 풀스크린 복귀 세 진입점을 처리.
        """
        self.timeline.setVisible(True)
        if edit_on:
            # 높이 제한 해제 + 편집용 비율 배분 (preview 약 2/3, timeline 약 1/3).
            self.timeline.setMaximumHeight(_WIDGET_MAX_H)
            total = self._main_splitter.height()
            if total > 0:
                tl = max(220, total // 3)
                tl = min(tl, max(160, total - 160))
                self._main_splitter.setSizes([total - tl, tl])
        else:
            # 시크 바 한 줄 높이로 묶음 — splitter 가 player 에 나머지 공간을 양보.
            self.timeline.setMaximumHeight(self.timeline.playback_height())

    def is_edit_mode_on(self) -> bool:
        return self._edit_controller.is_edit_mode_on()

    def set_edit_mode(self, on: bool) -> None:
        self._edit_controller.set_edit_mode(on)
        self.timeline.set_edit_mode(on)

    def sidecar(self):
        return self._edit_controller.sidecar()

    def duration_ms(self) -> int:
        """현재 트랙의 combined 총 길이 (밀리초). 에이전트 도구·외부 호출용 공개 API.

        주의: 이 값은 **자르기/트림 적용 후** 의 재생 가능 길이. 원본 파일 길이가 필요하면
        [`source_duration_ms()`](src/screen_recorder/ui/video_tab.py:source_duration_ms) 사용.
        """
        return self._get_duration_ms()

    def source_duration_ms(self) -> int:
        """원본 미디어 파일의 길이 (밀리초) — cut/trim 적용 *전*. 에이전트가 사용자에게
        "이 영상은 X분짜리" 라고 설명할 때 참조해야 하는 값.

        2026-05-14 회귀: 에이전트가 duration_ms (combined, cuts 후) 만 보고 "이 영상은
        2분이네요" 라고 보고 → 사용자는 파일 자체를 3:24 로 알고 있어서 환각으로 오해.
        실제론 source=3:24, 적용된 cut 두 개로 combined=2:00. 둘 다 노출 필요.
        """
        return self.player.duration_ms()

    def position_ms(self) -> int:
        """현재 재생 위치 (밀리초). 에이전트 도구·외부 호출용 공개 API."""
        return self._get_position_ms()

    def source_path(self) -> str:
        """현재 영상 소스의 절대 경로 문자열."""
        return str(self._source_path)

    def lanes_widget(self):
        """효과 lane 컨테이너 — 하위 호환. 신규 코드는 timeline.effect_lanes 사용."""
        return self.timeline.effect_lanes

    def edit_controller(self):
        return self._edit_controller

    # ---------- 효과 추가 흐름 ----------
    def _on_lane_request_add(self, effect_type: str, in_ms: int,
                              track_idx: int = 0) -> None:
        """Lane 우클릭 → 효과 추가 요청. 편집 모드 체크 후 위임.

        2026-05-13: track_idx 추가 — 사용자가 *클릭한 row* 의 track_idx 에 효과가
        들어가도록. 빈 row 클릭 시 그 row 가 그대로 채워짐.
        """
        if not self.is_edit_mode_on():
            return
        self._add_effect_at(effect_type, in_ms, track_idx=track_idx)

    def _add_effect_at(self, effect_type: str, in_ms: int,
                       track_idx: int = 0) -> bool:
        """현재 사이드카에 effect_type 의 새 효과를 in_ms 위치에 추가.

        영상 끝 가까우면 길이를 영상 끝까지 clamp. 100ms 미만으로 작으면 거부.
        track_idx 는 multi-라인 type (caption/broll/arrow) 의 sub-lane row 지정 —
        사용자가 클릭한 row 가 그대로 그 row 에 채워지도록.
        """
        duration_ms = self._get_duration_ms()
        if duration_ms <= 0:
            return False
        default_len = default_effect_duration_ms(
            effect_type, duration_ms, self._DEFAULT_DURATION_MS)
        out_ms = min(in_ms + default_len, duration_ms)
        if out_ms - in_ms < 100:
            return False
        ti = max(0, int(track_idx))
        if effect_type == "caption":
            # 직전 사용 폰트/크기/굵기 가 있으면 상속 (세션 한정). 없으면 Font() 기본값.
            if self._last_caption_font is not None:
                eff = CaptionEffect(in_ms=in_ms, out_ms=out_ms,
                                    font=self._last_caption_font, track_idx=ti)
            else:
                eff = CaptionEffect(in_ms=in_ms, out_ms=out_ms, track_idx=ti)
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
                track_idx=ti,
            )
        elif effect_type == "arrow":
            # 기본 — 화면 좌측 30% 에서 우측 70% 로 향하는 빨간 화살표.
            from ..effects.types.arrow import ArrowEffect, Point
            eff = ArrowEffect(
                in_ms=in_ms, out_ms=out_ms,
                start=Point(x=0.3, y=0.5),
                end=Point(x=0.7, y=0.5),
                track_idx=ti,
            )
        elif effect_type == "rect":
            # 기본 — 화면 가운데에 가로로 살짝 넓은 빨간 테두리 사각형.
            from ..effects.types.rect import RectEffect, Point
            eff = RectEffect(
                in_ms=in_ms, out_ms=out_ms,
                start=Point(x=0.3, y=0.4),
                end=Point(x=0.7, y=0.6),
                track_idx=ti,
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
        """현재 트랙의 combined 총 길이. 다중 segment 면 모든 segment 합.

        회귀 fix: player.duration_ms() 는 활성 segment 의 source 영상 길이라
        다중 segment 트랙에선 일부만 반환 → 후반 segment 영역에 캡션 추가가
        out_ms > duration 검증으로 거부됐다. timeline.slider_lane 의 duration 이
        _segment_ctrl.combined_duration_changed 로부터 받은 권위 있는 값.
        """
        d = self.timeline.slider_lane.duration_ms()
        if d > 0:
            return d
        return self.player.duration_ms()

    def _get_position_ms(self) -> int:
        return self.timeline.slider_lane.position_ms() or self.player.position_ms()

    def set_audio_output_device(self, dev_id: str) -> None:
        """외부(환경설정)에서 출력 장치가 바뀌면 이 탭의 player 에 적용. "" = 기본 따라가기."""
        self.player.set_audio_output_device(dev_id or "")

    def _refresh_preview_mute(self) -> None:
        """미리보기 음소거 = 전역(sidecar.audio_muted) | 수동(M/컨트롤) | 배속 구간 mute.

        세 음소거 소스를 한 곳에서 OR 로 합쳐 player 에 적용 — 한 소스 변경이 다른
        소스를 덮어쓰던 desync(편집 시 수동 음소거 풀림 등) 방지.
        """
        try:
            muted = (bool(self._edit_controller.sidecar().audio_muted)
                     or self._manual_muted or self._speed_muted)
            self.player.set_muted(muted)
        except (RuntimeError, AttributeError):
            pass

    def _on_audio_mute_toggled(self, muted: bool) -> None:
        """파형 레인 🔇 토글 → sidecar.audio_muted 갱신 + 미리보기 음소거 동기화."""
        if self._edit_controller.set_audio_muted(muted):
            self._refresh_preview_mute()

    def _on_sidecar_replaced(self, sc) -> None:
        self.timeline.set_sidecar(sc)
        # Phase 28 — 인스펙터에서 zoom.preview 체크박스 등 토글 시점은 position_changed 가
        # 발화 안 함 (재생 중이 아니므로). 사이드카 갱신 시 즉시 zoom_preview 재계산해
        # 화면 갱신을 강제. preview=False 로 바뀌면 None 전달 → surface 가 다시 paint.
        try:
            cur_ms = int(self.player.position())
            self._on_position_for_zoom(cur_ms)
        except (AttributeError, RuntimeError):
            pass
        self._refresh_preview_mute()
        self._request_waveforms(sc)

    def _request_waveforms(self, sc) -> None:
        """트랙의 각 소스에 대해 오디오 파형을 요청. 캐시/dedup 있어 반복 호출 cheap.

        init·sidecar 교체·duration 확정 세 시점 모두에서 호출 — 어느 한 시점에 놓쳐도
        파형이 결국 그려지도록. (예전엔 sidecar_replaced 에서만 요청해, 첫 로드 후
        사용자가 음소거를 처음 누르기 전까진 파형이 안 보였다.)
        """
        for src in {s.src for s in sc.video_track}:
            self._waveform_service.request(src)

    def _track_last_caption_font(self, sc) -> None:
        """사이드카의 가장 최근 (in_ms 가장 큰) 캡션의 font 를 기록.

        새 캡션을 추가할 때 직전 사용 폰트/크기/굵기 를 상속. 세션 한정 — 탭 닫고
        다시 열면 초기화. 향후 settings 영속화 가능.
        """
        from ..effects.types.caption import CaptionEffect
        latest: CaptionEffect | None = None
        for eff in sc.effects:
            if isinstance(eff, CaptionEffect):
                if latest is None or eff.in_ms > latest.in_ms:
                    latest = eff
        if latest is not None:
            self._last_caption_font = latest.font

    def _request_all_thumbnails(self, sc) -> None:
        """사이드카의 모든 segment 의 필름스트립 고정 슬롯 + 모든 broll src 의 대표 프레임을 비동기 요청.

        - segment 슬롯: 길이(1초당 1슬롯) 로 결정 — 박스 폭 무관.
        - broll: src 1개당 0ms 한 프레임만 — PreviewOverlay PIP 가이드 안에 채움.
        같은 src 는 ThumbnailService 의 dedup + LRU 캐시로 한 번만 추출.

        2026-05-14: 탭이 보이지 않으면 dispatch defer — showEvent 까지 보류.
        이유: 여러 탭 동시 열기 시 비가시 탭의 ffmpeg storm 이 가시 탭 로딩까지 막던 회귀.
        """
        if not self.isVisible():
            # showEvent 가 깨우면 그때 dispatch.
            self._initial_thumbs_requested = False
            return
        lane = self.timeline.video_track_lane
        for seg in sc.video_track:
            # GIF 는 random-access 불가 — ffmpeg 가 매 슬롯마다 frame 0 부터 linear
            # decode → 슬롯 N 개 만큼 동일 파일을 N 번 풀스캔. 메인 GIF 보기 흐름에서
            # 트랙 lane 의 정보 가치가 작아 스킵.
            if seg.src.lower().endswith(".gif"):
                continue
            # 이미 가진 슬롯은 skip — 편집마다 전체 재요청 시 슬롯 총합 > 썸네일 캐시(100)
            # 면 매번 수백 개를 ffmpeg 로 재추출하던 폭풍(클립 많을수록 CPU/메모리 폭증) 방지.
            for src_ms in lane.missing_thumbnail_slots(seg):
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

    def _on_broll_pip_frame(self, effect_id: str, img) -> None:
        """BrollPipPlayer.frame_ready → PreviewOverlay 의 live frame 캐시 갱신."""
        self._preview_overlay.set_broll_live_frame(effect_id, img)

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
        # duration 이 확정된 뒤 한 번 더 — 파형 그리기는 seg.src_duration_ms>0 을
        # 요구하므로, init 요청의 peaks 가 dur=0 일 때 도착했어도 여기서 캐시 재emit.
        self._request_waveforms(sc)

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
        # 2026-06-17: 미리보기 overlay 핸들 게이트 동기화 — lane/인스펙터에서 선택해도
        # 화살표/사각형 끝점·모서리 핸들이 보이고, 해제 시 사라진다(꼭짓점 노출).
        try:
            self._preview_overlay.set_selected_effect_id(getattr(eff, "id", None) if eff else None)
        except (RuntimeError, AttributeError):
            pass
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

    def _paste_effect_at_cursor(self) -> None:
        """clipboard 의 효과를 deep copy → 마우스 위치 ms 를 in_ms 로, duration 보존.

        마우스가 timeline 영역 밖이면 현재 재생 위치 (playhead) 로 폴백.
        같은 type 시간 겹침 시 EditController 가 차단 — fallback 으로 가장 가까운
        빈 슬롯 (target_ms 이상의 첫 비어 있는 자리) 으로 자동 이동 후 1회 재시도.
        """
        from dataclasses import replace
        from PySide6.QtGui import QCursor
        import copy
        import uuid
        if self._effect_clipboard is None:
            return
        # advisor 지적: replace 는 top-level 만 복사. nested dataclass (Font / Stroke /
        # Position / Fade / PipConfig 등) 가 두 효과 인스턴스간 공유돼 잠재 corruption.
        # deepcopy 로 명시적 분리.
        eff = copy.deepcopy(self._effect_clipboard)
        # 마우스 글로벌 → slider_lane 로컬 x → ms.
        slider = self.timeline.slider_lane
        local = slider.mapFromGlobal(QCursor.pos())
        target_ms: int
        if 0 <= local.x() < slider.width() and 0 <= local.y() < slider.height():
            target_ms = slider._ms_for_pixel(int(local.x()))
        else:
            target_ms = self._get_position_ms()
        duration = max(100, int(eff.out_ms - eff.in_ms))
        timeline_end = self._get_duration_ms()
        if timeline_end > 0:
            target_ms = max(0, min(target_ms, max(0, timeline_end - duration)))
        # 같은 type 의 효과들과 겹치지 않는 빈 슬롯으로 자동 이동.
        target_ms = self._find_free_slot_for_paste(eff, target_ms, duration)
        new_eff = replace(eff, id=str(uuid.uuid4()),
                          in_ms=int(target_ms), out_ms=int(target_ms + duration))
        ok = self._edit_controller.add_effect(new_eff)
        if ok:
            self.player.flash_action("📋 효과 붙여넣기")
        else:
            self.player.flash_action("⚠ 붙여넣기 실패 — 빈 자리가 없음")

    def _find_free_slot_for_paste(self, eff, target_ms: int, duration: int) -> int:
        """같은 type + 같은 track_idx 의 효과들과 [target_ms, target_ms+duration) 가
        겹치면 그 이후 첫 빈 자리로 이동. 영상 끝을 넘으면 target_ms 그대로.

        Phase 21: track_idx 가 다르면 같은 type 이라도 동시 가능 — auto_shift 도 같은
        track_idx 안에서만.
        """
        timeline_end = self._get_duration_ms() or (target_ms + duration)
        target_type = getattr(eff, "type", "")
        target_ti = getattr(eff, "track_idx", 0)
        same_type = sorted(
            (e for e in self.sidecar().effects
             if getattr(e, "type", "") == target_type
             and getattr(e, "track_idx", 0) == target_ti),
            key=lambda e: e.in_ms,
        )
        cursor = target_ms
        for existing in same_type:
            if cursor + duration <= existing.in_ms:
                # 이 구간 비어 있음.
                return cursor
            if cursor < existing.out_ms:
                # 겹침 — 이 효과 끝으로 이동.
                cursor = existing.out_ms
        # 마지막까지 — timeline 끝을 넘지 않는 한 그대로.
        if cursor + duration <= timeline_end:
            return cursor
        return target_ms   # 빈 자리 없음 — add_effect 가 거부, 호출자가 flash 안내

    _ACCEPTED_VIDEO_DROP_SUFFIXES = {
        ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv", ".gif",
        ".png", ".jpg", ".jpeg",
    }

    def dragEnterEvent(self, event) -> None:
        """외부 파일 드래그 진입 — 영상/이미지 확장자만 수락."""
        md = event.mimeData()
        if not md.hasUrls():
            event.ignore()
            return
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if not any(
            Path(p).suffix.lower() in self._ACCEPTED_VIDEO_DROP_SUFFIXES
            for p in paths
        ):
            event.ignore()
            return
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        """재생 화면 / timeline 빈 영역에 영상·이미지 드롭.

        사용자 의도 "뒤나 앞에 붙어야 되는데" — 드롭 위치 x 가 widget 의 왼쪽
        절반이면 timeline 0 위치에 prepend (기존 segment 들 뒤로 shift),
        오른쪽 절반이면 끝에 append.

        트랙 lane 위 정확한 위치 드롭은 VideoTrackLane.dropEvent 가 먼저 catch
        (Qt 자식 우선 전파). 여기로 도달하는 건 lane 외 영역 드롭.
        """
        md = event.mimeData()
        if not md.hasUrls():
            event.ignore()
            return
        paths = [
            u.toLocalFile() for u in md.urls()
            if u.isLocalFile()
            and Path(u.toLocalFile()).suffix.lower() in self._ACCEPTED_VIDEO_DROP_SUFFIXES
        ]
        if not paths:
            event.ignore()
            return
        # 드롭 x 위치 — widget 의 왼쪽 절반이면 prepend, 오른쪽이면 append.
        drop_x = int(event.position().x())
        is_left_half = drop_x < self.width() // 2
        if is_left_half:
            self._prepend_files_to_track(paths)
        else:
            track = self.sidecar().video_track
            end_ms = max((seg.start_ms + seg.duration_ms for seg in track), default=0)
            self._on_track_insert_files(paths, end_ms)
        event.acceptProposedAction()

    def _prepend_files_to_track(self, paths: list) -> None:
        """파일 들을 timeline 0 위치에 prepend — 기존 segment 들을 새 segment 들의
        총 길이만큼 뒤로 밀고 새 segment 를 0 부터 순서대로 배치.

        set_segment_start 루프 방식은 free-slot clamp 때문에 silently 실패할 수
        있어 (먼저 옮긴 segment 가 뒤 slot 을 차지하면 다음 segment 가 clamp).
        atomic 한 사이드카 교체로 한 번에 처리.
        """
        from dataclasses import replace
        import copy as _copy
        # 1) 새 segment 들 빌드 + 총 길이.
        new_segs = []
        cursor = 0
        for p in paths:
            seg = self._build_segment_for_path(str(p))
            if seg is None:
                continue
            new_segs.append(replace(seg, start_ms=cursor))
            cursor += seg.duration_ms
        if not new_segs:
            return
        total_new = cursor
        # 2) 사이드카 atomic 갱신 — 기존 segment 들 shift + 새 segment 앞에 prepend.
        new_sc = _copy.deepcopy(self._edit_controller.sidecar())
        shifted_existing = [replace(s, start_ms=s.start_ms + total_new) for s in new_sc.video_track]
        # 효과들도 같은 delta 만큼 동반 이동 (set_segment_start 의 "효과 따라감" 정책 유지).
        new_sc.effects = [
            replace(e, in_ms=e.in_ms + total_new, out_ms=e.out_ms + total_new)
            for e in new_sc.effects
        ]
        new_sc.video_track = new_segs + shifted_existing
        self._edit_controller.update_sidecar(new_sc)

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
        # 2026-05-20: active_effects() — 전체/개별 토글 OFF 면 zoom transform 해제.
        effects = self.sidecar().active_effects()
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
            str(getattr(active, "mode", "fit_screen")),
            float(getattr(active, "region_w", 0.3)),
            float(getattr(active, "region_h", 0.3)),
            float(getattr(active, "dest_cx", active.start.cx)),
            float(getattr(active, "dest_cy", active.start.cy)),
            float(getattr(active, "dest_w", getattr(active, "region_w", 0.3) * scale)),
            float(getattr(active, "dest_h", getattr(active, "region_h", 0.3) * scale)),
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

    # ---------- Cut skip (2026-05-19) ----------
    def _on_position_for_cut_skip(self, ms: int) -> None:
        """playhead 가 preview_skip=True 인 cut 구간 진입 시 out_ms 로 점프.

        사용자 보고: cut 효과는 사이드카 마커만이라 preview 재생에서 잘려야 할 콘텐츠가
        그대로 보임 → export 결과와 화면 불일치. 자동 skip 으로 WYSIWYG 회복.

        seek loop 방지: out_ms 도 같은 cut 안이라면 다음 tick 에 또 점프하지만,
        find_cut_skip_target 가 in_ms <= ms < out_ms 만 매치하므로 out_ms 정확
        도달 시점에 다시 매치되지 않음 — 안전.
        """
        from ..effects.types.cut import find_cut_skip_target
        # 2026-05-20: active_effects() — 전체/개별 토글 OFF 면 skip 안 함.
        target = find_cut_skip_target(self.sidecar().active_effects(), ms)
        if target is None:
            return
        # 자기 자신을 다시 트리거 안 하도록 seek 만 — 정상 재생 흐름은 SegmentPlaybackController
        # 가 알아서.
        self._segment_ctrl.seek_combined_ms(int(target))

    # ---------- Speed preview (Stage 5) ----------
    def _on_speed_effects_toggled(self, enabled: bool) -> None:
        """사용자 클릭 — 로컬 적용 + MainWindow 로 bubble (settings 저장 + 다른 탭 동기화)."""
        self._apply_speed_effects_enabled(enabled)
        self.speed_effects_change_requested.emit(enabled)

    def set_speed_effects_enabled(self, enabled: bool) -> None:
        """외부(MainWindow 전역 동기화) 에서 호출 — 플래그 + rate 즉시 적용.
        UI 토글은 SpeedInspector 의 버튼으로 이동 (PlayerControls 에서 제거됨)."""
        self._apply_speed_effects_enabled(enabled)

    def _apply_speed_effects_enabled(self, enabled: bool) -> None:
        self._speed_effects_enabled = enabled
        if not enabled:
            # 끈 즉시 rate 1.0 복원 + HUD 숨김.
            self.player.set_playback_rate(1.0)
            self.player.hide_speed_hud()
            self._speed_muted = False
            self._refresh_preview_mute()
            self._active_speed_id = None

    def _on_position_for_speed(self, ms: int) -> None:
        """현재 재생 위치 → 활성 SpeedEffect 결정.

        구간 진입: player.set_playback_rate(eff.rate). audio='mute' 면 set_muted(True),
        이탈 시: rate=1.0 으로 복원, mute 도 이전 상태로 복원.

        v1: Qt 의 setPlaybackRate 가 자동으로 atempo 를 적용하므로 'atempo' / 'auto' 는
        구분 없이 같은 동작 (rate 만 설정). 'mute' 만 set_muted 로 별도 처리.

        Phase 19.5 hotfix6: 고배속 (5×) 시 매 tick 호출되므로 SpeedEffect 자체가
        없으면 즉시 종료 (현재 활성 구간 복원만 처리하고 loop 회피).
        """
        if not self._speed_effects_enabled:
            return
        # 2026-05-20: active_effects() — 전체/개별 토글 OFF 면 rate 1.0 으로 복원.
        effects = self.sidecar().active_effects()
        if not any(getattr(e, "type", "") == "speed" for e in effects):
            if self._active_speed_id is not None:
                self.player.set_playback_rate(1.0)
                self.player.hide_speed_hud()
                self._speed_muted = False
                self._refresh_preview_mute()
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
                self.player.show_speed_hud(active_eff.rate, font_pt=active_eff.hud_font_pt)
                self._speed_muted = (active_eff.audio == "mute")
                self._refresh_preview_mute()
                self._active_speed_id = active_eff.id
        else:
            if self._active_speed_id is not None:
                # 구간 이탈 — rate 복원 + HUD 숨김. 1× 토스트는 보이지 않음 (사용자 결정).
                self.player.set_playback_rate(1.0)
                self.player.hide_speed_hud()
                self._speed_muted = False
                self._refresh_preview_mute()
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
        # Ctrl+C — 활성 효과 복사. Ctrl+V — 마우스 위치에 붙여넣기.
        # 캡션·배속·줌·곁들임 박스 선택 후 Ctrl+C, 다음 위치에서 Ctrl+V.
        if k == Qt.Key_C and (m & Qt.ControlModifier) and not (m & Qt.ShiftModifier):
            if self._active_kind == "effect" and self._active_id:
                eff = next(
                    (e for e in self.sidecar().effects if getattr(e, "id", None) == self._active_id),
                    None,
                )
                if eff is not None:
                    self._effect_clipboard = eff
                    self.player.flash_action("📋 효과 복사")
            event.accept(); return
        if k == Qt.Key_V and (m & Qt.ControlModifier):
            if self._effect_clipboard is not None and self.is_edit_mode_on():
                self._paste_effect_at_cursor()
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
        """슬라이더 드래그/클릭 또는 트림 레인 시크 — segment 시간축에서 시크.

        2026-05-14 진단: 사용자가 줌이 있는 위치로 재생바를 옮기니 어플이 멈췄다는 보고.
        seek_combined_ms 호출이 >100ms 면 app.log 에 경고. event loop 막힘 진단.
        """
        import time
        import logging
        self._reset_frame_step_accum()
        _t0 = time.perf_counter()
        self._segment_ctrl.seek_combined_ms(int(ms))
        _dt_ms = (time.perf_counter() - _t0) * 1000
        if _dt_ms > 100:
            sc = self._edit_controller.sidecar()
            n_zoom = sum(1 for e in sc.effects
                         if e.type == "zoom" and e.in_ms <= int(ms) < e.out_ms)
            n_speed = sum(1 for e in sc.effects
                          if e.type == "speed" and e.in_ms <= int(ms) < e.out_ms)
            logging.warning(
                "video_tab: SLOW seek %.1fms ms=%d (zoom=%d speed=%d)",
                _dt_ms, int(ms), n_zoom, n_speed,
            )

    def _ensure_player_loaded(self) -> None:
        """탭이 보일 때 player.load + thumbnail + audio_enabled 적용.

        2026-05-22 (Phase 51): 라이브러리 "이것저것 클릭" 누적 회귀 fix. __init__ 에서
        load 안 하고 여기서 lazy 로드. release_player 후 다시 호출되면 reload + seek 복원.

        반복 호출 안전 — _media_loaded 플래그로 중복 차단.
        """
        if self._media_loaded:
            return
        self.player.load(self._source_path)
        if self._thumbnail_pending is not None:
            self.player.set_thumbnail(self._thumbnail_pending)
        self.controls.set_audio_enabled(self.player.has_audio())
        self._refresh_preview_mute()
        # release 후 reload 라면 마지막 position 으로 복원 — UX 연속성.
        # setSource() 는 비동기 — duration 이 처음 보고될 때 (metadata 로드 완료)
        # 한 번만 seek (즉시 seek 은 duration=0 clamp 로 silent fail).
        if self._saved_position_ms > 0:
            self._schedule_pending_seek(self._saved_position_ms)
        self._media_loaded = True

    def _schedule_pending_seek(self, target_ms: int) -> None:
        """release → reload 사이 보존한 position 으로 metadata 로드 후 1회 seek.

        QMediaPlayer.setSource 는 비동기 — duration_ms() 가 처음 >0 으로 보고될 때까지
        seek_ms 가 clamp 0 으로 silent fail. duration_changed one-shot 으로 적용.
        """
        pending = {"applied": False, "target": int(target_ms)}

        def _apply(dur_ms: int) -> None:
            if pending["applied"] or int(dur_ms) <= 0:
                return
            pending["applied"] = True
            try:
                self.player.seek_ms(pending["target"])
            except (AttributeError, RuntimeError):
                # 위젯 destroyed / API 변경 — 무시 (다음 사용자 seek 으로 자연 복원).
                pass
            # one-shot — disconnect.
            try:
                self.player.duration_changed.disconnect(_apply)
            except (TypeError, RuntimeError):
                pass

        self.player.duration_changed.connect(_apply)

    def _release_player(self) -> None:
        """탭이 비활성화될 때 디코더 해제 + 현재 position 보존.

        Windows MF QMediaPlayer 가 비활성 상태에서도 디코더 reservation + 메모리 점유.
        라이브러리 N번 클릭 시 누적 회귀의 핵심 원인. setSource(QUrl()) 로 즉시 해제 →
        다음 showEvent 에서 reload (~200ms) + seek 복원.
        """
        if not self._media_loaded:
            return
        try:
            self._saved_position_ms = int(self.player.position_ms())
        except (AttributeError, RuntimeError):
            self._saved_position_ms = 0
        try:
            self.player.release_file_handles()
        except (AttributeError, RuntimeError):
            pass
        self._media_loaded = False

    def release_player_for_file_op(self) -> None:
        """디스크 파일 작업(rename 등) 전 player 파일 핸들을 해제 + position 보존.

        Windows WMF/QMovie 가 잡고 있는 핸들 때문에 열린 영상은 rename/삭제가
        WinError 32 로 실패. _release_player 와 동일하나 외부(MainWindow) 호출용 공개 API.
        해제 후 _media_loaded=False 가 되어 다음 _ensure_player_loaded 가 재로드한다.
        """
        self._release_player()

    def apply_renamed_source(self, old_path: Path, new_path: Path) -> None:
        """디스크 rename 완료 후 호출 — in-memory 소스 경로 갱신 + (보이는 탭이면) 재로드.

        호출자(MainWindow)가 release_player_for_file_op → 디스크 rename 까지 끝낸 뒤 호출.
        실패해 원복하는 경우 old_path == new_path 로 호출하면 마이그레이션은 no-op 이고
        원본을 그대로 재로드한다.
        """
        self._source_path = Path(new_path)
        try:
            self._edit_controller.migrate_source_path(old_path, new_path)
        except (AttributeError, RuntimeError):
            pass
        if self.isVisible():
            self._ensure_player_loaded()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt signature
        """탭이 보일 때 player lazy 로드 + thumbnail filmstrip 디스패치.

        2026-05-14: 여러 탭 동시 열기 시 비가시 탭이 ffmpeg storm 을 일으켜 가시 탭의
        프리뷰 로딩까지 지연되던 회귀. QTabWidget 은 보이는 탭만 showEvent 발화.

        2026-05-22: lazy player.load + release 패턴 추가 — 비활성 탭의 디코더 해제.
        """
        super().showEvent(event)
        # 매 showEvent 마다 lazy 로드 시도 (release 후 재진입 포함).
        self._ensure_player_loaded()
        if not self._initial_thumbs_requested:
            self._initial_thumbs_requested = True
            self._request_all_thumbnails(self._edit_controller.sidecar())

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt signature
        """탭이 가려질 때 디코더 해제 — 비활성 탭의 메모리/MF 디코더 점유 회피.

        QTabWidget 의 다른 탭으로 전환 / 윈도우 minimize 시 발화. 같은 탭 다시 보면
        showEvent 가 _ensure_player_loaded 로 재로드 (~200ms + saved_position 복원).
        """
        super().hideEvent(event)
        self._release_player()

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
        self._manual_muted = not self._manual_muted
        self.controls.set_muted(self._manual_muted)
        self._refresh_preview_mute()

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

        # 복귀 시 원래 위치 보존을 위해 *modify 전* 에 부모 layout 안에서의 인덱스를
        # 캡처. 2026-05-12 의 QSplitter 도입 이후 위젯들은 self.layout() (outer
        # QVBoxLayout) 의 직접 자식이 아니라 _preview_container 안 (player/controls)
        # + splitter 안 (timeline) 에 있다. 회귀: self.layout().indexOf 가 모두 -1
        # 반환 → 복귀 시 outer layout 끝에 append 되어 splitter 가 비고 playbar 가
        # 사라지는 보고 ("영상 편집 갔다가 편집 끝니까 플레이바 사라짐").
        preview_layout = self._preview_container.layout()
        self._fs_player_index = preview_layout.indexOf(self.player)
        self._fs_ctrl_index = preview_layout.indexOf(self.controls)
        self._fs_timeline_index = self._main_splitter.indexOf(self.timeline)

        # 새 top-level 창. holder 엔 빈 QVBoxLayout 을 둔다 — 편집 모드에선 여기에
        # _main_splitter 를 통째로 넣어 풀스크린 전체를 차지하게 하고(일반 모드와 동일
        # 한 리사이즈 핸들·레인 배치), 재생 모드에선 비워두고 player/controls/timeline
        # 을 floating(setGeometry) overlay 로 띄운다. 마우스 트래킹은 위젯별 대신
        # __init__ 의 QApplication 글로벌 eventFilter 가 처리.
        holder = QWidget()
        holder.setWindowTitle("KStudio - 풀스크린")
        holder.setStyleSheet("background-color: black;")
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(0)
        self._fs_holder_layout = holder_layout

        # 자동 숨김 타이머 (재생 모드 floating overlay 에서만 사용 — 편집 모드는 비활성)
        hide_timer = QTimer(holder)
        hide_timer.setSingleShot(True)
        hide_timer.setInterval(_FS_HIDE_DELAY_MS)
        hide_timer.timeout.connect(lambda: self._fs_maybe_hide_controls())
        self._fs_hide_timer = hide_timer

        def _on_resize(ev):
            # 편집(splitter) 모드면 holder 의 layout 이 splitter 크기를 잡으므로 손대지
            # 않는다. 재생(floating) 모드에서만 player 를 꽉 채우고 바를 하단 재배치.
            if not self._fs_edit_layout:
                self.player.setGeometry(0, 0, holder.width(), holder.height())
                self._fs_reposition_floating()
        holder.resizeEvent = _on_resize  # type: ignore[assignment]

        # 닫힐 때(Esc 등) 복귀 처리 — _fs_restore 가 현재 하위 레이아웃과 무관하게 복원.
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
            self._fs_restore()
            original_closeEvent(ev)
        holder.closeEvent = _close   # type: ignore[assignment]

        self._fullscreen_holder = holder
        self._fs_edit_layout = False
        # 진입 시점의 편집 모드에 맞는 하위 레이아웃 구성.
        self._fs_apply_sublayout(self.is_edit_mode_on())
        holder.showFullScreen()
        # showFullScreen 직후 정확한 크기로 재배치 (floating 모드 한정).
        if not self._fs_edit_layout:
            self.player.setGeometry(0, 0, holder.width(), holder.height())
            self._fs_reposition_floating()
            if self.player.is_playing():
                hide_timer.start()

    # ---------- 풀스크린 하위 레이아웃 전환 (재생 overlay ↔ 편집 splitter) ----------
    def _fs_apply_sublayout(self, edit_on: bool) -> None:
        """풀스크린에서 편집 모드에 맞는 하위 레이아웃을 적용한다.

        편집 ON: 일반 모드와 동일한 _main_splitter 를 holder 전체에 — 위/아래 핸들
        드래그로 영역 조절 가능, 자동 숨김 비활성(편집 공간 항상 표시).
        편집 OFF: player 가 화면을 채우고 controls/timeline 은 floating overlay.
        """
        holder = self._fullscreen_holder
        if holder is None:
            return
        if edit_on:
            if self._fs_hide_timer is not None:
                self._fs_hide_timer.stop()
            self._fs_reassemble_splitter()                     # floating 였다면 재조립
            self._fs_holder_layout.addWidget(self._main_splitter)  # self→holder (자식 동반)
            self._fs_edit_layout = True
            self._main_splitter.show()
            self.player.show()
            self.controls.show()
            self.timeline.show()
            self._apply_timeline_layout(True)                  # 핸들 비율 + 높이 제한 해제
        else:
            self._fs_edit_layout = False
            self._apply_timeline_layout(False)                 # 시크 바 한 줄로 묶음
            self._fs_detach_to_floating()
            if self.player.is_playing() and self._fs_hide_timer is not None:
                self._fs_hide_timer.start()

    def _fs_reposition_floating(self) -> None:
        """재생(floating) 모드 — controls/timeline 을 화면 하단에 겹쳐 배치."""
        holder = self._fullscreen_holder
        if holder is None:
            return
        ctrl_h = self.controls.sizeHint().height()
        tl_h = self.timeline.sizeHint().height()
        self.controls.setGeometry(0, holder.height() - ctrl_h, holder.width(), ctrl_h)
        self.controls.raise_()
        # timeline 은 controls 바로 위에.
        self.timeline.setGeometry(
            0, holder.height() - ctrl_h - tl_h, holder.width(), tl_h,
        )
        self.timeline.raise_()

    def _fs_detach_to_floating(self) -> None:
        """player/controls/timeline 을 splitter 에서 빼 holder 직속 floating 으로.

        편집→재생 전환 또는 재생 모드 진입 시 호출. 빈 splitter 는 복귀 대비해
        self 의 outer layout 으로 도로 park.
        """
        holder = self._fullscreen_holder
        if holder is None:
            return
        self._fs_holder_layout.removeWidget(self._main_splitter)
        self.player.setParent(holder)
        self.player.show()
        self.player.setGeometry(0, 0, max(1, holder.width()), max(1, holder.height()))
        self.controls.setParent(holder)
        self.controls.show()
        self.timeline.setParent(holder)
        self.timeline.show()
        if self._main_splitter.parent() is not self:
            self.layout().addWidget(self._main_splitter)
        self._fs_reposition_floating()

    def _fs_reassemble_splitter(self) -> None:
        """floating 상태였던 player/controls/timeline 을 splitter 구조로 되돌린다.

        이미 splitter 안에 있으면 각 검사가 False 라 no-op. *_index 는 진입 전 캡처값.
        """
        preview_layout = self._preview_container.layout()
        if self.player.parent() is not self._preview_container:
            preview_layout.insertWidget(self._fs_player_index, self.player, stretch=1)
        if self.controls.parent() is not self._preview_container:
            preview_layout.insertWidget(self._fs_ctrl_index, self.controls)
        if self.timeline.parent() is not self._main_splitter:
            self._main_splitter.insertWidget(self._fs_timeline_index, self.timeline)

    def _fs_restore(self) -> None:
        """풀스크린 종료 — 하위 레이아웃(overlay/splitter)과 무관하게 원위치 복원.

        멱등 — closeEvent 가 한 번만 실행되도록 holder 가드.
        """
        if self._fullscreen_holder is None:
            return
        self._fullscreen_holder = None
        self._fs_hide_timer = None
        self._fs_edit_layout = False
        # 위젯들을 splitter 구조로 복원하고 splitter 를 self 의 outer layout 으로.
        self._fs_reassemble_splitter()
        if self._main_splitter.parent() is not self:
            self.layout().addWidget(self._main_splitter)
        # 현재 편집 모드에 맞게 타임라인 레이아웃 재적용 (단일 funnel).
        self._apply_timeline_layout(self.is_edit_mode_on())
        self.player.show()
        self.controls.show()
        self.player.setFocus()

    # ---------- 풀스크린 컨트롤 오버레이 ----------
    def eventFilter(self, obj, ev) -> bool:  # type: ignore[override]
        """QApplication 전역 필터 (영구 설치).

        - MouseMove: 풀스크린일 때만 컨트롤 표시/숨김 결정.
        - KeyPress: ←/→ 를 활성 영상 탭의 seek 으로 라우팅 — 포커스가 컨트롤·타임라인·
          풀스크린 holder 안일 때. VideoTab.keyPressEvent 가 VideoTab 직접 포커스에만
          발화하던 한계(편집 모드/풀스크린에서 방향키 미작동) 보완.
        다른 이벤트는 모두 그대로 통과.
        """
        et = ev.type()
        if et == QEvent.MouseMove:
            if self._fullscreen_holder is not None:
                self._fs_handle_global_mouse_move()
        elif et == QEvent.KeyPress and self._route_seek_key(obj, ev):
            return True
        return super().eventFilter(obj, ev)

    def _route_seek_key(self, obj, ev) -> bool:
        """←/→ 를 이 영상 탭의 seek 으로 라우팅. 처리했으면 True(소비).

        판정 기준은 이벤트 수신 대상(obj = 포커스 위젯) — 키는 포커스 위젯으로 배달되므로
        focusWidget() 전역 조회보다 정확하고 헤드리스에서도 안정적이다. 포커스가
        (a) 이 VideoTab subtree(또는 탭 자신) 또는 (b) 풀스크린 holder 안일 때만 작동 —
        다른 탭·채팅·라이브러리·인스펙터엔 간섭하지 않는다. 텍스트·숫자 입력·목록 위젯엔
        방향키를 넘겨 커서/선택 이동을 보호한다. keyPressEvent 가 modifier(Shift/Ctrl)에
        따라 skip 단위를 정하고 accept 한다.
        """
        if ev.key() not in (Qt.Key_Left, Qt.Key_Right):
            return False
        from PySide6.QtWidgets import (
            QAbstractItemView, QAbstractSpinBox, QLineEdit, QPlainTextEdit, QTextEdit,
            QWidget,
        )
        # 위젯 단위 배달만 처리 (QWindow 등 비위젯 수신은 위젯 배달에서 다시 잡힘).
        target = obj if isinstance(obj, QWidget) else None
        if target is None:
            return False
        if isinstance(
            target,
            (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QAbstractItemView),
        ):
            return False
        if self._fullscreen_holder is not None:
            in_context = True   # 풀스크린 — 위 입력 위젯 외엔 항상 seek
        else:
            in_context = target is self or self.isAncestorOf(target)
        if not in_context:
            return False
        self.keyPressEvent(ev)
        return ev.isAccepted()

    def _fs_handle_global_mouse_move(self) -> None:
        holder = self._fullscreen_holder
        if holder is None:
            return
        # 편집(splitter) 모드에선 controls/timeline 이 splitter 자식(상시 표시)이라
        # 자동 숨김/표시 토글을 하면 안 된다 — overlay 모드에서만 동작.
        if self._fs_edit_layout:
            return
        # 글로벌 커서 → holder 로컬 좌표 변환. 다른 모니터/창 위로 마우스가 가도
        # 안전하게 무시.
        pos = holder.mapFromGlobal(QCursor.pos())
        if not (0 <= pos.x() < holder.width() and 0 <= pos.y() < holder.height()):
            return
        # 어떤 움직임이든 숨겨져 있던 바를 다시 보여줌 (YouTube/VLC 표준 — 하단으로
        # 내려가야만 보이던 이전 동작 대신 화면 어디서나 움직이면 복원).
        if self.controls.isHidden() or self.timeline.isHidden():
            self.controls.show()
            self.controls.raise_()
            self.timeline.show()
            self.timeline.raise_()
        if self._fs_hide_timer is None:
            return
        in_bottom_band = pos.y() >= holder.height() - _FS_BOTTOM_BAND_PX
        if in_bottom_band:
            # 컨트롤 위에 마우스가 있으면 조작 중 — 숨김 보류 (계속 표시).
            self._fs_hide_timer.stop()
        elif self.player.is_playing():
            # 그 외 영역 — 재생 중이면 마지막 움직임 후 3초 뒤 숨김 (매 움직임마다 리셋).
            self._fs_hide_timer.start()

    def _fs_maybe_hide_controls(self) -> None:
        if self._fullscreen_holder is None:
            return
        if self._fs_edit_layout:
            return  # 편집 모드 — 바를 숨기지 않음
        if not self.player.is_playing():
            return  # 일시정지 중엔 숨기지 않음
        self.controls.hide()
        self.timeline.hide()
