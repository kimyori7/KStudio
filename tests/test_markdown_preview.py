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
