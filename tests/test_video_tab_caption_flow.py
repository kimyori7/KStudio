"""VideoTab — 캡션 추가/수정/삭제 흐름."""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 200_000)
    return p


def _make_tab(qtbot, sample_mp4, tmp_path):
    tab = VideoTab(
        path=sample_mp4, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.set_edit_mode(True)
    return tab


def test_lane_request_add_creates_caption_at_ms(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    # 가짜로 lanes_widget 의 시그널 발화
    tab.lanes_widget().request_add.emit("caption", 5000)

    sc = tab.sidecar()
    assert len(sc.effects) == 1
    e = sc.effects[0]
    assert e.type == "caption"
    assert e.in_ms == 5000
    assert e.out_ms == 5000 + 3000


def test_video_tab_accepts_external_file_drop(qtbot, sample_mp4, tmp_path):
    """VideoTab 에 드래그-드롭 활성화 + dragEnterEvent 가 영상 url 수락.

    실제 segment 생성은 ffmpeg 가 영상 길이를 읽어야 하므로 단위 테스트에서는
    수락 여부만 검증. _on_track_insert_files 의 위임 경로는 별도 통합 테스트.
    """
    from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent

    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    assert tab.acceptDrops() is True

    extra = tmp_path / "extra.mp4"
    extra.write_bytes(b"")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(extra))])
    enter = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    tab.dragEnterEvent(enter)
    assert enter.isAccepted()


def test_video_tab_ignores_unsupported_file_drop(qtbot, sample_mp4, tmp_path):
    """영상/이미지 확장자 외 파일은 거부."""
    from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent

    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    other = tmp_path / "doc.pdf"
    other.write_bytes(b"")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(other))])
    enter = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    tab.dragEnterEvent(enter)
    assert not enter.isAccepted()


def test_ctrl_c_copies_active_effect_to_clipboard(qtbot, sample_mp4, tmp_path):
    """효과 선택 후 Ctrl+C → _effect_clipboard 에 deep copy 저장."""
    from PySide6.QtCore import Qt
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 1000)
    sc = tab.sidecar()
    cap = sc.effects[0]
    tab._active_kind = "effect"
    tab._active_id = cap.id
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyClick(tab, Qt.Key_C, Qt.ControlModifier)
    assert tab._effect_clipboard is not None
    assert tab._effect_clipboard.id == cap.id


def test_ctrl_v_pastes_effect_with_new_id(qtbot, sample_mp4, tmp_path):
    """Ctrl+V → clipboard 의 효과를 새 id 로 사이드카에 추가."""
    from PySide6.QtCore import Qt
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 1000)
    sc = tab.sidecar()
    cap = sc.effects[0]
    tab._active_kind = "effect"
    tab._active_id = cap.id
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    # 복사 → 빈 위치로 playhead 이동 → 붙여넣기.
    qtbot.keyClick(tab, Qt.Key_C, Qt.ControlModifier)
    tab.timeline.set_position_ms(6000)   # 캡션 (1000~4000) 과 겹치지 않는 위치
    qtbot.keyClick(tab, Qt.Key_V, Qt.ControlModifier)
    after = tab.sidecar().effects
    # 두 개의 caption — 원본 + 복사본.
    captions = [e for e in after if e.type == "caption"]
    assert len(captions) == 2
    new_caption = next(c for c in captions if c.id != cap.id)
    # duration 보존.
    assert new_caption.out_ms - new_caption.in_ms == cap.out_ms - cap.in_ms


def test_new_caption_inherits_last_used_font(qtbot, sample_mp4, tmp_path):
    """첫 캡션 → 폰트 수정 후 두 번째 캡션 추가 → 두 번째도 같은 폰트/크기/굵기."""
    from dataclasses import replace
    from screen_recorder.effects.types.caption import Font
    tab = _make_tab(qtbot, sample_mp4, tmp_path)

    # 1) 첫 캡션 추가 (기본 폰트).
    tab.lanes_widget().request_add.emit("caption", 1000)
    sc = tab.sidecar()
    first = sc.effects[0]
    assert first.font.family == "sans-serif"  # 기본
    assert first.font.size == 36

    # 2) 사용자가 폰트 변경 — 인스펙터 경로 모사 (update_effect 직접 호출).
    custom = Font(family="Arial", size=72, bold=True)
    new_first = replace(first, font=custom)
    tab.edit_controller().update_effect(new_first)

    # 3) 두 번째 캡션 추가 → 첫 캡션의 폰트 그대로 상속.
    tab.lanes_widget().request_add.emit("caption", 5000)
    sc2 = tab.sidecar()
    captions = [e for e in sc2.effects if e.type == "caption"]
    assert len(captions) == 2
    new_caption = max(captions, key=lambda e: e.in_ms)
    assert new_caption.font.family == "Arial"
    assert new_caption.font.size == 72
    assert new_caption.font.bold is True


def test_t_shortcut_adds_caption_at_current_position(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    # 현재 재생 위치를 명시적으로 설정 — player_widget 의 mock
    tab.timeline.set_position_ms(2000)
    qtbot.keyClick(tab, Qt.Key_T)

    sc = tab.sidecar()
    assert len(sc.effects) == 1
    assert sc.effects[0].in_ms == 2000
    assert sc.effects[0].out_ms == 5000


def test_t_shortcut_no_op_when_edit_mode_off(qtbot, sample_mp4, tmp_path):
    tab = VideoTab(
        path=sample_mp4, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    # 편집 모드 OFF
    qtbot.keyClick(tab, Qt.Key_T)
    assert len(tab.sidecar().effects) == 0


def test_lane_effect_deleted_removes_from_sidecar(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 1000)
    cap_id = tab.sidecar().effects[0].id

    tab.lanes_widget().effect_deleted.emit(cap_id)
    assert tab.sidecar().effects == []


def test_lane_effect_changed_updates_sidecar(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 1000)
    eff = tab.sidecar().effects[0]
    from dataclasses import replace
    moved = replace(eff, in_ms=2000, out_ms=2000 + 3000)

    tab.lanes_widget().effect_changed.emit(moved)
    assert tab.sidecar().effects[0].in_ms == 2000


def test_add_caption_near_end_clamps_or_rejects(qtbot, sample_mp4, tmp_path):
    """영상 9.5초 위치에 추가 시 기본 3초 길이가 안 들어가 → 거부 또는 clamp."""
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 9500)
    sc = tab.sidecar()
    if len(sc.effects) == 1:
        # clamp 정책: 영상 끝까지 길이 자름
        e = sc.effects[0]
        assert e.in_ms == 9500
        assert e.out_ms <= 10_000
    else:
        # reject 정책: 0 개
        assert len(sc.effects) == 0
