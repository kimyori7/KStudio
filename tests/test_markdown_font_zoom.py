"""Markdown 폰트 크기 조절 — 편집기/미리보기 각각 독립 줌 (툴바 버튼 + Ctrl+휠 + 영속).

사용자 요청 2026-05-29: "폰트 크기 전반적으로 크게, 작게 할수 있는 기능 필요해.
편집 미리보기, 나란히 일때도 각각."

주의: conftest 가 KSTUDIO_DISABLE_WEBENGINE=1 → 미리보기는 Fallback(QTextBrowser).
따라서 setZoomFactor / KZOOM(Ctrl+휠) 같은 WebEngine 경로는 여기서 검증되지 않는다
(수동 재시작 확인 필요). 아래는 상태/클램프/영속/Fallback 줌/가시성만 검증.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent


def test_editor_set_font_point_size_clamps(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.set_font_point_size(100)
    assert ed.font().pointSize() == 32      # 상한 클램프
    ed.set_font_point_size(1)
    assert ed.font().pointSize() == 8       # 하한 클램프
    ed.set_font_point_size(14)
    assert ed.font().pointSize() == 14


def test_editor_font_change_grows_gutter(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.set_font_point_size(11)
    small = ed.line_number_area_width()
    ed.set_font_point_size(24)
    assert ed.line_number_area_width() > small   # 거터가 폰트에 맞춰 재계산


def test_bump_editor_emits_and_applies(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    seen: list[tuple[int, float]] = []
    tab.font_settings_changed.connect(lambda pt, z: seen.append((pt, z)))
    tab._bump_editor(+1)
    assert tab.editor.font().pointSize() == 12
    assert seen[-1] == (12, 1.0)


def test_bump_preview_emits_and_applies(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    seen: list[tuple[int, float]] = []
    tab.font_settings_changed.connect(lambda pt, z: seen.append((pt, z)))
    tab._bump_preview(+1)
    assert abs(tab._preview_zoom - 1.1) < 1e-6
    assert seen[-1][0] == 11
    assert abs(seen[-1][1] - 1.1) < 1e-6


def test_reset_fonts_restores_defaults(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab._bump_editor(+5)
    tab._bump_preview(+3)
    seen: list[tuple[int, float]] = []
    tab.font_settings_changed.connect(lambda pt, z: seen.append((pt, z)))
    tab._reset_fonts()
    assert tab.editor.font().pointSize() == 11
    assert abs(tab._preview_zoom - 1.0) < 1e-6
    assert seen[-1] == (11, 1.0)


def test_editor_clamp_does_not_exceed_max(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    for _ in range(50):
        tab._bump_editor(+1)
    assert tab.editor.font().pointSize() == MarkdownTab.EDITOR_MAX_PT
    for _ in range(50):
        tab._bump_editor(-1)
    assert tab.editor.font().pointSize() == MarkdownTab.EDITOR_MIN_PT


def test_preview_clamp_bounds(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    for _ in range(100):
        tab._bump_preview(+1)
    assert abs(tab._preview_zoom - MarkdownTab.PREVIEW_MAX_ZOOM) < 1e-6
    for _ in range(100):
        tab._bump_preview(-1)
    assert abs(tab._preview_zoom - MarkdownTab.PREVIEW_MIN_ZOOM) < 1e-6


def test_from_blank_applies_initial_sizes(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank(editor_font_pt=16, preview_zoom=1.5)
    qtbot.addWidget(tab)
    assert tab.editor.font().pointSize() == 16
    assert abs(tab._preview_zoom - 1.5) < 1e-6


def test_from_file_applies_initial_sizes(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "a.md"
    p.write_text("# t", encoding="utf-8")
    tab = MarkdownTab.from_file(p, editor_font_pt=20, preview_zoom=0.8)
    qtbot.addWidget(tab)
    assert tab.editor.font().pointSize() == 20
    assert abs(tab._preview_zoom - 0.8) < 1e-6


def test_fallback_set_zoom_changes_font(qtbot):
    # conftest 가 WebEngine 끔 → Fallback QTextBrowser. set_zoom 이 base*factor 로 폰트 조정.
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    browser = pv._renderer.widget()
    base = browser.fontInfo().pointSizeF()
    pv.set_zoom(2.0)
    assert browser.font().pointSizeF() > base * 1.5   # 대략 2배 (정수 반올림 여유)


def test_preview_zoom_survives_content_refresh(qtbot):
    # 회귀: 줌 적용 후 본문이 다시 렌더돼도(setHtml) 폰트 크기가 유지돼야 함.
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    browser = pv._renderer.widget()
    pv.set_zoom(2.0)
    enlarged = browser.font().pointSizeF()
    pv.set_content("# 새 내용\n본문", None)   # setHtml 재렌더
    assert abs(browser.font().pointSizeF() - enlarged) < 1e-6


def test_font_controls_visibility_by_mode(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab, ViewMode
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.show()
    tab.set_view_mode(ViewMode.EDITOR)
    assert tab._editor_font_group.isVisible()
    assert not tab._preview_font_group.isVisible()
    tab.set_view_mode(ViewMode.PREVIEW)
    assert tab._preview_font_group.isVisible()
    assert not tab._editor_font_group.isVisible()
    tab.set_view_mode(ViewMode.SPLIT)
    assert tab._editor_font_group.isVisible()
    assert tab._preview_font_group.isVisible()


def test_editor_font_works_under_theme_qss(qtbot):
    """회귀(2026-05-29): 전역 테마 QSS `QWidget{font-size:10pt}` 가 setFont() 를 덮어쓴다.
    편집기 폰트는 위젯별 stylesheet 로 지정해야 프로덕션(테마 적용)에서 실제로 커진다.
    setFont 로 되돌리면 이 테스트가 깨진다."""
    from PySide6.QtWidgets import QApplication
    from screen_recorder.ui import theme
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    app = QApplication.instance()
    prev = app.styleSheet()
    theme.apply_theme(app, "video")            # 프로덕션처럼 전역 폰트 QSS 적용
    try:
        ed = MarkdownEditor()
        qtbot.addWidget(ed)
        ed.set_font_point_size(26)
        assert ed.font().pointSize() == 26     # QSS 를 이기고 실제 적용
    finally:
        app.setStyleSheet(prev)                # 다른 테스트 오염 방지


def test_editor_ctrl_wheel_requests_zoom(qtbot):
    # Ctrl+휠 → zoom_requested(+1/-1). 일반 휠은 무시(스크롤).
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    steps: list[int] = []
    ed.zoom_requested.connect(steps.append)

    def wheel(dy: int, mod: Qt.KeyboardModifier):
        ev = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
            Qt.NoButton, mod, Qt.ScrollPhase.NoScrollPhase, False,
        )
        ed.wheelEvent(ev)

    wheel(120, Qt.ControlModifier)
    wheel(-120, Qt.ControlModifier)
    assert steps == [1, -1]
    wheel(120, Qt.NoModifier)        # Ctrl 없으면 줌 요청 없음
    assert steps == [1, -1]
