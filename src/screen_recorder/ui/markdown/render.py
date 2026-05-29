"""Markdown → HTML 변환 (Python markdown_it-py + pygments).

html=False 로 raw HTML 차단(보안). fenced code 는 pygments 로 구문강조하되,
언어가 mermaid 면 <pre class="mermaid"> 로 passthrough 해 클라이언트(Phase 2)가 렌더.

주의: markdown_it 는 highlight 콜백 반환이 "<pre" 로 시작하면 재래핑하지 않는다.
pygments 기본 출력은 <div class="highlight"><pre>... 라 재래핑되어 깨지므로,
nowrap=True 로 토큰 span 만 받아 <pre class="highlight"><code> 로 직접 감싼다.
"""
from __future__ import annotations

import html as _html

from markdown_it import MarkdownIt
from pygments import highlight as _pyg_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound


def _highlight(code: str, lang: str, _attrs) -> str:
    if lang and lang.lower() == "mermaid":
        return f'<pre class="mermaid">{_html.escape(code)}</pre>'
    lexer = None
    if lang:
        try:
            lexer = get_lexer_by_name(lang)
        except ClassNotFound:
            lexer = None
    if lexer is None:
        return f'<pre class="highlight"><code>{_html.escape(code)}</code></pre>'
    highlighted = _pyg_highlight(code, lexer, HtmlFormatter(nowrap=True))
    return f'<pre class="highlight"><code>{highlighted}</code></pre>'


def _inject_source_lines(state) -> None:
    """블록 토큰에 ``data-source-line``(0-based 시작 줄)을 부여 — 미리보기↔편집기 위치 매핑.

    VS Code/Joplin 과 동일한 기법: markdown-it 의 ``token.map`` 을 렌더 태그 속성으로
    노출해, 미리보기 DOM 요소 ↔ 에디터 줄 번호를 양방향으로 매핑할 수 있게 한다
    (선택 범위 동기화·스크롤 동기화의 토대). close 토큰엔 부여하지 않는다.
    """
    for token in state.tokens:
        if token.map is not None and token.nesting != -1:
            token.attrSet("data-source-line", str(token.map[0]))


_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": True, "highlight": _highlight})
    .enable("table")
    .enable("strikethrough")
)
# core 파이프라인 끝(블록·인라인 파싱 후)에 줄번호 주입 규칙 추가 — 이때 token.map 이 확정됨.
_md.core.ruler.push("source_line", _inject_source_lines)


def render_markdown_to_html(md_text: str) -> str:
    return _md.render(md_text)


def pygments_css() -> str:
    """template.html 에 inline 할 pygments 스타일시트 (다크 테마)."""
    return HtmlFormatter(style="monokai").get_style_defs(".highlight")
