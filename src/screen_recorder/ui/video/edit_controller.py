"""영상 탭의 편집 상태 보유자 — Sidecar + History + autosave + 편집 모드."""
from __future__ import annotations
import copy
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ...effects import (
    History, Sidecar, SidecarStore, Trim, compute_video_hash, overlaps_existing,
)
from .clip_placement import MoveOutcome, Placement


_log = logging.getLogger(__name__)
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

    def __init__(self, video_path: Path, sidecar_dir: Path,
                 sidecar_path: Optional[Path] = None,
                 save_path: Optional[Path] = None) -> None:
        """sidecar_path 가 명시되면 그 파일 직접 load (hash 매칭 우회) — 사용자가
        편집본 파일을 파일 열기로 직접 열었을 때. None 이면 hash 매칭으로 자동 검색.

        save_path 가 명시되면 **모든 저장이 그 파일로** 간다 (hash 기반 파일명 우회).
        소스 영상 파일이 없는 빈 프로젝트("새 영상")용 — 사이드카를 영상 hash 로 찾을
        수 없으므로 프로젝트 파일 자체가 유일한 정체성이 된다.
        """
        super().__init__()
        from ...effects.sidecar import load as _load_sidecar
        self._video_path = Path(video_path)
        self._store = SidecarStore(sidecar_dir)
        self._save_path = Path(save_path) if save_path is not None else None
        self._edit_mode_on = False

        # hash 1회 계산 — 이전엔 진단·load_for·MISS fallback 에서 동일 hash 가 3번
        # 계산되어 메인 스레드 1MB read*3 + SHA1*3 으로 탭 오픈 지연의 큰 원인.
        try:
            h = compute_video_hash(self._video_path)
            _log.info(
                "sidecar load video=%s hash=%s dir=%s explicit=%s",
                self._video_path.name, h[:12] + "...", sidecar_dir,
                sidecar_path.name if sidecar_path else "(none)",
            )
        except OSError:
            h = ""
        loaded: Optional[Sidecar] = None
        # 1) 명시 사이드카 path 가 있으면 hash 매칭 우회.
        if sidecar_path is not None:
            try:
                loaded = _load_sidecar(Path(sidecar_path))
                _log.info("sidecar load explicit HIT — file=%s effects=%d segments=%d",
                          sidecar_path.name, len(loaded.effects), len(loaded.video_track))
            except Exception as e:
                _log.warning("sidecar load explicit FAIL — file=%s err=%s",
                             sidecar_path, e)
        # 2) 명시 없거나 실패 시 hash 매칭 — 이미 계산한 h 를 hint 로 전달.
        #    hash 가 비어 있으면(파일이 없거나 못 읽음) 매칭 자체가 불가능하고,
        #    load_for 는 hint 없이 호출되면 다시 파일을 열어 FileNotFoundError 를
        #    던진다 — 빈 프로젝트 / 사라진 파일에서 탭 오픈이 통째로 깨지던 경로.
        if loaded is None and h:
            loaded = self._store.load_for(self._video_path, hash_hint=h)
            if loaded is None:
                _log.info(
                    "sidecar load_for: MISS (새 사이드카로 시작) — dir 안 후보들=%s",
                    [p.name for p in self._store._candidates_for_hash(h)],
                )
            else:
                _log.info(
                    "sidecar load_for: HIT — effects=%d, segments=%d",
                    len(loaded.effects), len(loaded.video_track),
                )
        if loaded is None:
            # 새 사이드카로 시작. 빈 프로젝트(save_path 지정) 는 소스 영상이 없으므로
            # source_path 를 비워 둔다 — export 가 "트랙이 권위" 를 판별하는 근거이자,
            # 사이드카가 존재하지 않는 파일을 가리키지 않게 하는 장치.
            loaded = Sidecar(
                source_path="" if self._save_path is not None else str(self._video_path),
                source_hash=h,
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

    def sidecar_dir(self) -> Path:
        """사이드카 파일이 저장되는 디렉터리 경로."""
        return self._store.root

    def migrate_source_path(self, old_path: Path, new_path: Path) -> None:
        """디스크 rename 후 in-memory 소스 경로를 즉시 갱신 (재로드 없이).

        편집 탭이 열린 채 라이브러리에서 영상 이름을 바꾸면, hash 매칭이라 사이드카
        자체는 따라오지만 메모리상의 _video_path / sidecar.source_path / segment.src 는
        여전히 옛 경로를 가리켜 이후 export/trim 이 깨진다. SidecarStore.load_for 가
        파일 이동 시 하던 마이그레이션과 동일 로직을 현재 사이드카와 undo/redo 히스토리
        전체에 적용한다.
        """
        from ...effects.sidecar import migrate_sidecar_source
        old_s = str(old_path)
        new_s = str(new_path)
        self._video_path = Path(new_path)
        migrate_sidecar_source(self._sidecar, old_s, new_s)
        self._history.migrate(lambda sc: migrate_sidecar_source(sc, old_s, new_s))

    def is_edit_mode_on(self) -> bool:
        return self._edit_mode_on

    def set_edit_mode(self, on: bool) -> None:
        if self._edit_mode_on == on:
            return
        self._edit_mode_on = on
        self.edit_mode_toggled.emit(on)

    def update_sidecar(self, new_sidecar: Sidecar) -> None:
        """효과 추가/삭제/수정 후 호출. History push + autosave 트리거.

        track 변경 (cut/trim/segment delete 등) 으로 combined duration 이 줄어들면
        끝점을 넘는 effect 가 trailing zone 에 남아 효과 라인이 어긋남 + export 시
        엉뚱한 시각에 표시. update_sidecar 가 단일 funnel 이라 여기서 한 번 clamp 하면
        모든 진입점이 자동 처리. clamp 는 idempotent — track 안 변한 경우 no-op.
        """
        from ...effects.sidecar import clamp_effects_to_track
        new_sidecar.effects = clamp_effects_to_track(new_sidecar)
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
        """효과 추가. 시간 겹침 시 다음 빈 track_idx (sub-lane) 자동 할당 (Phase 21).

        반환값: 항상 True — track_idx 끝까지 다 차도 0..N 마지막 + 1 로 새 lane.
        같은 type 의 시간 겹침을 거부하지 않음 — 동시에 여러 caption/arrow 등 허용.
        """
        effect = self._assign_free_track_idx(self._sidecar.effects, effect)
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.effects.append(effect)
        self.update_sidecar(new_sc)
        return True

    def add_effects(self, effects) -> int:
        """효과 여러 개를 한 history entry 로 추가.

        자동편집처럼 수십 개 효과를 한 번에 추가하는 경로에서 Ctrl+Z 한 번으로
        전체를 되돌릴 수 있게 한다. 각 효과의 track_idx 자동 분리는 add_effect 와
        같은 규칙을 순차 적용한다.
        """
        if not effects:
            return 0
        new_sc = copy.deepcopy(self._sidecar)
        added = 0
        for effect in effects:
            placed = self._assign_free_track_idx(new_sc.effects, effect)
            new_sc.effects.append(placed)
            added += 1
        self.update_sidecar(new_sc)
        return added

    @staticmethod
    def _assign_free_track_idx(existing, effect):
        if overlaps_existing(existing, effect):
            from dataclasses import replace
            # 같은 type 의 track_idx 중 candidate.in_ms~out_ms 겹치지 않는 가장 작은 값.
            ti = 0
            while True:
                ti += 1
                trial = replace(effect, track_idx=ti)
                if not overlaps_existing(existing, trial):
                    effect = trial
                    break
        return effect

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

    # ---------- 2026-05-20: 효과 활성/비활성 토글 ----------
    def set_effects_enabled(self, enabled: bool) -> bool:
        """전체 효과 ON/OFF — Sidecar.effects_enabled 변경 + history + autosave.

        사용자가 메뉴에서 '효과 적용' 체크 토글했을 때 호출. False 면 preview / export
        모두 효과 무시 (active_effects() 가 빈 리스트 반환). 반환: 실제로 바뀌었으면
        True, no-op 이면 False.
        """
        if bool(self._sidecar.effects_enabled) == bool(enabled):
            return False
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.effects_enabled = bool(enabled)
        self.update_sidecar(new_sc)
        return True

    def set_audio_muted(self, muted: bool) -> bool:
        """오디오 음소거 ON/OFF — Sidecar.audio_muted 변경 + history + autosave.

        파형 레인의 🔇 토글에서 호출. True 면 미리보기 재생 무음 + 내보내기 무음.
        값이 바뀌면 True, no-op 이면 False (set_effects_enabled 와 동일 패턴).
        """
        if bool(self._sidecar.audio_muted) == bool(muted):
            return False
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.audio_muted = bool(muted)
        self.update_sidecar(new_sc)
        return True

    def set_row_enabled(self, effect_type: str, track_idx: int, enabled: bool) -> bool:
        """특정 lane row (effect_type + track_idx) 의 모든 효과의 enabled 일괄 변경.

        사용자가 lane 우클릭 메뉴 '이 라인 활성/비활성' 클릭했을 때. 같은 type + 같은
        track_idx 의 효과들을 한 번에 변경 — undo 1번으로 되돌릴 수 있도록 단일 history.
        반환: 실제로 바뀐 효과가 있었으면 True.
        """
        from dataclasses import replace
        new_effs = []
        changed = False
        for e in self._sidecar.effects:
            if (e.type == effect_type
                    and int(getattr(e, "track_idx", 0)) == int(track_idx)
                    and bool(getattr(e, "enabled", True)) != bool(enabled)):
                new_effs.append(replace(e, enabled=bool(enabled)))
                changed = True
            else:
                new_effs.append(e)
        if not changed:
            return False
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.effects = new_effs
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

        쪼개진 두 segment 모두 최소 100ms 폭 보장. 자르기는 갭 없이 인접 — 둘째의
        start_ms = 첫째의 end_ms.
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
        split_at_src = seg.src_in_ms + at_local_ms
        first_out = split_at_src
        second_in = split_at_src
        second_out = seg.src_out_ms if seg.src_out_ms > 0 else seg.src_duration_ms
        first = replace(seg, src_out_ms=first_out, effects=list(seg.effects))
        # 둘째의 트랙 시작 = 첫째의 끝 (자르기는 갭 없이 인접).
        second_start = seg.start_ms + at_local_ms
        second = VideoSegment(
            src=seg.src,
            src_in_ms=second_in,
            src_out_ms=second_out,
            src_duration_ms=seg.src_duration_ms,
            media_kind=seg.media_kind,
            image_duration_ms=seg.image_duration_ms,
            effects=[],   # 쪼갤 때 효과는 첫째에만 보존 (간단화 — Stage C 에서 정교화).
            start_ms=second_start,
        )
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.video_track[idx] = first
        new_sc.video_track.insert(idx + 1, second)
        self.update_sidecar(new_sc)
        return True

    def insert_segment(self, at_idx: int, segment) -> "MoveOutcome":
        """segment 를 at_idx 위치(track list 의 인덱스) 에 삽입.

        Gap 모델 변경: 트랙은 list 순서가 아니라 start_ms 가 위치를 결정한다.
        삽입 시 segment.start_ms 가 0 이면 "마지막 segment 끝에 이어 붙임" — 이전
        UI 의 packed 동작과 호환. 명시 start_ms 가 있으면 그 값 그대로 사용.

        자리 결정은 드래그 이동·붙여넣기와 같은 규칙(clip_placement) — 놓은 지점이
        가리키는 빈칸이 좁으면 그 자리에 넣고 뒤 클립들을 민다. "여기에 놓는다" 는
        같은 의도의 동작이 경로마다 다르게 움직이지 않도록 한 규칙으로 통일한다.

        반환: MoveOutcome — 배치된 start_ms + 밀린 클립 수/양. 여러 파일을 이어서 넣는
        호출자가 실제 배치 위치를 이어받아 다음 파일의 위치를 정할 수 있다.
        """
        from dataclasses import replace
        from .clip_placement import apply_push, plan_placement
        old_track = self._sidecar.video_track
        new_sc = copy.deepcopy(self._sidecar)
        track = new_sc.video_track
        # start_ms 결정.
        if segment.start_ms <= 0:
            plan = Placement(start_ms=self._track_end_ms(old_track))
        else:
            plan = plan_placement(old_track, segment.start_ms, segment.duration_ms)
        pushes = apply_push(old_track, plan)
        for i, moved_start in pushes:
            pushed = old_track[i]
            track[i] = replace(pushed, start_ms=int(moved_start))
        if pushes:
            ranges = [(old_track[i].start_ms,
                       old_track[i].start_ms + old_track[i].duration_ms)
                      for i, _ in pushes]
            for i, eff in enumerate(new_sc.effects):
                if any(lo <= eff.in_ms and eff.out_ms <= hi for lo, hi in ranges):
                    new_sc.effects[i] = replace(
                        eff,
                        in_ms=int(eff.in_ms + plan.push_delta_ms),
                        out_ms=int(eff.out_ms + plan.push_delta_ms),
                    )
        seg_to_insert = replace(segment, start_ms=int(plan.start_ms))
        idx = max(0, min(len(track), int(at_idx)))
        track.insert(idx, seg_to_insert)
        self.update_sidecar(new_sc)
        return MoveOutcome(moved=True, start_ms=int(plan.start_ms),
                           pushed_count=len(pushes),
                           push_delta_ms=plan.push_delta_ms)

    def paste_clip(self, segment, effects=(), *, at_ms: int) -> "MoveOutcome":
        """클립 1개 + 동반 효과를 트랙의 at_ms 위치에 붙여넣는다 (history 1회).

        insert_segment 를 쓰지 않는 이유: 그쪽은 start_ms <= 0 을 "트랙 끝에 append"
        로 해석한다. 붙여넣기는 사용자가 인디케이터를 0 에 두면 0 에 놓여야 하므로
        (앞이 비어 있으면 진짜로 0), 여기선 항상 명시 위치를 쓴다.

        자리 결정은 드래그 이동과 같은 규칙(clip_placement) — 인디케이터가 가리키는
        빈칸이 좁으면 그 자리에 넣고 뒤 클립들을 민다. 이전에는 들어갈 자리를 못 찾으면
        트랙 맨 뒤로 보내, 다른 영상에서 가져온 클립이 엉뚱한 곳에 붙었다.

        effects 의 in_ms/out_ms 는 클립 시작 기준 local ms — 배치된 start 를 더해
        트랙(combined) 시간축으로 옮긴다. 같은 type 과 겹치면 add_effect 와 같은 규칙으로
        빈 track_idx (sub-lane) 를 자동 할당.

        반환: MoveOutcome — 배치된 start_ms + 밀린 클립 수/양.
        """
        from dataclasses import replace
        from .clip_placement import apply_push, plan_placement
        dur = segment.duration_ms
        if dur <= 0:
            raise ValueError(
                f"길이 0 인 클립은 붙여넣을 수 없다 (src={segment.src!r})"
            )
        track = self._sidecar.video_track
        # segment 는 아직 트랙에 없는 새 클립이다 (클립보드가 붙여넣을 때마다 새 id 를
        # 발급한다). 그래서 배치 계산에서 제외할 id 가 없다 — 트랙에 이미 있는 클립을
        # 그대로 넘기면 자기 자신을 장애물로 보고 옆자리로 밀려난다.
        plan = plan_placement(track, max(0, int(at_ms)), dur)
        pushes = apply_push(track, plan)
        start = int(plan.start_ms)
        new_sc = copy.deepcopy(self._sidecar)
        # 밀리는 클립과 그 안의 효과 — 드래그 이동과 같은 정책.
        for i, moved_start in pushes:
            pushed = track[i]
            new_sc.video_track[i] = replace(pushed, start_ms=int(moved_start))
        if pushes:
            lo_hi = [(track[i].start_ms, track[i].start_ms + track[i].duration_ms)
                     for i, _ in pushes]
            for i, eff in enumerate(new_sc.effects):
                if any(lo <= eff.in_ms and eff.out_ms <= hi for lo, hi in lo_hi):
                    new_sc.effects[i] = replace(
                        eff,
                        in_ms=int(eff.in_ms + plan.push_delta_ms),
                        out_ms=int(eff.out_ms + plan.push_delta_ms),
                    )
        new_sc.video_track.append(replace(segment, start_ms=start))
        for eff in effects:
            moved = replace(eff, in_ms=int(start + eff.in_ms),
                            out_ms=int(start + eff.out_ms))
            new_sc.effects.append(self._assign_free_track_idx(new_sc.effects, moved))
        self.update_sidecar(new_sc)
        return MoveOutcome(moved=True, start_ms=start, pushed_count=len(pushes),
                           push_delta_ms=plan.push_delta_ms)

    def delete_segment(self, segment_id: str) -> bool:
        """id 로 segment 제거. 다른 segment 의 start_ms 는 변하지 않음 — 갭 그대로 유지.

        삭제된 segment 의 시간 범위에 완전히 포함된 effects 도 같이 제거 (고아 효과 방지).
        """
        track = self._sidecar.video_track
        target_seg = next((s for s in track if s.id == segment_id), None)
        if target_seg is None:
            return False
        old_start = target_seg.start_ms
        old_end = target_seg.start_ms + target_seg.duration_ms
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.video_track = [s for s in new_sc.video_track if s.id != segment_id]
        new_sc.effects = [
            e for e in new_sc.effects
            if not (old_start <= e.in_ms and e.out_ms <= old_end)
        ]
        self.update_sidecar(new_sc)
        return True

    def move_segment(self, from_idx: int, to_idx: int) -> bool:
        """레거시 API — 사용처 없음 (Stage 1 갭 모델로 대체).

        호출되면 list 순서만 바꾼다 (start_ms 는 그대로). 시각 효과는 없지만 시그널
        호환 위해 남겨둔다.
        """
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

    def set_segment_start(self, segment_id: str, new_start_ms: int) -> "MoveOutcome":
        """segment 를 트랙상 새 위치로 이동. 좁은 빈칸이면 뒤 클립들을 밀어 끼워 넣는다.

        위치 결정은 clip_placement.plan_placement 가 한다 (드래그 중 미리보기와 같은
        규칙). 놓은 지점이 가리키는 빈칸이 클립보다 넓으면 그대로, 좁으면 빈칸 시작에
        놓고 그 뒤 클립 전부를 부족분만큼 오른쪽으로 민다.

        같이 이동: segment 의 시간 범위에 완전히 포함되는 effects (caption/speed/zoom/broll)
        도 같은 delta 만큼 in_ms/out_ms shift — "자른 후 옮겨도 효과 따라감" (사용자 결정).
        밀려난 클립들의 효과도 같은 정책으로 밀림 양만큼 함께 이동한다.

        반환: MoveOutcome — 이동 여부 + 밀린 클립 수/양 (호출자가 사용자에게 알리도록).
        """
        from dataclasses import replace
        from .clip_placement import apply_push, plan_placement
        track = self._sidecar.video_track
        idx = next((i for i, s in enumerate(track) if s.id == segment_id), -1)
        if idx < 0:
            return MoveOutcome()
        seg = track[idx]
        others = [s for s in track if s.id != segment_id]
        plan = plan_placement(others, max(0, int(new_start_ms)), seg.duration_ms)
        pushes = apply_push(track, plan, exclude_id=segment_id)
        if plan.start_ms == seg.start_ms and not pushes:
            return MoveOutcome(start_ms=int(seg.start_ms))
        delta = plan.start_ms - seg.start_ms
        new_sc = copy.deepcopy(self._sidecar)
        new_sc.video_track[idx] = replace(seg, start_ms=int(plan.start_ms))
        # 옮기는 클립 + 밀려나는 클립들의 (옛 범위, 이동량) 을 모아 효과를 한 번에 처리.
        # 효과 동반은 "클립 안에 완전히 들어 있는 것만" — 걸쳐 있으면 의도가 모호해 제외.
        shifts: list[tuple[int, int, int]] = [
            (seg.start_ms, seg.start_ms + seg.duration_ms, delta)
        ]
        for i, moved_start in pushes:
            pushed = track[i]
            new_sc.video_track[i] = replace(pushed, start_ms=int(moved_start))
            shifts.append((pushed.start_ms, pushed.start_ms + pushed.duration_ms,
                           plan.push_delta_ms))
        for i, eff in enumerate(new_sc.effects):
            for lo, hi, d in shifts:
                if d and lo <= eff.in_ms and eff.out_ms <= hi:
                    new_sc.effects[i] = replace(
                        eff, in_ms=int(eff.in_ms + d), out_ms=int(eff.out_ms + d),
                    )
                    break
        # 한 번의 update_sidecar — 옮김 + 밀림 + 효과가 Ctrl+Z 한 번에 되돌아간다.
        self.update_sidecar(new_sc)
        return MoveOutcome(moved=True, start_ms=int(plan.start_ms),
                           pushed_count=len(pushes),
                           push_delta_ms=plan.push_delta_ms)

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

    # ---------- gap helpers ----------
    @staticmethod
    def _track_end_ms(track: list) -> int:
        """트랙의 마지막 점 — 모든 segment 의 end_ms 의 최대값. 빈 트랙이면 0."""
        return max((s.end_ms for s in track), default=0)

    @staticmethod
    def _clamp_to_free_slot(
        track: list, target_start: int, dur: int, *, ignore_id: str
    ) -> int:
        """target_start ~ target_start+dur 가 다른 segment 와 겹치면 가장 가까운 빈
        구간으로 밀어준다. 충돌 segment 의 좌측·우측 끝 중 가까운 쪽을 시도하고,
        그래도 안 들어가면 트랙 끝에 붙인다.
        """
        target = max(0, int(target_start))
        others = [s for s in track if s.id != ignore_id]
        if not others:
            return target
        # 충돌하지 않으면 그대로.
        def overlaps_any(start: int) -> "VideoSegment | None":
            end = start + dur
            for s in others:
                if start < s.end_ms and end > s.start_ms:
                    return s
            return None
        hit = overlaps_any(target)
        if hit is None:
            return target
        # target 위치에 충돌 — 그 segment 의 좌측 끝 (target_start = hit.start_ms - dur)
        # 또는 우측 끝 (target_start = hit.end_ms) 중 target 에 가까운 쪽으로 밀어 넣고
        # 거기도 충돌하면 그 다음 빈 slot 으로 재귀.
        candidates = sorted(
            [max(0, hit.start_ms - dur), hit.end_ms],
            key=lambda x: abs(x - target),
        )
        for cand in candidates:
            if cand < 0:
                continue
            if overlaps_any(cand) is None:
                return cand
        # 어디도 못 들어가면 트랙 끝.
        return EditController._track_end_ms(track)

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

    def flush_autosave(self) -> bool:
        """디바운스 타이머가 pending 이면 즉시 저장 (탭 닫힘 / 앱 종료 시 호출).

        타이머가 활성 상태(=변경 후 500ms 안에 호출됨)이면 stop 하고 즉시 디스크 flush.
        그렇지 않으면 no-op (이미 저장된 상태).

        반환: 실제 디스크 저장이 일어났으면 True, 변경 없어 no-op 면 False.
        """
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._do_autosave()
            return True
        return False

    def set_sidecar_dir(self, new_dir: Path) -> None:
        """사이드카 폴더 변경 — 다음 save_for / load_for 부터 새 경로 사용.

        Phase 19.5: 환경설정에서 사이드카 폴더 변경 시 기존 영상 탭들에도 즉시 반영.
        이전 폴더의 .kstudio 는 그대로 두고, 다음 save 부터 새 폴더에 저장.
        """
        self._store = SidecarStore(Path(new_dir))

    def save_now(self) -> bool:
        """사용자 Ctrl+S — 항상 즉시 디스크 저장. 변경 없어도 사이드카 다시 씀.

        Phase 19.5 사용자 보고: autosave 디바운스(500ms)가 끝나면 flush_autosave 가
        no-op 으로 떨어져 "이미 최신 상태" 만 뜨는 회귀. 사용자 멘탈모델은
        "Ctrl+S = 무조건 저장" — 변경 없는 경우에도 디스크 write 한 번 더 해도
        idempotent + 부담 없음. 반환: 저장 성공이면 True, OSError 면 False.
        """
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        try:
            self._write_sidecar()
            return True
        except OSError as e:
            self.autosave_failed.emit(str(e))
            return False

    def project_path(self) -> Optional[Path]:
        """빈 프로젝트의 사이드카 파일 경로. 소스 영상 기반 탭이면 None."""
        return self._save_path

    # ---------- internal ----------
    def _write_sidecar(self) -> None:
        """사이드카 디스크 기록 — 저장 위치 결정의 단일 지점.

        save_path 가 있으면(빈 프로젝트) 그 파일에 그대로 쓴다. SidecarStore 의
        `<basename>_<hash>` 명명은 영상 파일 hash 를 전제하는데 빈 프로젝트엔 그
        영상이 없다.
        """
        if self._save_path is not None:
            from ...effects.sidecar import save_atomic
            self._save_path.parent.mkdir(parents=True, exist_ok=True)
            save_atomic(self._save_path, self._sidecar)
            return
        self._store.save_for(self._video_path, self._sidecar)

    def _do_autosave(self) -> None:
        try:
            self._write_sidecar()
        except OSError as e:
            self.autosave_failed.emit(str(e))
