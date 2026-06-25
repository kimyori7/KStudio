"""디스크 rename 후 in-memory 사이드카/히스토리 경로 마이그레이션.

영상 파일 이름을 바꾸면 (편집 탭이 열린 채로) sidecar.source_path 와 같은 파일을
가리키던 video_track segment.src, 그리고 undo/redo 히스토리의 모든 스냅샷이 새 경로로
즉시 갱신돼야 export/preview/undo 가 깨지지 않는다.
"""
from __future__ import annotations

from screen_recorder.effects.sidecar import Sidecar, migrate_sidecar_source
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.history import History


OLD = "E:/KStudio_Image/Video/rec_20260622_160747.mp4"
NEW = "E:/KStudio_Image/Video/260623 Sample.mp4"


def _sidecar_with_segments(src: str) -> Sidecar:
    return Sidecar(
        source_path=src,
        source_hash="deadbeef",
        video_track=[
            VideoSegment(src=src, start_ms=0, src_duration_ms=5000),
            VideoSegment(src=src, start_ms=5000, src_in_ms=1000, src_out_ms=3000),
        ],
    )


def test_migrate_updates_source_path_and_matching_segments():
    sc = _sidecar_with_segments(OLD)
    migrate_sidecar_source(sc, OLD, NEW)
    assert sc.source_path == NEW
    assert [s.src for s in sc.video_track] == [NEW, NEW]


def test_migrate_leaves_other_sources_untouched():
    """멀티-소스 concat — 다른 영상에서 온 segment 의 src 는 건드리지 않는다."""
    other = "E:/KStudio_Image/Video/intro.mp4"
    sc = Sidecar(
        source_path=OLD,
        video_track=[
            VideoSegment(src=OLD, start_ms=0, src_duration_ms=5000),
            VideoSegment(src=other, start_ms=5000, src_duration_ms=2000),
        ],
    )
    migrate_sidecar_source(sc, OLD, NEW)
    assert sc.source_path == NEW
    assert [s.src for s in sc.video_track] == [NEW, other]


def test_migrate_fills_empty_source_path():
    sc = Sidecar(source_path="", video_track=[])
    migrate_sidecar_source(sc, OLD, NEW)
    assert sc.source_path == NEW


def test_history_migrate_applies_to_all_retained_states():
    """undo/redo 스택의 모든 스냅샷이 새 경로로 갱신 — rename 후 undo 해도 안 깨짐."""
    s0 = _sidecar_with_segments(OLD)
    hist = History(initial=s0)
    # 두 번 push → undo 스택에 과거 상태 쌓임.
    hist.push(_sidecar_with_segments(OLD))
    hist.push(_sidecar_with_segments(OLD))
    # 한 번 undo → redo 스택에도 상태 생김.
    hist.undo()

    hist.migrate(lambda sc: migrate_sidecar_source(sc, OLD, NEW))

    # current / undo 전체 / redo 전체 모두 새 경로.
    assert hist.current().source_path == NEW
    assert all(s.src == NEW for s in hist.current().video_track)
    # undo 를 끝까지 돌려도 전부 NEW.
    while hist.can_undo():
        sc = hist.undo()
        assert sc.source_path == NEW
        assert all(s.src == NEW for s in sc.video_track)
    # redo 도 전부 NEW.
    while hist.can_redo():
        sc = hist.redo()
        assert sc.source_path == NEW
