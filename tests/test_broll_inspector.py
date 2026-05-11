"""BrollInspector — 폼 값 ↔ BrollEffect 양방향, file/placement/corner/size/audio_mix 편집."""
from __future__ import annotations

import pytest

from screen_recorder.effects.types.broll import BrollEffect, PipConfig
from screen_recorder.ui.video.inspectors.broll_inspector import BrollInspector


@pytest.fixture
def inspector(qtbot):
    w = BrollInspector()
    qtbot.addWidget(w)
    return w


def _make_broll(*, src="b.mp4", placement="pip", corner="bottom-right",
                 size_ratio=0.3, audio_mix="both",
                 in_ms=1000, out_ms=4000) -> BrollEffect:
    pip = (PipConfig(corner=corner, size_ratio=size_ratio)
           if placement == "pip" else None)
    return BrollEffect(
        in_ms=in_ms, out_ms=out_ms, src=src,
        placement=placement, pip=pip, audio_mix=audio_mix,
    )


def test_load_effect_populates_fields(inspector):
    """src='b.mp4', placement='pip', pip=(top-left, 0.4): 콤보/라디오 반영."""
    eff = _make_broll(src="b.mp4", placement="pip",
                       corner="top-left", size_ratio=0.4,
                       audio_mix="both")
    inspector.set_effect(eff)
    assert "b.mp4" in inspector._src_label.text()
    assert inspector._placement_combo.currentText() == "PiP (모서리 작게)"
    # top-left 라디오가 체크되어 있어야 함 (index 0).
    btn = inspector._corner_group.button(0)
    assert btn is not None
    assert btn.isChecked()
    assert inspector._size_combo.currentText() == "40%"
    assert inspector._audio_mix_combo.currentText() == "둘 다 (믹스)"
    assert inspector._in_spin.value() == 1000
    assert inspector._out_spin.value() == 4000


def test_change_corner_emits_effect_changed(inspector):
    """top-right 라디오 클릭 → 발화된 effect 의 pip.corner=='top-right'."""
    eff = _make_broll(corner="bottom-right")
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    # top-right = index 1
    inspector._corner_group.button(1).setChecked(True)

    assert any(e.pip is not None and e.pip.corner == "top-right" for e in received)


def test_change_audio_mix_emits(inspector):
    """audio_mix 콤보 → '음소거' 선택 시 effect_changed(audio_mix='mute')."""
    eff = _make_broll(audio_mix="original_only")
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    inspector._audio_mix_combo.setCurrentText("음소거")

    assert any(e.audio_mix == "mute" for e in received)


def test_switch_to_fullscreen_disables_pip_widgets(inspector):
    """placement → 'fullscreen' 전환 시 corner radio + size combo isEnabled=False."""
    eff = _make_broll(placement="pip")
    inspector.set_effect(eff)
    # 초기 상태 — PiP 위젯 활성.
    assert all(rb.isEnabled() for rb in inspector._corner_radios)
    assert inspector._size_combo.isEnabled()
    # isVisible 은 부모가 show 되기 전엔 False — isHidden 으로 검사.
    assert inspector._fullscreen_warning_label.isHidden()

    inspector._placement_combo.setCurrentText("전체 화면 (자르기 끼워넣기 권장)")

    # 전환 후 — PiP 위젯 비활성 + 경고 라벨 표시.
    assert not any(rb.isEnabled() for rb in inspector._corner_radios)
    assert inspector._size_combo.isEnabled() is False
    assert not inspector._fullscreen_warning_label.isHidden()


def test_switch_back_to_pip_re_enables_widgets(inspector):
    """fullscreen → pip 복귀 시 PiP 위젯 다시 활성화."""
    eff = _make_broll(placement="pip")
    inspector.set_effect(eff)
    inspector._placement_combo.setCurrentText("전체 화면 (자르기 끼워넣기 권장)")
    assert not inspector._size_combo.isEnabled()
    inspector._placement_combo.setCurrentText("PiP (모서리 작게)")
    assert inspector._size_combo.isEnabled()
    assert all(rb.isEnabled() for rb in inspector._corner_radios)
    assert inspector._fullscreen_warning_label.isHidden()


def test_delete_emits_effect_deleted(inspector, qtbot):
    """'이 곁들임 삭제' 버튼 → effect_deleted(effect.id) 발화."""
    eff = _make_broll()
    inspector.set_effect(eff)
    with qtbot.waitSignal(inspector.effect_deleted, timeout=1000) as blocker:
        inspector._delete_btn.click()
    assert blocker.args == [eff.id]


def test_set_effect_none_disables_form(inspector):
    """None 전달 시 폼 모든 위젯이 disabled."""
    inspector.set_effect(None)
    assert inspector._pick_btn.isEnabled() is False
    assert inspector._placement_combo.isEnabled() is False
    assert inspector._audio_mix_combo.isEnabled() is False
    assert inspector._delete_btn.isEnabled() is False


def test_no_signal_during_set_effect_load(inspector):
    """set_effect 로 폼 채우는 동안 effect_changed 가 발화하지 않음."""
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector.set_effect(_make_broll(corner="top-left", size_ratio=0.4))
    assert received == []


def test_load_effect_alias_works(inspector):
    """load_effect alias 도 set_effect 와 동일 동작."""
    eff = _make_broll(src="x.mp4")
    inspector.load_effect(eff)
    assert "x.mp4" in inspector._src_label.text()


def test_change_to_fullscreen_emits_with_pip_none(inspector):
    """placement='fullscreen' 전환 시 발화된 effect.pip 가 None."""
    eff = _make_broll(placement="pip")
    inspector.set_effect(eff)
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector._placement_combo.setCurrentText("전체 화면 (자르기 끼워넣기 권장)")
    assert any(e.placement == "fullscreen" and e.pip is None for e in received)


def test_drop_video_url_updates_src_and_emits(inspector, tmp_path):
    """탐색기에서 mp4 를 BrollInspector 위에 떨어뜨리면 src 가 갱신되고 effect_changed 발화."""
    from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    eff = _make_broll(src="old.mp4")
    inspector.set_effect(eff)

    dropped = tmp_path / "new.mp4"
    dropped.write_bytes(b"x")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(dropped))])

    received: list = []
    inspector.effect_changed.connect(received.append)
    evt = QDropEvent(
        QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier,
    )
    inspector.dropEvent(evt)
    assert any(getattr(e, "src", "").endswith("new.mp4") for e in received)
    assert "new.mp4" in inspector._src_label.text()


def test_drop_unsupported_suffix_ignored(inspector, tmp_path):
    """txt 같은 비지원 확장자는 ignore — effect_changed 미발화."""
    from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    eff = _make_broll(src="old.mp4")
    inspector.set_effect(eff)

    dropped = tmp_path / "notes.txt"
    dropped.write_bytes(b"x")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(dropped))])

    received: list = []
    inspector.effect_changed.connect(received.append)
    evt = QDropEvent(
        QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier,
    )
    inspector.dropEvent(evt)
    assert received == []
    assert "old.mp4" in inspector._src_label.text()
