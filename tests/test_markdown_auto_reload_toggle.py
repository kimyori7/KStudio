"""문서 «자동 갱신» (체크박스는 위쪽 도구줄) (사용자 요청: 외부 변경 갱신 팝업이 귀찮다).

- 켜짐(기본): 지금 동작 그대로(팝업)
- 꺼짐: 팝업 없이 탭이 pending 상태가 되고 신호를 냄, _disk_text 는 건드리지 않음
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
    assert tab.auto_reload_enabled()


def test_on_still_prompts(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path)
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=False)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert calls == [False]
    assert not tab.disk_changed_pending()


def test_off_no_popup_marks_refresh_and_keeps_disk_text(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    assert not tab.auto_reload_enabled()
    calls = _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert calls == []                              # 팝업 없음
    assert tab.disk_changed_pending()
    assert tab._disk_text == "v1"                   # 감지가 기준을 바꾸지 않음
    assert tab.editor.toPlainText() == "v1"         # 편집기도 그대로


def test_off_poll_marks_refresh(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    p.write_text("v2 longer", encoding="utf-8")
    tab._poll_disk()
    assert calls == []
    assert tab.disk_changed_pending()


def test_refresh_clears_marker(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    tab.refresh_from_disk()
    assert tab.editor.toPlainText() == "v2"
    assert not tab.disk_changed_pending()


def test_disk_reverting_clears_marker(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert tab.disk_changed_pending()
    p.write_text("v1", encoding="utf-8")            # 원래 내용으로 복귀
    tab._reload_check()
    assert not tab.disk_changed_pending()


def test_turning_on_processes_pending_with_popup(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    assert calls == []
    tab.set_auto_reload(True)                       # 켬(도구줄 체크 → main_window 전파)
    assert tab.auto_reload_enabled()
    assert calls == [False]                         # 밀린 변경을 팝업으로
    assert tab.editor.toPlainText() == "v2"
    assert not tab.disk_changed_pending()


def test_pending_signal_emits_only_on_change(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, auto_reload=False)
    qtbot.addWidget(tab)
    seen = []
    tab.disk_changed_pending_changed.connect(seen.append)
    _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    tab._reload_check()                             # 같은 상태 — 재발화 없음
    assert seen == [True]
    tab.refresh_from_disk()
    assert seen == [True, False]


def test_set_auto_reload_updates_state(qtbot, tmp_path):
    tab, _ = _make_tab(tmp_path)
    qtbot.addWidget(tab)
    tab.set_auto_reload(False)
    assert not tab.auto_reload_enabled()
    tab.set_auto_reload(True)
    assert tab.auto_reload_enabled()


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


def _fake_window(qtbot, tabs):
    from PySide6.QtWidgets import QTabWidget
    from screen_recorder.core import settings as S
    from screen_recorder.ui.global_toolbar import GlobalToolbar
    area = QTabWidget()
    qtbot.addWidget(area)
    for w in tabs:
        area.addTab(w, "x")   # area 가 소유 — qtbot 에 따로 등록하지 않는다
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    persisted = []
    fake = SimpleNamespace(
        app_settings=S.AppSettings(), tab_area=area, global_toolbar=tb,
        _persist_settings=lambda: persisted.append(1),
    )
    return fake, area, tb, persisted


def test_main_window_handler_saves_and_propagates(qtbot):
    """도구줄 체크 → 설정 저장 + 열린 모든 문서 탭에 적용."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from screen_recorder.ui.main_window import MainWindow
    from screen_recorder.ui.markdown_tab import MarkdownTab
    from screen_recorder.ui.mode_controller import AppMode

    a, b = MarkdownTab.from_blank(), MarkdownTab.from_blank()
    fake, _, tb, persisted = _fake_window(qtbot, [a, QWidget(), b])
    tb.doc_auto_reload_changed.connect(
        lambda v: MainWindow._on_markdown_auto_reload_changed(fake, v))
    tb.set_mode(AppMode.DOCUMENT)
    tb.set_doc_auto_reload(True)   # 설정 기본값(켬)과 맞춘 시작 상태
    tb.show()
    qtbot.mouseClick(tb.doc_auto_reload_chk, Qt.LeftButton)
    assert fake.app_settings.markdown.auto_reload is False
    assert persisted == [1]
    assert not a.auto_reload_enabled()
    assert not b.auto_reload_enabled()


def test_toolbar_pending_follows_visible_tab_only(qtbot):
    """● 는 현재 보이는 문서 탭 상태를 따른다 — 다른 탭 신호는 무시, 탭 전환 때 갱신."""
    from PySide6.QtWidgets import QWidget
    from screen_recorder.ui.main_window import MainWindow
    from screen_recorder.ui.markdown_tab import MarkdownTab

    a, b = MarkdownTab.from_blank(), MarkdownTab.from_blank()
    other = QWidget()
    fake, area, tb, _ = _fake_window(qtbot, [a, b, other])
    for t in (a, b):
        t.disk_changed_pending_changed.connect(
            lambda p, t=t: MainWindow._on_markdown_pending_changed(fake, t, p))
    area.currentChanged.connect(lambda _i: MainWindow._sync_doc_toolbar(fake))

    area.setCurrentIndex(0)
    MainWindow._sync_doc_toolbar(fake)
    assert tb.doc_refresh_btn.isEnabled()
    b._set_disk_changed_pending(True)               # 보이지 않는 탭
    assert "●" not in tb.doc_refresh_btn.text()
    a._set_disk_changed_pending(True)               # 보이는 탭
    assert "●" in tb.doc_refresh_btn.text()
    area.setCurrentIndex(1)                         # b 는 pending
    assert "●" in tb.doc_refresh_btn.text()
    a._set_disk_changed_pending(False)
    area.setCurrentIndex(0)                         # a 는 깨끗
    assert "●" not in tb.doc_refresh_btn.text()
    area.setCurrentIndex(2)                         # 문서 탭 아님
    assert not tb.doc_refresh_btn.isEnabled()


def test_toolbar_refresh_refreshes_current_tab(qtbot, tmp_path):
    from screen_recorder.ui.main_window import MainWindow
    tab, p = _make_tab(tmp_path)
    fake, _, _, _ = _fake_window(qtbot, [tab])
    _stub_confirm(tab, answer=True)
    p.write_text("v2", encoding="utf-8")
    MainWindow._on_doc_refresh_clicked(fake)
    assert tab.editor.toPlainText() == "v2"
