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


def test_drop_md_on_library_opens_document_tab(qtbot, tmp_path):
    """라이브러리에 .md 드롭 → 등록+선택만이 아니라 그 문서 탭이 즉시 열려 보여야 한다.

    사용자 보고(2026-07-13): 항목이 선택된 것처럼 표시되는데 내용은 안 보임 — 문서
    모드는 탭이 없으면 빈 화면이라 하이라이트만으로는 아무것도 안 보인다.
    """
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    from screen_recorder.ui.markdown_tab import MarkdownTab
    from screen_recorder.ui.mode_controller import AppMode
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "dropped.md"
    p.write_text("# dropped", encoding="utf-8")
    win._on_library_files_dropped([str(p)])
    assert win.mode_controller.mode() is AppMode.DOCUMENT
    cur = win.tab_area.currentWidget()
    assert isinstance(cur, MarkdownTab)                    # 탭이 실제로 열림
    assert cur.editor.toPlainText() == "# dropped"         # 그 파일 내용이 보임
    assert cur.saved_path() == p
    docs = win.library_model.entries(EntryKind.DOCUMENT)
    assert len(docs) == 1                                  # 중복 등록 없음
    panel = win.library_panel
    assert panel.list_widget.currentItem() is panel._items_by_id[docs[0].id]
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


# NOTE: test_agent_document_edit_* 3건은 2026-07-13 제거 — 인앱 에이전트 기능이
# 기능 다이어트(b552408, 2026-06-18)로 통째 삭제되면서 _on_agent_document_edit 가
# 사라져 잔재로 실패하고 있었다. 기능 복원 시 git 이력에서 함께 복원할 것.
