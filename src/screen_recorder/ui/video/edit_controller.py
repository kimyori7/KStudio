"""영상 탭의 편집 상태 보유자 — Sidecar + History + autosave + 편집 모드."""
from __future__ import annotations
import copy
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ...effects import (
    History, Sidecar, SidecarStore, Trim, compute_video_hash, overlaps_existing,
)


_AUTOSAVE_DEBOUNCE_MS = 500


class EditController(QObject):
    """한 영상 탭의 편집 상태.

    - Sidecar 로드/저장
    - History (undo/redo)
    - autosave (사이드카 변경 후 디바운스 저장)
    - 편집 모드 ON/OFF 상태

    UI 위젯은 보유하지 않는다 — VideoTab 이 시그널을 받아 lanes/인스펙터에 전달.
    """

    sidecar_replaced = Signal(object)        # Sidecar — 외부 변경 (undo/redo, 효과 추가) 후
    edit_mode_toggled = Signal(bool)         # ON/OFF
    autosave_failed = Signal(str)            # 에러 메시지

    def __init__(self, video_path: Path, sidecar_dir: Path) -> None:
        super().__init__()
        self._video_path = Path(video_path)
        self._store = SidecarStore(sidecar_dir)
        self._edit_mode_on = False

        loaded = self._store.load_for(self._video_path)
        if loaded is None:
            loaded = Sidecar(
                source_path=str(self._video_path),
                source_hash=compute_video_hash(self._video_path),
                trim=Trim(in_ms=0, out_ms=0),
            )
        self._sidecar: Sidecar = loaded
        self._history = History(initial=loaded)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(_AUTOSAVE_DEBOUNCE_MS)
        self._autosave_timer.timeout.connect(self._do_autosave)

    # ---------- public ----------
    def sidecar(self) -> Sidecar:
        return self._sidecar

    def is_edit_mode_on(self) -> bool:
        return self._edit_mode_on

    def set_edit_mode(self, on: bool) -> None:
        if self._edit_mode_on == on:
            return
        self._edit_mode_on = on
        self.edit_mode_toggled.emit(on)

    def update_sidecar(self, new_sidecar: Sidecar) -> None:
        """효과 추가/삭제/수정 후 호출. History push + autosave 트리거."""
        self._history.push(new_sidecar)
        self._sidecar = self._history.current()
        self.sidecar_replaced.emit(self._sidecar)
        self._autosave_timer.start()

    def ensure_default_track(self, source_duration_ms: int) -> None:
        """첫 로드 시 빈 video_track 에 source 1 segment 자동 채움.

        호출 후 사이드카 상태를 History 의 baseline 으로 다시 설정 — 사용자가
        Ctrl+Z 로 "빈 트랙" 까지 되돌리지 않도록 한다.

        시그널은 emit 하지 않음 — VideoTab init 흐름에서 timeline 이 아직 없을 수 있어
        호출자가 직접 timeline.set_sidecar() 로 초기 상태를 그린다.
        """
        from ...effects.sidecar import ensure_default_track as _impl
        had_track = bool(self._sidecar.video_track)
        _impl(self._sidecar, source_duration_ms=source_duration_ms)
        if not had_track and self._sidecar.video_track:
            # 새로 채웠으니 history baseline 만 갱신 (emit 안 함).
            self._history = History(initial=self._sidecar)

    def add_effect(self, effect) -> bool:
        """효과 추가 — 같은 type 의 시간 겹침 검사 후 push.

        반환값: 추가 성공이면 True, 겹쳐서 거부면 False.
        """
        if overlaps_existing(self._sidecar.effects, effect):
            return False
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.effects.append(effect)
        self.update_sidecar(new_sc)
        return True

    def update_effect(self, effect) -> bool:
        """기존 효과를 같은 id 로 교체. 없으면 no-op.

        교체 시 같은 type 의 다른 효과들과 시간이 겹치면 거부 (False) — 사이드카 변경 없이
        sidecar_replaced 만 다시 emit 해 UI 가 원본 위치로 resync 하도록 한다. 이는
        드래그 리사이즈로 다른 효과 위로 침범할 때 결합 시간축 빌드가 깨지는 것을 막기 위함.
        """
        for i, e in enumerate(self._sidecar.effects):
            if e.id == effect.id:
                others = [x for x in self._sidecar.effects if x.id != effect.id]
                if overlaps_existing(others, effect):
                    self.sidecar_replaced.emit(self._sidecar)
                    return False
                new_sc = copy.deepcopy(self._sidecar)
                new_sc.effects[i] = effect
                self.update_sidecar(new_sc)
                return True
        return False

    def remove_effect(self, effect_id: str) -> bool:
        """id 로 효과 삭제. 없으면 no-op."""
        new_effects = [e for e in self._sidecar.effects if e.id != effect_id]
        if len(new_effects) == len(self._sidecar.effects):
            return False
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.effects = new_effects
        self.update_sidecar(new_sc)
        return True

    def update_trim(self, in_ms: int, out_ms: int) -> None:
        """사이드카의 trim 을 갱신. History push + autosave 트리거.

        in_ms, out_ms 는 정규화된 값이어야 함 (in <= out). 둘 다 0 = 트림 없음.
        """
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.trim = Trim(in_ms=int(in_ms), out_ms=int(out_ms))
        self.update_sidecar(new_sc)

    # ---------- Stage B: video_track segment 단위 API ----------
    _MIN_SPLIT_MS = 100

    def split_segment(self, segment_id: str, at_local_ms: int) -> bool:
        """segment 를 at_local_ms (segment-local) 에서 둘로 쪼갠다.

        쪼개진 두 segment 모두 최소 100ms 폭 보장. 거부 시 False.
        """
        from dataclasses import replace
        from ...effects.segment import VideoSegment
        track = self._sidecar.video_track
        idx = next((i for i, s in enumerate(track) if s.id == segment_id), -1)
        if idx < 0:
            return False
        seg = track[idx]
        dur = seg.duration_ms
        if dur <= 0:
            return False
        if at_local_ms < self._MIN_SPLIT_MS or (dur - at_local_ms) < self._MIN_SPLIT_MS:
            return False
        # 첫째: 원본 in ~ in+at, 둘째: in+at ~ 원본 out (or duration).
        split_at_src = seg.src_in_ms + at_local_ms
        first_out = split_at_src
        second_in = split_at_src
        second_out = seg.src_out_ms if seg.src_out_ms > 0 else seg.src_duration_ms
        first = replace(seg, src_out_ms=first_out)
        second = VideoSegment(
            src=seg.src,
            src_in_ms=second_in,
            src_out_ms=second_out,
            src_duration_ms=seg.src_duration_ms,
            media_kind=seg.media_kind,
            image_duration_ms=seg.image_duration_ms,
            effects=[],   # 쪼갤 때 효과는 첫째에만 보존 (간단화 — Stage C 에서 정교화).
        )
        # 첫째에는 원본 effects 유지.
        first = replace(first, effects=list(seg.effects))
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.video_track[idx] = first
        new_sc.video_track.insert(idx + 1, second)
        self.update_sidecar(new_sc)
        return True

    def insert_segment(self, at_idx: int, segment) -> bool:
        """segment 를 at_idx 위치에 삽입. idx 는 [0, len(track)] 으로 clamp."""
        track_len = len(self._sidecar.video_track)
        idx = max(0, min(track_len, int(at_idx)))
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.video_track.insert(idx, segment)
        self.update_sidecar(new_sc)
        return True

    def delete_segment(self, segment_id: str) -> bool:
        """id 로 segment 제거. 못 찾으면 False."""
        track = self._sidecar.video_track
        if not any(s.id == segment_id for s in track):
            return False
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.video_track = [s for s in new_sc.video_track if s.id != segment_id]
        self.update_sidecar(new_sc)
        return True

    def move_segment(self, from_idx: int, to_idx: int) -> bool:
        """from_idx 의 segment 를 to_idx 위치로 이동. 인덱스 범위 외면 False."""
        track = self._sidecar.video_track
        n = len(track)
        if not (0 <= from_idx < n) or not (0 <= to_idx < n):
            return False
        if from_idx == to_idx:
            return True
        new_sc = copy.deepcopy(self._sidecar)
        seg = new_sc.video_track.pop(from_idx)
        new_sc.video_track.insert(to_idx, seg)
        self.update_sidecar(new_sc)
        return True

    def update_segment(self, segment) -> bool:
        """기존 segment 를 같은 id 로 교체. 못 찾으면 False."""
        track = self._sidecar.video_track
        idx = next((i for i, s in enumerate(track) if s.id == segment.id), -1)
        if idx < 0:
            return False
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.video_track[idx] = segment
        self.update_sidecar(new_sc)
        return True

    def undo(self) -> bool:
        if not self._history.can_undo():
            return False
        self._sidecar = self._history.undo()
        self.sidecar_replaced.emit(self._sidecar)
        self._autosave_timer.start()
        return True

    def redo(self) -> bool:
        if not self._history.can_redo():
            return False
        self._sidecar = self._history.redo()
        self.sidecar_replaced.emit(self._sidecar)
        self._autosave_timer.start()
        return True

    # ---------- internal ----------
    def _do_autosave(self) -> None:
        try:
            self._store.save_for(self._video_path, self._sidecar)
        except OSError as e:
            self.autosave_failed.emit(str(e))
