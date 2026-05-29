"""문서 라이브러리 통합 + 에이전트 문서 편집 — MainWindow 통합 테스트.

NOTE: build_main_window() 인스턴스를 다수 만들면 오프스크린 Qt teardown 누적
세그폴트(환경 이슈, 메모리 문서화됨)가 ~13개 부근에서 발생 → 문서 통합 테스트는
이 파일로 분리해 단일 파일 인스턴스 수를 임계 아래로 유지한다.
"""


def test_library_remove_document_entry(qtbot, tmp_path):
    # 문서가 라이브러리에 노출되며 Del(제외) 핸들러를 새로 타게 됨 — 크래시 없이 제외 +
    # 사용자 .md 원본은 디스크에 보존돼야 함 (send2trash 아님).
    # NOTE: 이 핸들러는 sendPostedEvents(None, DeferredDelete) 로 *전역* deferred-delete 를
    # 플러시한다 → 다른 build_main_window 들이 누적된 뒤 호출하면 오프스크린 teardown
    # 세그폴트(환경 이슈)를 조기 유발. 그래서 priors 0 인 *맨 앞* 에 둔다.
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    eid = win.library_model.entries(EntryKind.DOCUMENT)[0].id
    win._on_library_remove(eid)
    assert win.library_model.entries(EntryKind.DOCUMENT) == []
    assert p.exists()
    win.close()


def test_open_md_registers_document_entry(qtbot, tmp_path):
    # 사용자 보고: .md 드롭 시 열리지만 라이브러리에 등록 안 됨 → DOCUMENT entry 등록돼야 함.
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    docs = win.library_model.entries(EntryKind.DOCUMENT)
    assert len(docs) == 1
    assert docs[0].path == p
    assert docs[0].display_name == "doc.md"
    win.close()


def test_reopen_md_no_duplicate_library_entry(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    win.tab_area._on_close_requested(win.tab_area.currentIndex())
    win._open_path(p)   # 재오픈 — 같은 path 면 라이브러리 항목 재사용
    assert len(win.library_model.entries(EntryKind.DOCUMENT)) == 1
    win.close()


def test_open_document_entry_from_library(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    from screen_recorder.ui.markdown_tab import MarkdownTab
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    eid = win.library_model.entries(EntryKind.DOCUMENT)[0].id
    win.tab_area._on_close_requested(win.tab_area.currentIndex())   # 탭 닫기
    win._open_entry(eid)                                            # 라이브러리에서 열기
    assert isinstance(win.tab_area.currentWidget(), MarkdownTab)
    win.close()


def test_blank_md_saved_promotes_to_library(qtbot, tmp_path, monkeypatch):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    from screen_recorder.ui import markdown_tab as M
    win = build_main_window()
    qtbot.addWidget(win)
    win._on_new_markdown()
    assert win.library_model.entries(EntryKind.DOCUMENT) == []   # blank 는 라이브러리 없음
    target = tmp_path / "new.md"
    monkeypatch.setattr(M.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    win._on_file_save()                                          # blank → Save As → 승격
    docs = win.library_model.entries(EntryKind.DOCUMENT)
    assert len(docs) == 1 and docs[0].path == target
    win.close()


def test_agent_document_edit_replace_is_undoable(qtbot, tmp_path):
    # 에이전트 replace → 즉시 적용 + Ctrl+Z(undo) 한 번에 원복돼야 함.
    from concurrent.futures import Future
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("original", encoding="utf-8")
    win._open_path(p)
    fut = Future()
    win._on_agent_document_edit({"op": "replace", "content": "rewritten"}, fut)
    assert fut.result()["ok"] is True
    md = win.tab_area.currentWidget()
    assert md.editor.toPlainText() == "rewritten"
    md.editor.undo()
    assert md.editor.toPlainText() == "original"   # 한 번의 undo 로 복원
    win.close()


def test_agent_document_find_replace(qtbot, tmp_path):
    from concurrent.futures import Future
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("foo bar foo", encoding="utf-8")
    win._open_path(p)
    fut = Future()
    win._on_agent_document_edit(
        {"op": "find_replace", "find": "foo", "replace": "X", "count": 0}, fut)
    res = fut.result()
    assert res["n_replaced"] == 2
    assert win.tab_area.currentWidget().editor.toPlainText() == "X bar X"
    win.close()


def test_agent_document_edit_no_active_doc(qtbot):
    # 활성 문서 아닐 때 편집 요청은 거부(ok=False)하되 future 는 반드시 해결돼야 함(hang 방지).
    from concurrent.futures import Future
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    fut = Future()
    win._on_agent_document_edit({"op": "replace", "content": "x"}, fut)
    assert fut.result()["ok"] is False
    win.close()
