"""ClipClipboard — 탭 밖에 사는 전역 클립보드의 단위 동작."""
import pytest

from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video.clip_clipboard import ClipClipboard, clipboard


def _seg(start_ms: int = 4000, dur: int = 6000) -> VideoSegment:
    return VideoSegment(
        src="C:/a.mp4", src_in_ms=0, src_out_ms=dur, src_duration_ms=dur,
        start_ms=start_ms,
    )


def test_empty_clipboard_reports_no_kind():
    cb = ClipClipboard()
    assert cb.kind() is None
    assert cb.take_segment() is None
    assert cb.take_effect() is None


def test_copy_segment_rebases_effects_to_local_ms():
    """동반 효과는 클립 시작 기준 local ms 로 저장 — 붙여넣는 쪽이 위치만 더하면 된다."""
    cb = ClipClipboard()
    seg = _seg(start_ms=4000)
    cap = CaptionEffect(in_ms=5000, out_ms=8000, text="hi")
    cb.copy_segment(seg, [cap])

    taken_seg, effs = cb.take_segment()
    assert taken_seg.src == "C:/a.mp4"
    assert len(effs) == 1
    assert (effs[0].in_ms, effs[0].out_ms) == (1000, 4000)   # 4000 만큼 당겨짐


def test_take_segment_gives_fresh_ids_every_time():
    """반복 붙여넣기 — 매번 새 id. 효과 id 도 새로 (중복이면 Del 한 번에 둘 다 지워짐)."""
    cb = ClipClipboard()
    seg = _seg()
    cap = CaptionEffect(in_ms=4000, out_ms=7000, text="hi")
    cb.copy_segment(seg, [cap])

    a_seg, a_effs = cb.take_segment()
    b_seg, b_effs = cb.take_segment()
    assert a_seg.id != b_seg.id
    assert a_seg.id != seg.id
    assert a_effs[0].id != b_effs[0].id
    assert a_effs[0].id != cap.id


def test_copy_segment_rejects_zero_duration():
    """길이 0 클립은 붙여넣어도 되살릴 수 없는 1px 조각 — 조용히 담지 않고 거부."""
    cb = ClipClipboard()
    zero = VideoSegment(src="C:/a.mp4", src_in_ms=0, src_out_ms=0, src_duration_ms=0)
    with pytest.raises(ValueError):
        cb.copy_segment(zero)
    assert cb.kind() is None


def test_copy_effect_replaces_segment_and_vice_versa():
    """마지막 복사가 이긴다 — kind 가 뒤바뀌면 이전 내용은 사라진다."""
    cb = ClipClipboard()
    cb.copy_segment(_seg())
    assert cb.kind() == "segment"
    cb.copy_effect(CaptionEffect(in_ms=0, out_ms=1000, text="x"))
    assert cb.kind() == "effect"
    assert cb.take_segment() is None
    cb.copy_segment(_seg())
    assert cb.take_effect() is None


def test_take_effect_deep_copies_nested_dataclass():
    """중첩 dataclass (font 등) 는 원본과 공유되면 안 된다."""
    cb = ClipClipboard()
    cap = CaptionEffect(in_ms=0, out_ms=1000, text="x")
    cb.copy_effect(cap)
    taken = cb.take_effect()
    assert taken.id != cap.id
    assert taken.font is not cap.font


def test_module_clipboard_is_a_singleton():
    assert clipboard() is clipboard()
