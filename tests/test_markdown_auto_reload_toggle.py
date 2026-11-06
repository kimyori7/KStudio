"""문서 탭 «자동 갱신» 체크박스 (사용자 요청: 외부 변경 갱신 팝업이 귀찮다).

- 켜짐(기본): 지금 동작 그대로(팝업)
- 꺼짐: 팝업 없이 새로고침 버튼에 ● 표시, _disk_text 는 건드리지 않음
- 새로고침/디스크 복귀 → 표시 해제, 다시 켜면 밀린 변경을 팝업으로 처리
- 설정 기본값·저장·옛 파일 호환, 여러 탭 전파(되돌아오는 신호 없음)
"""
from pathlib import Path
from types import SimpleNamespace


def _make_tab(tmp_path: Path, text: str = "v1", **kw):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return MarkdownTab.from_file(p, **kw), p


def _stub_confirm(tab, answer: bool):
    calls = []

    def fake(dirty):
        calls.append(dirty)
        return answer

    tab._confirm_external_reload = fake
    return calls


def test_default_is_on(qtbot, tmp_path):
    tab, _ = _make_tab(tmp_path)
    qtbot.addWidget(tab)
    assert tab.auto_reload_cb.isChecked()
    assert tab.auto_reload_enabled()


def test_on_still_prompts(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path)
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=False)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert calls == [False]
    assert "●" not in tab.refresh_btn.text()


def test_off_no_popup_marks_refresh_and_keeps_disk_text(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    assert not tab.auto_reload_cb.isChecked()
    calls = _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert calls == []                              # 팝업 없음
    assert tab.refresh_btn.text() == "⟳ 새로고침 ●"
    assert "바뀐 내용" in tab.refresh_btn.toolTip()
    assert tab._disk_text == "v1"                   # 감지가 기준을 바꾸지 않음
    assert tab.editor.toPlainText() == "v1"         # 편집기도 그대로


def test_off_poll_marks_refresh(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    p.write_text("v2 longer", encoding="utf-8")
    tab._poll_disk()
    assert calls == []
    assert "●" in tab.refresh_btn.text()


def test_refresh_clears_marker(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    tab.refresh_btn.click()
    assert tab.editor.toPlainText() == "v2"
    assert tab.refresh_btn.text() == "⟳ 새로고침"
    assert "다시 불러오고" in tab.refresh_btn.toolTip()


def test_disk_reverting_clears_marker(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert "●" in tab.refresh_btn.text()
    p.write_text("v1", encoding="utf-8")            # 원래 내용으로 복귀
    tab._reload_check()
    assert "●" not in tab.refresh_btn.text()


def test_turning_on_processes_pending_with_popup(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert calls == []
    tab.auto_reload_cb.click()                      # 사용자가 켬
    assert tab.auto_reload_enabled()
    assert calls == [False]                         # 밀린 변경을 팝업으로
    assert tab.editor.toPlainText() == "v2"
    assert "●" not in tab.refresh_btn.text()


def test_user_toggle_emits_but_set_auto_reload_does_not(qtbot, tmp_path):
    tab, _ = _make_tab(tmp_path)
    qtbot.addWidget(tab)
    seen = []
    tab.auto_reload_changed.connect(seen.append)
    tab.auto_reload_cb.click()
    assert seen == [False]
    tab.set_auto_reload(True)                       # 코드 경로 — 신호 없음
    assert seen == [False]
    assert tab.auto_reload_cb.isChecked()


def test_settings_default_and_old_file_compat(tmp_path):
    from screen_recorder.core import settings as S
    assert S.AppSettings().markdown.auto_reload is True
    old = tmp_path / "settings.json"
    old.write_text('{"markdown": {"editor_font_pt": 13}}', encoding="utf-8")
    loaded = S.load(old)
    assert loaded.markdown.editor_font_pt == 13
    assert loaded.markdown.auto_reload is True


def test_settings_roundtrip(tmp_path):
    from screen_recorder.core import settings as S
    s = S.AppSettings()
    s.markdown.auto_reload = False
    path = tmp_path / "settings.json"
    S.save(s, path)
    assert S.load(path).markdown.auto_reload is False


def test_main_window_handler_saves_and_propagates(qtbot, tmp_path):
    """한 탭에서 바꾸면 설정 저장 + 다른 문서 탭 동기화, 신호는 되돌아오지 않는다."""
    from PySide6.QtWidgets import QTabWidget, QWidget
    from screen_recorder.core import settings as S
    from screen_recorder.ui.main_window import MainWindow
    from screen_recorder.ui.markdown_tab import MarkdownTab

    a = MarkdownTab.from_blank()
    b = MarkdownTab.from_blank()
    qtbot.addWidget(a)
    qtbot.addWidget(b)
    area = QTabWidget()
    qtbot.addWidget(area)
    for w in (a, QWidget(), b):
        area.addTab(w, "x")
    persisted = []
    fake = SimpleNamespace(
        app_settings=S.AppSettings(), tab_area=area,
        _persist_settings=lambda: persisted.append(1),
    )
    echoes = []
    b.auto_reload_changed.connect(echoes.append)
    a.auto_reload_changed.connect(
        lambda v: MainWindow._on_markdown_auto_reload_changed(fake, v))
    a.auto_reload_cb.click()
    assert fake.app_settings.markdown.auto_reload is False
    assert persisted == [1]
    assert not b.auto_reload_cb.isChecked()
    assert echoes == []
