"""Markdown → HTML 변환 (Python markdown_it-py + pygments).

html=False 로 raw HTML 차단(보안). fenced code 는 pygments 로 구문강조하되,
언어가 mermaid 면 <pre class="mermaid"> 로 passthrough 해 클라이언트(Phase 2)가 렌더.

주의: markdown_it 는 highlight 콜백 반환이 "<pre" 로 시작하면 재래핑하지 않는다.
pygments 기본 출력은 <div class="highlight"><pre>... 라 재래핑되어 깨지므로,
nowrap=True 로 토큰 span 만 받아 <pre class="highlight"><code> 로 직접 감싼다.
"""
from __future__ import annotations

import html as _html
import re

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


# GitHub 스타일 슬러그: 소문자화 → 단어문자(유니코드 포함)·공백·하이픈 외 제거 → 공백을 -.
_SLUG_STRIP = re.compile(r"[^\w\s-]")
_SLUG_WS = re.compile(r"\s+")


def _heading_slug(text: str) -> str:
    s = _SLUG_STRIP.sub("", text.strip().lower())
    return _SLUG_WS.sub("-", s)


def _inject_heading_anchors(state) -> None:
    """heading 에 GitHub 스타일 ``id`` 를 부여 — 문서 내 앵커 링크([...](#섹션))의 목적지.

    id 가 없으면 앵커 링크가 갈 곳이 없어 "링크가 작동 안 함"으로 보인다. 슬러그는
    인라인 마크업(**굵게**, `코드`)을 벗긴 표시 텍스트 기준, 중복 heading 은 -1, -2 접미.
    """
    seen: dict[str, int] = {}
    tokens = state.tokens
    for i, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        inline = tokens[i + 1] if i + 1 < len(tokens) else None
        text = ""
        if inline is not None and inline.type == "inline" and inline.children:
            text = "".join(
                c.content for c in inline.children if c.type in ("text", "code_inline")
            )
        slug = _heading_slug(text)
        if not slug:
            continue  # 순수 기호 heading — 앵커로 쓸 이름이 없으니 건너뜀
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        token.attrSet("id", slug if n == 0 else f"{slug}-{n}")


_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": True, "highlight": _highlight})
    .enable("table")
    .enable("strikethrough")
)
# core 파이프라인 끝(블록·인라인 파싱 후)에 줄번호 주입 규칙 추가 — 이때 token.map 이 확정됨.
_md.core.ruler.push("source_line", _inject_source_lines)
_md.core.ruler.push("heading_anchors", _inject_heading_anchors)


def render_markdown_to_html(md_text: str) -> str:
    return _md.render(md_text)


def pygments_css() -> str:
    """template.html 에 inline 할 pygments 스타일시트 (다크 테마)."""
    return HtmlFormatter(style="monokai").get_style_defs(".highlight")
