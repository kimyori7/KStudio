"""CutInspector — 폼 값 ↔ CutEffect 양방향, 파일 선택, 모드 라디오."""
from PySide6.QtCore import Qt
import pytest

from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.ui.video.inspectors.cut_inspector import CutInspector


@pytest.fixture
def inspector(qtbot):
    w = CutInspector()
    qtbot.addWidget(w)
    w.show()
    return w


def test_set_effect_populates_form_for_range_with_insert(inspector):
    e = CutEffect(
        in_ms=4000, out_ms=7000,
        src=r"D:\Clips\b.mp4",
        src_in_ms=500, src_out_ms=4500,
        src_duration_ms=6000,
        scale_mode="fill",
    )
    inspector.set_effect(e)
    assert inspector.in_ms_spin.value() == 4000
    assert inspector.out_ms_spin.value() == 7000
    assert inspector.src_in_ms_spin.value() == 500
    assert inspector.src_out_ms_spin.value() == 4500
    assert inspector.scale_mode_group.checkedId() == 1  # fill 인덱스


def test_set_effect_for_splice_locks_out_ms(inspector):
    e = CutEffect(in_ms=3000, out_ms=3000, src="x.mp4", src_duration_ms=2000)
    inspector.set_effect(e)
    assert inspector.splice_check.isChecked()
    assert not inspector.out_ms_spin.isEnabled()


def test_set_effect_for_simple_cut_shows_add_video_button(inspector):
    """src 비어있는 단순 자르기는 [+ 영상 넣기] 버튼이 보이고, src 폼 영역은 hidden 또는 비활성."""
    e = CutEffect(in_ms=4000, out_ms=7000)
    inspector.set_effect(e)
    assert inspector.add_video_btn.isVisible()
    assert not inspector.has_src_section()


def test_change_in_ms_emits_effect_changed(inspector, qtbot):
    e = CutEffect(in_ms=4000, out_ms=7000, src="x.mp4", src_duration_ms=2000, src_out_ms=2000)
    inspector.set_effect(e)
    with qtbot.waitSignal(inspector.effect_changed) as sig:
        inspector.in_ms_spin.setValue(5000)
    assert sig.args[0].in_ms == 5000


def test_change_scale_mode_emits(inspector, qtbot):
    e = CutEffect(in_ms=0, out_ms=1000, src="x.mp4", src_duration_ms=2000, src_out_ms=2000)
    inspector.set_effect(e)
    with qtbot.waitSignal(inspector.effect_changed) as sig:
        # 라디오 변경 — index 2 = stretch
        btn = inspector.scale_mode_group.button(2)
        btn.setChecked(True)
    assert sig.args[0].scale_mode == "stretch"


def test_pick_file_via_stub_sets_src(inspector, qtbot, monkeypatch):
    e = CutEffect(in_ms=4000, out_ms=7000)
    inspector.set_effect(e)
    # QFileDialog.getOpenFileName 을 stub
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **kw: (r"D:\Clips\new.mp4", "")))
    # ffprobe 도 stub — 실제 파일 없어도 길이 5000 반환
    import screen_recorder.ui.video.inspectors.cut_inspector as ci
    monkeypatch.setattr(ci, "probe_duration_ms", lambda path: 5000)
    with qtbot.waitSignal(inspector.effect_changed) as sig:
        inspector.add_video_btn.click()
    assert sig.args[0].src == r"D:\Clips\new.mp4"
    assert sig.args[0].src_duration_ms == 5000


def test_combined_length_label_updates(inspector):
    e = CutEffect(in_ms=4000, out_ms=7000, src="x.mp4", src_in_ms=0, src_out_ms=4000, src_duration_ms=4000)
    inspector.set_effect(e)
    # 결합 후 = (자르기 -3000) + (B +4000) = +1000ms 만큼 늘어남 (원본 길이는 모르므로 차이만 표기)
    assert "1.0s" in inspector.combined_label.text() or "+1" in inspector.combined_label.text()


def test_splice_toggle_emits_once(inspector, qtbot):
    """splice 토글 ON 시 effect_changed 가 정확히 1회만 발화 — 더블 에밋 회귀 방지.

    이전 버그: setValue(in_ms_spin.value()) → valueChanged → _on_any_change(emit#1)
    + 명시 _on_any_change(emit#2). undo 2번 필요했음.
    """
    e = CutEffect(in_ms=4000, out_ms=7000, src="x.mp4", src_duration_ms=2000, src_out_ms=2000)
    inspector.set_effect(e)
    received = []
    inspector.effect_changed.connect(received.append)
    inspector.splice_check.setChecked(True)
    assert len(received) == 1
    assert received[0].is_splice


# ============================================================
# 2026-05-19 다: preview_skip 체크박스 — 재생 시 cut 자동 skip 여부 토글
# ============================================================
def test_preview_skip_checkbox_default_checked(inspector):
    """기본값 preview_skip=True → 체크 ON 상태."""
    e = CutEffect(in_ms=1000, out_ms=2000)
    inspector.set_effect(e)
    assert inspector.preview_skip_check.isChecked()


def test_preview_skip_checkbox_off_for_false_effect(inspector):
    e = CutEffect(in_ms=1000, out_ms=2000, preview_skip=False)
    inspector.set_effect(e)
    assert not inspector.preview_skip_check.isChecked()


def test_preview_skip_toggle_emits_effect_changed(inspector, qtbot):
    """체크박스 토글 시 effect_changed 발화 + 새 effect.preview_skip 반영."""
    e = CutEffect(in_ms=1000, out_ms=2000)   # preview_skip=True (기본)
    inspector.set_effect(e)
    with qtbot.waitSignal(inspector.effect_changed) as sig:
        inspector.preview_skip_check.setChecked(False)
    assert sig.args[0].preview_skip is False


def test_preview_skip_toggle_back_on_emits(inspector, qtbot):
    e = CutEffect(in_ms=1000, out_ms=2000, preview_skip=False)
    inspector.set_effect(e)
    with qtbot.waitSignal(inspector.effect_changed) as sig:
        inspector.preview_skip_check.setChecked(True)
    assert sig.args[0].preview_skip is True


def test_preview_skip_preserved_through_other_field_changes(inspector, qtbot):
    """preview_skip=False 인 채로 in_ms 변경 시 preview_skip 값 유지."""
    e = CutEffect(in_ms=1000, out_ms=2000, preview_skip=False)
    inspector.set_effect(e)
    with qtbot.waitSignal(inspector.effect_changed) as sig:
        inspector.in_ms_spin.setValue(1500)
    assert sig.args[0].preview_skip is False
    assert sig.args[0].in_ms == 1500
