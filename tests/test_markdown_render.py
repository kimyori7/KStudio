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


def test_render_injects_source_line():
    # 미리보기↔편집기 위치 매핑 토대 — 블록 태그에 data-source-line(0-based) 부여.
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("# 제목\n\n본문 문단")
    assert 'data-source-line="0"' in html   # 제목 = 줄 0
    assert 'data-source-line="2"' in html   # 본문 문단 = 줄 2 (빈 줄 사이)


def test_render_basic_html_still_intact_with_source_lines():
    # data-source-line 추가가 기존 태그/강조를 깨지 않아야 함.
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("# Title\n\n**bold**")
    assert "<h1" in html and "Title" in html
    assert "<strong>bold</strong>" in html


def test_pygments_css_nonempty():
    from screen_recorder.ui.markdown.render import pygments_css
    css = pygments_css()
    assert ".highlight" in css and len(css) > 100


def test_heading_anchor_ids():
    # 문서 내 앵커 링크([...](#섹션))의 목적지 — heading 에 GitHub 스타일 id 부여.
    # id 가 없으면 앵커 링크가 "작동 안 함"으로 보인다 (2026-07-13 사용자 보고).
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("# Hello World\n\n## 결정 이력\n")
    assert 'id="hello-world"' in html
    assert 'id="결정-이력"' in html


def test_heading_anchor_ids_dedup_and_formatting_stripped():
    from screen_recorder.ui.markdown.render import render_markdown_to_html
    html = render_markdown_to_html("# Same\n\n# Same\n\n## **Bold** `code` title\n")
    assert 'id="same"' in html and 'id="same-1"' in html  # 중복 heading 은 -1 접미
    assert 'id="bold-code-title"' in html                 # 인라인 마크업은 슬러그에서 제거
