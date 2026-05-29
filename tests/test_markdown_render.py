def test_render_basic_html():
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("# Title\n\n**bold**")
    assert "<h1" in html and "Title" in html
    assert "<strong>bold</strong>" in html


def test_render_table():
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table" in html


def test_raw_html_disabled():
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("<script>alert(1)</script>")
    assert "<script>" not in html  # html=False 라 이스케이프됨


def test_fenced_code_highlighted():
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("```python\nx = 1\n```")
    assert 'class="' in html  # pygments span class 존재
    # markdown_it 가 <pre> 로 시작하는 highlight 반환을 재래핑하지 않아야 함
    assert "<pre><code><pre" not in html


def test_mermaid_passthrough():
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("```mermaid\ngraph TD;A-->B;\n```")
    assert 'class="mermaid"' in html and "graph TD" in html


def test_pygments_css_nonempty():
    from screen_recorder.ui.markdown.render import pygments_css
    css = pygments_css()
    assert ".highlight" in css and len(css) > 100
