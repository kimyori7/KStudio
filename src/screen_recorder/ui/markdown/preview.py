"""Markdown 미리보기 — PreviewRenderer 인터페이스 뒤 QtWebEngine/Fallback.

set_content(md, doc_dir) → Python 으로 HTML 변환 → json 직렬화 주입.
template.html 은 그대로 로드하고(읽기 전용 번들 안전), pygments CSS 는 loadFinished
후 JS 로 <style> 주입한다 (런타임 파일 쓰기 없음).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .render import pygments_css, render_markdown_to_html

_ASSETS = Path(__file__).parent / "assets"
_log = logging.getLogger(__name__)


def build_inject_script(html: str, doc_dir: str | None, revision: int) -> str:
    """window.updateMarkdown 호출 JS 문자열. 모든 인자 json 직렬화 (안전)."""
    return (
        f"window.updateMarkdown("
        f"{json.dumps(html)}, "
        f"{json.dumps(doc_dir)}, "
        f"{int(revision)});"
    )


def build_pygments_style_script(css: str) -> str:
    """pygments CSS 를 <style> 로 head 에 주입하는 JS (json 직렬화로 안전)."""
    return (
        "var s=document.createElement('style');"
        f"s.textContent={json.dumps(css)};"
        "document.head.appendChild(s);"
    )


class PreviewRenderer:
    """미리보기 백엔드 추상 인터페이스 — WebEngine / Fallback 교체 지점."""

    def widget(self) -> QWidget:
        raise NotImplementedError

    def show_html(self, html: str, doc_dir: str | None, revision: int) -> None:
        raise NotImplementedError


class MarkdownPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._revision = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._renderer = self._make_renderer()
        layout.addWidget(self._renderer.widget())

    def _make_renderer(self) -> PreviewRenderer:
        try:
            return WebEnginePreviewRenderer()
        except Exception as e:  # QtWebEngine 사용 불가 환경 → degrade
            _log.warning("WebEngine 미리보기 초기화 실패, fallback 사용: %s", e)
            return FallbackPreviewRenderer()

    def set_content(self, markdown_text: str, doc_dir: Path | None) -> None:
        self._revision += 1
        html = render_markdown_to_html(markdown_text)
        dd = str(doc_dir) if doc_dir is not None else None
        self._renderer.show_html(html, dd, self._revision)


class WebEnginePreviewRenderer(PreviewRenderer):
    def __init__(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        class _LoggingPage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, message, line, source):
                _log.info("[preview JS] %s (%s:%s)", message, source, line)

            def acceptNavigationRequest(self, url, nav_type, is_main_frame):
                # 링크 클릭은 시스템 브라우저로, 그 외(초기 로드 등)는 허용.
                if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                    QDesktopServices.openUrl(url)
                    return False
                return True

        self._profile = QWebEngineProfile()  # 이름 없는 기본 생성자 = off-the-record
        self._view = QWebEngineView()
        self._page = _LoggingPage(self._profile, self._view)
        self._view.setPage(self._page)
        self._ready = False
        self._pending: tuple[str, str | None, int] | None = None
        self._css = pygments_css()
        self._page.loadFinished.connect(self._on_load_finished)
        self._view.renderProcessTerminated.connect(
            lambda status, code: _log.error(
                "WebEngine render proc terminated: %s/%s", status, code
            )
        )
        self._page.setUrl(QUrl.fromLocalFile(str(_ASSETS / "template.html")))

    def widget(self):
        return self._view

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            _log.error("WebEngine template loadFinished(False)")
            return
        # pygments 스타일을 먼저 주입한 뒤 대기 중인 본문 적용.
        self._page.runJavaScript(build_pygments_style_script(self._css))
        self._ready = True
        if self._pending is not None:
            html, dd, rev = self._pending
            self._pending = None
            self._inject(html, dd, rev)

    def show_html(self, html: str, doc_dir: str | None, revision: int) -> None:
        if not self._ready:
            self._pending = (html, doc_dir, revision)  # loadFinished 전 큐잉
            return
        self._inject(html, doc_dir, revision)

    def _inject(self, html: str, doc_dir: str | None, revision: int) -> None:
        self._page.runJavaScript(build_inject_script(html, doc_dir, revision))


class FallbackPreviewRenderer(PreviewRenderer):
    """QtWebEngine 불가 시 — QTextBrowser 로 degrade (제한적이지만 텍스트는 보임)."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import QTextBrowser

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)

    def widget(self):
        return self._browser

    def show_html(self, html: str, doc_dir: str | None, revision: int) -> None:
        self._browser.setHtml(html)
