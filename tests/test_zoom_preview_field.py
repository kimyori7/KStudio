"""ZoomEffect.preview 필드 + ZoomInspector 체크박스 + 라이브 transform.

Stage 3 (2026-05-08): preview ON 인 zoom 구간 재생 시 PlayerWidget 에 zoom transform
가 적용되도록 video_tab 의 _on_position_for_zoom 가 player.set_zoom_preview 를 호출.
"""
from unittest.mock import MagicMock

from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint


def test_zoom_effect_preview_default_false():
    eff = ZoomEffect(in_ms=0, out_ms=1000)
    assert eff.preview is False


def test_zoom_effect_preview_can_be_set_true():
    eff = ZoomEffect(in_ms=0, out_ms=1000, preview=True)
    assert eff.preview is True


def test_zoom_inspector_preview_checkbox_round_trip(qtbot):
    from screen_recorder.ui.video.inspectors.zoom_inspector import ZoomInspector
    insp = ZoomInspector()
    qtbot.addWidget(insp)
    eff = ZoomEffect(
        in_ms=0, out_ms=2000, preview=True,
        start=ZoomPoint(cx=0.5, cy=0.5, scale=2.0),
        end=ZoomPoint(cx=0.5, cy=0.5, scale=2.0),
    )
    insp.set_effect(eff)
    assert insp._preview_chk.isChecked() is True
    # OFF 로 토글 → effect_changed 시그널의 새 effect.preview = False.
    received: list[ZoomEffect] = []
    insp.effect_changed.connect(lambda e: received.append(e))
    insp._preview_chk.setChecked(False)
    assert received[-1].preview is False


def test_player_widget_set_zoom_preview_stores_params(qtbot):
    from screen_recorder.ui.video.player_widget import PlayerWidget
    pw = PlayerWidget()
    qtbot.addWidget(pw)
    pw.set_zoom_preview((0.5, 0.5, 2.0))
    assert pw._video_surface._zoom_preview == (0.5, 0.5, 2.0)
    pw.set_zoom_preview(None)
    assert pw._video_surface._zoom_preview is None
