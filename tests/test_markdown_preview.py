import json


def test_build_inject_script_is_json_serialized():
    from screen_recorder.ui.markdown.preview import build_inject_script
    # 따옴표/백슬래시/유니코드/</script> 가 안전하게 직렬화돼야 함
    html = '<p>"quote" \\ </script> 한글</p>'
    script = build_inject_script(html, r"C:\docs", 7)
    assert script.startswith("window.updateMarkdown(")
    inner = script[len("window.updateMarkdown("):].rstrip(");")
    assert inner.endswith(", 7")              # revision 인자
    assert json.dumps(html) in script         # html json 직렬화 (따옴표/백슬래시/유니코드 안전)
    assert json.dumps(r"C:\docs") in script   # docDir json 직렬화
    # runJavaScript 경로라 HTML <script> 파싱을 안 거침 → 본문은 JS 문자열 리터럴로만 해석됨.
    # json.dumps 가 큰따옴표/백슬래시/제어문자/유니코드를 이스케이프하므로 문자열 탈출 불가.
    assert '"quote"' not in script             # raw 큰따옴표가 노출되면 안 됨 (\\" 로 escape)


def test_build_inject_script_none_docdir():
    from screen_recorder.ui.markdown.preview import build_inject_script
    script = build_inject_script("<p>x</p>", None, 1)
    assert "null" in script  # json.dumps(None) == "null"


def test_set_content_increments_revision(qtbot):
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    r0 = pv._revision
    pv.set_content("# a", None)
    pv.set_content("# b", None)
    assert pv._revision == r0 + 2


def test_disable_webengine_env_uses_fallback(qtbot, monkeypatch):
    # KSTUDIO_DISABLE_WEBENGINE=1 → Chromium 안 띄우고 QTextBrowser fallback 사용.
    monkeypatch.setenv("KSTUDIO_DISABLE_WEBENGINE", "1")
    from screen_recorder.ui.markdown.preview import (
        FallbackPreviewRenderer, MarkdownPreview,
    )
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    assert isinstance(pv._renderer, FallbackPreviewRenderer)
    # fallback 도 set_content 가 예외 없이 동작해야 함.
    pv.set_content("# 제목\n**bold**", None)


def test_fallback_applies_base_style(qtbot):
    # 회귀: Fallback(QTextBrowser)도 style.css 를 입혀야 한다 — 무스타일이면 다크테마
    # 위 검은 글씨로 "폰트 색상 없음" 증상. defaultStyleSheet 로 body 색이 적용돼야 함.
    from screen_recorder.ui.markdown.preview import FallbackPreviewRenderer
    r = FallbackPreviewRenderer()
    qtbot.addWidget(r.widget())
    r.show_html("<p>본문</p>", None, 1)
    css = r.widget().document().defaultStyleSheet()
    assert "body" in css and "#d4d4d4" in css.lower()


def test_preview_emits_scrolled_ratio(qtbot):
    # Fallback 미리보기를 사용자가 스크롤하면 scrolled(ratio) 방출 (에디터 동기화용).
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    got = []
    pv.scrolled.connect(got.append)
    vsb = pv._renderer.widget().verticalScrollBar()
    vsb.setRange(0, 50)
    vsb.setValue(25)
    assert got and abs(got[-1] - 0.5) < 1e-6


def test_set_scroll_ratio_moves_fallback(qtbot):
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    vsb = pv._renderer.widget().verticalScrollBar()
    vsb.setRange(0, 80)
    pv.set_scroll_ratio(0.25)
    assert vsb.value() == 20


def test_base_css_loads_nonempty():
    from screen_recorder.ui.markdown.preview import load_base_css
    css = load_base_css()
    assert "body" in css and "color" in css


def test_base_css_has_webkit_scrollbar_pill():
    # 미리보기(Chromium)는 Qt QSS 가 안 닿아 style.css 의 ::-webkit-scrollbar 로 앱 pill 을
    # 맞춘다. 이 규칙이 주입되는 base CSS 에 실려야(loadFinished 에서 inject) 미리보기
    # 스크롤바도 에디터/라이브러리와 같은 모양이 된다.
    from screen_recorder.ui.markdown.preview import load_base_css
    css = load_base_css()
    assert "::-webkit-scrollbar" in css and "::-webkit-scrollbar-thumb" in css


def test_template_has_no_dead_stylesheet_link():
    # style.css 는 JS 주입으로 일원화 — template 의 <link> 는 제거돼야 함.
    from screen_recorder.ui.markdown.preview import _ASSETS
    html = (_ASSETS / "template.html").read_text(encoding="utf-8")
    assert 'rel="stylesheet"' not in html


# --- 하이퍼링크 (2026-07-13 사용자 보고: 링크가 작동 안 함) ---

def test_appjs_links_not_blanket_blocked():
    # 회귀: 모든 a[href] 클릭에 무조건 preventDefault 하면 네비게이션이 시작조차
    # 안 돼서, 링크를 시스템 브라우저로 보내는 Python acceptNavigationRequest 가
    # 영영 호출되지 않는다 — 두 메커니즘이 서로를 상쇄해 링크가 전부 죽는다.
    from screen_recorder.ui.markdown.preview import _ASSETS
    js = (_ASSETS / "app.js").read_text(encoding="utf-8")
    assert "if (a) e.preventDefault();" not in js
    # 문서 내 앵커(#섹션)는 페이지 URL 변경 없이 스크롤로 처리해야 한다.
    assert "scrollIntoView" in js


def test_appjs_rewrites_relative_link_href():
    # 상대 경로 링크(./other.md 등)는 img[src] 처럼 doc_dir 기준 file:// 로
    # 재작성해야 클릭 시 실제 파일을 가리킨다 (기본은 template.html 기준 = 오답).
    from screen_recorder.ui.markdown.preview import _ASSETS
    js = (_ASSETS / "app.js").read_text(encoding="utf-8")
    assert 'querySelectorAll("a[href]")' in js


# --- Reload 자가 복구 (2026-07-13 사용자 보고: Reload 하면 미리보기가 사라짐) ---

def _bare_webengine_renderer(run_js):
    # Chromium 없이 로직만 검증 — __init__ 을 우회하고 필요한 속성만 스텁.
    from types import SimpleNamespace
    from screen_recorder.ui.markdown.preview import WebEnginePreviewRenderer
    r = object.__new__(WebEnginePreviewRenderer)
    r._page = SimpleNamespace(runJavaScript=run_js)
    r._view = SimpleNamespace(setZoomFactor=lambda f: None)
    r._base_css = ""
    r._css = ""
    r._zoom_factor = 1.0
    r._ready = False
    r._pending = None
    r._last = None
    return r


def test_webengine_show_html_caches_last_content():
    r = _bare_webengine_renderer(lambda s: None)
    r._ready = True
    r.show_html("<p>x</p>", "C:/d", 1)
    assert r._last == ("<p>x</p>", "C:/d", 1)


def test_webengine_load_finished_reinjects_last_content():
    # template.html 이 다시 로드되면(#content 빈 상태) 마지막 본문을 재주입해야
    # 미리보기가 빈 화면으로 남지 않는다 — 렌더 프로세스 재시작 등에도 자가 복구.
    calls = []
    r = _bare_webengine_renderer(calls.append)
    # 마커는 ASCII — build_inject_script 의 json.dumps 가 한글을 \uXXXX 로 이스케이프함.
    r._last = ("<p>RECOVERED</p>", None, 3)
    r._on_load_finished(True)
    assert any("updateMarkdown" in c and "RECOVERED" in c for c in calls)


# --- 우클릭 메뉴 (2026-07-13 사용자 보고: 브라우저 기본 메뉴가 노출됨) ---

def test_preview_context_menu_spec():
    # 기본 Chromium 메뉴(Back/Forward/Reload/Save page/View source)는 주입형
    # 미리보기에서 전부 무의미하거나 유해(Reload=본문 소실) — 최소 메뉴로 교체.
    from screen_recorder.ui.markdown.preview_menu import context_menu_items
    # 선택도 링크도 없으면 '모두 선택'만.
    assert context_menu_items(False, "") == [("select_all", "모두 선택")]
    # 텍스트 선택 중이면 '복사'가 맨 앞.
    assert context_menu_items(True, "")[0] == ("copy", "복사")
    # 링크 위에서 열면 '링크 주소 복사' 포함.
    keys = [k for k, _ in context_menu_items(False, "https://example.com")]
    assert "copy_link" in keys and "select_all" in keys
