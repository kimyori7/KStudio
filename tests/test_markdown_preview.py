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


def test_template_has_no_dead_stylesheet_link():
    # style.css 는 JS 주입으로 일원화 — template 의 <link> 는 제거돼야 함.
    from screen_recorder.ui.markdown.preview import _ASSETS
    html = (_ASSETS / "template.html").read_text(encoding="utf-8")
    assert 'rel="stylesheet"' not in html
