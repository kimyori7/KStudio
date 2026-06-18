"""AudioTab — mp3/오디오 파일 전용 자르기 탭 (전용, 영상 탭과 분리).

구성: PlayerWidget(오디오 재생) + AudioWaveformEditor(파형 위 트림/컷 편집) + 슬림
트랜스포트(재생/일시정지·시간·배속·출력). brain 은 영상 탭과 동일한 EditController/
Sidecar — 오디오는 video_track 의 단일 풀 segment(src_in=0, src_out=0) 로 들고, 트림·
중간컷을 모두 원본 시간축의 CutEffect 로 표현한다(앞 트림=cut[0,trim_in], 뒤 트림=
cut[trim_out,dur], 중간컷=그대로). 이래야 컷 ms 좌표계·clamp·내보내기가 한 좌표계로
일치한다(트림을 src_in 으로 하면 중간컷이 clamp 에 사라지는 버그 — _apply_edits 주석 참조).
내보내기는 기존 음성 export 경로(_on_export_audio)를 탄다.
"""
from __future__ import annotations
import copy
from dataclasses import replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..core.settings import PlayerSettings
from ..effects import default_sidecar_dir
from ..effects.types.cut import CutEffect
from ..effects.sidecar import ensure_default_track
from .icons import load_icon
from .audio.audio_waveform_editor import AudioWaveformEditor
from .audio import audio_edit_geometry as _geom
from .video.player_widget import PlayerWidget
from .video.edit_controller import EditController
from ..encode.audio_export import compute_audio_keep_intervals

_ICON_PX = 18
_SPEEDS = [("0.5×", 0.5), ("1.0×", 1.0), ("1.5×", 1.5), ("2.0×", 2.0)]


def _fmt_ms(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


class AudioTab(QWidget):
    """단일 오디오 파일 자르기 탭."""

    export_requested = Signal()     # 출력 버튼 → main_window._on_export_audio

    def __init__(self, *, path: Path, player_settings: PlayerSettings,
                 sidecar_dir: "Path | None" = None,
                 sidecar_path: "Path | None" = None) -> None:
        super().__init__()
        self._source_path = Path(path)
        self._settings = player_settings
        self._media_loaded = False
        self._playing = False
        # 편집 상태(권위). 트림/컷을 모두 "원본 시간축의 잘라낼 구간(CutEffect)" 으로
        # 표현한다 — segment 는 항상 풀(src_in=0, src_out=0). 앞 트림=cut[0,trim_in],
        # 뒤 트림=cut[trim_out,dur], 중간컷=그대로. 이래야 컷의 ms 좌표계(combined)와
        # 내보내기(compute_audio_keep_intervals)·clamp 가 한 좌표계로 일치한다.
        self._trim_in = 0
        self._trim_out = 0      # 0 = 끝까지
        self._mid_cuts: list[tuple[int, int]] = []
        self._dur = 0
        self._keep: list[tuple[int, int]] = []   # 재생 시 건너뛸 구간 계산용(이어붙은 재생)

        sc_dir = Path(sidecar_dir) if sidecar_dir else default_sidecar_dir()
        self._edit_controller = EditController(
            self._source_path, sc_dir,
            sidecar_path=Path(sidecar_path) if sidecar_path else None,
        )
        # 오디오 1개를 단일 segment 트랙으로 — duration 은 player 로드 후 채움.
        self._edit_controller.ensure_default_track(source_duration_ms=0)

        self.player = PlayerWidget()
        self.player.hide()   # 오디오엔 영상 프레임 없음 — 파형이 미리보기. 소리만 재생.
        self.editor = AudioWaveformEditor()
        self.editor.set_filename(self._source_path.name)

        self._build_ui()
        self._wire()

        # 파형 요청은 init 에서 (Phase 85.3 교훈: 변경 시그널에만 걸면 첫 진입에서 안 뜸).
        from ..services.waveform_service import WaveformService
        from ..core.ffmpeg_check import find_ffmpeg
        _ff = find_ffmpeg()
        self._waveform_service = WaveformService(
            ffmpeg_path=str(_ff) if _ff else "ffmpeg", parent=self)
        self._waveform_service.waveform_ready.connect(self._on_waveform_ready)
        self._waveform_service.request(str(self._source_path))

        self._sync_editor_from_sidecar(self._edit_controller.sidecar())

    # ---------- UI ----------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        root.addWidget(self.editor, stretch=1)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(36, 32)
        self.play_btn.setIcon(load_icon("play", size=_ICON_PX))
        self.play_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        bar.addWidget(self.play_btn)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(110)
        bar.addWidget(self.time_label)
        bar.addStretch(1)

        self.speed_combo = QComboBox()
        for label, _ in _SPEEDS:
            self.speed_combo.addItem(label)
        self.speed_combo.setCurrentText("1.0×")
        bar.addWidget(self.speed_combo)

        self.export_btn = QPushButton(" 출력")
        self.export_btn.setIcon(load_icon("upload", size=_ICON_PX))
        self.export_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.export_btn.setFixedHeight(32)
        bar.addWidget(self.export_btn)
        root.addLayout(bar)

    def _wire(self) -> None:
        self.editor.trim_changed.connect(self._on_trim_changed)
        self.editor.cuts_changed.connect(self._on_cuts_changed)
        self.editor.seek_request.connect(self.player.seek_ms)

        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.playing_changed.connect(self._on_playing_changed)

        self.play_btn.clicked.connect(self._toggle_play)
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)
        self.export_btn.clicked.connect(self.export_requested.emit)
        self._edit_controller.sidecar_replaced.connect(self._sync_editor_from_sidecar)
        # 스페이스바(재생)·Ctrl+Z/Y(실행취소)는 **자체 QShortcut 을 만들지 않는다** —
        # MainWindow 에 이미 전역 Space(ApplicationShortcut)·메뉴 Ctrl+Z(WindowShortcut)가
        # 있어 탭에 또 만들면 "Ambiguous shortcut"으로 둘 다 안 먹는다(사용자 보고). 대신
        # MainWindow._on_global_space / _on_undo / _on_redo 가 현재 탭이 AudioTab 이면
        # 여기 _toggle_play/_undo/_redo 로 라우팅한다.

    # ---------- lazy load ----------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._media_loaded:
            self._media_loaded = True
            try:
                self.player.load(self._source_path)
            except (RuntimeError, OSError):
                pass

    # ---------- player → editor ----------
    def _on_position(self, ms: int) -> None:
        self.editor.set_position_ms(ms)
        self.time_label.setText(f"{_fmt_ms(ms)} / {_fmt_ms(self.player.duration_ms())}")
        # 재생 중에는 잘라낸 구간을 건너뛴다 — 미리듣기가 '이어붙은' 결과(=내보내기)와 같게.
        # 일시정지/수동 seek 중에는 건너뛰지 않는다(사용자가 컷 구간을 봐도 됨).
        if not self._playing or not self._keep:
            return
        target = _geom.playback_skip_target(int(ms), self._keep)
        if target is None:
            return
        if target < 0:                      # 마지막 keep 끝 → 정지 + 처음으로.
            self.player.pause()
            self.player.seek_ms(self._keep[0][0])
        else:                               # 제거된 구간 → 다음 keep 시작으로 점프.
            self.player.seek_ms(target)

    def _recompute_keep(self) -> None:
        """사이드카(트림+컷) → 재생 시 살아있는 구간 목록. 실패하면 빈 목록(=건너뛰기 없음)."""
        try:
            _src, keep = compute_audio_keep_intervals(self._edit_controller.sidecar())
            self._keep = [(int(s), int(e)) for s, e in keep]
        except (ValueError, NotImplementedError):
            self._keep = []

    def _on_duration(self, ms: int) -> None:
        if ms <= 0:
            return
        self._dur = int(ms)
        self.editor.set_total_ms(ms)
        self.time_label.setText(f"{_fmt_ms(self.player.position_ms())} / {_fmt_ms(ms)}")
        # segment 의 src_duration 이 비어 있으면 채움(내보내기 keep 계산에 필요). 사용자
        # 액션 아니므로 history 안 건드리고 직접 mutate.
        sc = self._edit_controller.sidecar()
        if sc.video_track and sc.video_track[0].src_duration_ms <= 0:
            sc.video_track[0] = replace(sc.video_track[0], src_duration_ms=int(ms))
        self._recompute_keep()   # 길이 확정 후 keep 구간(끝 경계) 계산 가능

    def _on_playing_changed(self, playing: bool) -> None:
        self._playing = bool(playing)
        self.play_btn.setIcon(load_icon("pause" if playing else "play", size=_ICON_PX))

    def _on_waveform_ready(self, src: str, peaks: list) -> None:
        if str(src) == str(self._source_path):
            self.editor.set_peaks(peaks)

    # ---------- editor → sidecar ----------
    def _on_trim_changed(self, in_ms: int, out_ms: int) -> None:
        self._trim_in = max(0, int(in_ms))
        self._trim_out = max(0, int(out_ms))
        self._apply_edits()

    def _on_cuts_changed(self, cuts: list) -> None:
        self._mid_cuts = [(int(s), int(e)) for (s, e) in cuts]
        self._apply_edits()

    def _track_duration_ms(self, sc) -> int:
        if sc.video_track and sc.video_track[0].src_duration_ms > 0:
            return int(sc.video_track[0].src_duration_ms)
        return int(self._dur or 0)

    def _apply_edits(self) -> None:
        """현재 트림/중간컷을 풀 segment 위의 CutEffect 리스트로 사이드카에 반영.

        앞/뒤 트림을 경계 컷으로 바꿔, 컷 ms 좌표계(combined)·clamp·내보내기 keep 계산이
        모두 원본 시간축 한 좌표계로 일치하게 한다(트림을 src_in 으로 하면 좌표계가
        어긋나 중간컷이 clamp 에 잘려 사라진다 — 실파일 진단으로 확인된 버그)."""
        sc = self._edit_controller.sidecar()
        if not sc.video_track:
            return
        dur = self._track_duration_ms(sc)
        trim_out_eff = self._trim_out if self._trim_out > 0 else dur
        cuts: list[tuple[int, int]] = []
        if self._trim_in > 0:
            cuts.append((0, self._trim_in))
        if dur and trim_out_eff < dur:
            cuts.append((trim_out_eff, dur))
        cuts += self._mid_cuts
        new_sc = copy.deepcopy(sc)
        # segment 는 항상 풀 — 트림은 경계 컷으로 표현(src_duration 은 보존).
        new_sc.video_track[0] = replace(new_sc.video_track[0], src_in_ms=0, src_out_ms=0)
        new_sc.effects = [e for e in new_sc.effects if e.type != "cut"]
        new_sc.effects += [CutEffect(in_ms=int(s), out_ms=int(e), preview_skip=False)
                           for (s, e) in cuts if e > s]
        self._edit_controller.update_sidecar(new_sc)

    def _sync_editor_from_sidecar(self, sc) -> None:
        """사이드카의 컷들 → 트림(경계 컷)/중간컷으로 역산해 editor·내부 상태에 반영.

        라운드트립 안정(역산 결과가 _apply_edits 입력과 같음)이라 루프 없음."""
        dur = self._track_duration_ms(sc)
        cuts = sorted((int(e.in_ms), int(e.out_ms))
                      for e in sc.effects if e.type == "cut")
        trim_in, trim_out, middles = 0, 0, []
        for s, e in cuts:
            if s <= 0:
                trim_in = max(trim_in, e)        # 앞 경계 컷
            elif dur and e >= dur:
                trim_out = s if trim_out == 0 else min(trim_out, s)   # 뒤 경계 컷
            else:
                middles.append((s, e))
        self._trim_in, self._trim_out, self._mid_cuts = trim_in, trim_out, middles
        self.editor.set_trim(trim_in, trim_out)
        self.editor.set_cuts(middles)
        self._recompute_keep()   # 컷/트림 바뀌면 재생 건너뛰기 구간도 갱신

    # ---------- undo/redo ----------
    def _undo(self) -> None:
        self._edit_controller.undo()   # sidecar_replaced → editor 재동기화

    def _redo(self) -> None:
        self._edit_controller.redo()

    # ---------- transport ----------
    def _toggle_play(self) -> None:
        if self._playing:
            self.player.pause()
        else:
            self.player.play()

    def _on_speed_changed(self, label: str) -> None:
        for lbl, val in _SPEEDS:
            if lbl == label:
                self.player.set_playback_rate(val)
                return

    # ---------- 외부 인터페이스 (export 등) ----------
    def edit_controller(self) -> EditController:
        return self._edit_controller

    def source_path(self) -> str:
        return str(self._source_path)
