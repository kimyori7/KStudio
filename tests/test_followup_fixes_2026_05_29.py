"""2026-05-29 후속 픽스 검증 — 사이드카 기본 폴더 / 모드전환 md 누출 / 라이브러리 md 드롭.

build_main_window() 다수 = teardown 누적 세그폴트(환경 이슈) → 테스트 수를 적게 유지.
"""


def test_sidecar_default_is_under_video_output(qtbot, tmp_path):
    # 사이드카 기본 폴더 = [영상 저장 폴더]\sidecars (사용자 요청). custom 비었을 때.
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    win.app_settings.preferences.sidecar_dir = ""          # 기본(미지정)
    win.app_settings.general.output_dir = str(tmp_path / "vids")
    got = win._resolve_sidecar_dir()
    assert got == (tmp_path / "vids" / "sidecars")
    assert got.exists()                                    # 생성까지
    win.close()


def test_sidecar_custom_dir_respected(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    custom = tmp_path / "my_sidecars"
    win.app_settings.preferences.sidecar_dir = str(custom)
    assert win._resolve_sidecar_dir() == custom
    win.close()


def test_switch_away_from_document_hides_md(qtbot, tmp_path):
    # 회귀: 문서 모드에서 md 보다가 이미지 모드로 가면 md 본문이 화면에 남으면 안 됨.
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.markdown_tab import MarkdownTab
    from screen_recorder.ui.mode_controller import AppMode
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)                       # 문서 모드 + md 탭
    md = win.tab_area.currentWidget()
    assert isinstance(md, MarkdownTab) and md.isVisible()
    win.mode_controller.set_mode(AppMode.IMAGE)   # 이미지 모드로 전환 (이미지 탭 없음)
    assert not md.isVisible()               # md 본문이 숨겨져야 함
    win.close()


def test_library_drop_md_adds_document_entry(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "note.md"
    p.write_text("# n", encoding="utf-8")
    win._on_library_files_dropped([str(p)])   # 라이브러리에 드롭
    docs = win.library_model.entries(EntryKind.DOCUMENT)
    assert len(docs) == 1 and docs[0].path == p
    win.close()


def test_webengine_prewarm_guarded_by_disable_flag(qtbot):
    # 문서 첫 진입 창 깜빡임 fix = WebEngine pre-warm. gate(last_mode==document)를 통과시켜도
    # KSTUDIO_DISABLE_WEBENGINE(conftest 강제)가 우선이라 테스트는 Chromium 을 안 띄운다.
    # (시각적 깜빡임 제거 자체는 네이티브 창 효과라 사용자 확인 영역 — 여기선 가드+배선만.)
    from screen_recorder.app.main import build_main_window
    from screen_recorder.core.settings import AppSettings
    s = AppSettings()
    s.preferences.last_mode = "document"
    win = build_main_window(settings=s)
    qtbot.addWidget(win)
    assert win._webengine_prewarm is None
    win.close()
