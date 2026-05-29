"""Markdown 미리보기 — PreviewRenderer 인터페이스 뒤 QtWebEngine/Fallback.

set_content(md, doc_dir) → Python 으로 HTML 변환 → json 직렬화 주입.
template.html 은 그대로 로드하고(읽기 전용 번들 안전), pygments CSS 는 loadFinished
후 JS 로 <style> 주입한다 (런타임 파일 쓰기 없음).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .render import pygments_css, render_markdown_to_html

_log = logging.getLogger(__name__)


def _resolve_assets_dir() -> Path:
    """소스 실행과 PyInstaller 빌드 양쪽에서 assets 폴더를 찾는다 (app_icon 패턴)."""
    candidates = [Path(__file__).resolve().parent / "assets"]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(
            exe_dir / "_internal" / "screen_recorder" / "ui" / "markdown" / "assets"
        )
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(
                Path(meipass) / "screen_recorder" / "ui" / "markdown" / "assets"
            )
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


_ASSETS = _resolve_assets_dir()


def load_base_css() -> str:
    """assets/style.css 내용을 읽어 반환. 못 읽으면 빈 문자열 (degrade)."""
    try:
        return (_ASSETS / "style.css").read_text(encoding="utf-8")
    except OSError:
        _log.warning("style.css 읽기 실패 — 미리보기 스타일 없이 진행")
        return ""


def build_inject_script(html: str, doc_dir: str | None, revision: int) -> str:
    """window.updateMarkdown 호출 JS 문자열. 모든 인자 json 직렬화 (안전)."""
    return (
        f"window.updateMarkdown("
        f"{json.dumps(html)}, "
        f"{json.dumps(doc_dir)}, "
        f"{int(revision)});"
    )


def build_style_inject_script(css: str) -> str:
    """CSS 문자열을 <style> 로 head 에 주입하는 JS (json 직렬화로 안전).

    template.html 의 <link rel=stylesheet> 대신 이 경로로 style.css·pygments CSS 를
    주입한다 — file:// 문서에서 CSP style-src 'self' 가 상대 링크를 막는 케이스를
    우회하고(읽기 전용 번들에서도 안전), pygments 와 동일 메커니즘으로 일원화.
    """
    return (
        "var s=document.createElement('style');"
        f"s.textContent={json.dumps(css)};"
        "document.head.appendChild(s);"
    )


# 하위 호환 별칭 (기존 호출부/테스트 보호).
build_pygments_style_script = build_style_inject_script


class PreviewRenderer:
    """미리보기 백엔드 추상 인터페이스 — WebEngine / Fallback 교체 지점."""

    def widget(self) -> QWidget:
        raise NotImplementedError

    def show_html(self, html: str, doc_dir: str | None, revision: int) -> None:
        raise NotImplementedError

    # --- 스크롤 동기화 (나란히 모드) ---
    def set_scroll_ratio(self, ratio: float) -> None:
        """미리보기를 세로 비율 0..1 위치로 이동 (0=맨 위, 1=맨 아래). 기본 no-op."""

    def set_scroll_callback(self, cb) -> None:
        """사용자가 미리보기를 스크롤할 때 cb(ratio: float) 로 알림. 기본 no-op."""


class MarkdownPreview(QWidget):
    # 사용자가 미리보기를 스크롤할 때 비율(0..1) 방출 — MarkdownTab 이 에디터와 동기화.
    scrolled = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._revision = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._renderer = self._make_renderer()
        self._renderer.set_scroll_callback(self.scrolled.emit)
        layout.addWidget(self._renderer.widget())

    def set_scroll_ratio(self, ratio: float) -> None:
        self._renderer.set_scroll_ratio(ratio)

    def _make_renderer(self) -> PreviewRenderer:
        # 환경변수로 강제 Fallback — 테스트(Chromium teardown 불안정) 및 WebEngineProcess
        # 가 막힌 환경(회사 PC 보안 정책, headless CI)에서 명시적으로 degrade.
        if os.environ.get("KSTUDIO_DISABLE_WEBENGINE") == "1":
            return FallbackPreviewRenderer()
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

        outer = self

        class _LoggingPage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, message, line, source):
                # app.js 가 스크롤 위치를 "KSCROLL:<ratio>" 로 보냄 — 로그 대신 콜백.
                if isinstance(message, str) and message.startswith("KSCROLL:"):
                    if outer._scroll_cb is not None:
                        try:
                            outer._scroll_cb(float(message[len("KSCROLL:"):]))
                        except (ValueError, TypeError):
                            pass
                    return
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
        self._scroll_cb = None
        self._base_css = load_base_css()
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
        # 문서 스타일(style.css) → pygments 코드강조 순서로 주입한 뒤 대기 본문 적용.
        # <link> 대신 JS 주입 — file:// CSP 우회 + 읽기전용 번들 안전.
        if self._base_css:
            self._page.runJavaScript(build_style_inject_script(self._base_css))
        self._page.runJavaScript(build_style_inject_script(self._css))
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

    # --- 스크롤 동기화 ---
    def set_scroll_callback(self, cb) -> None:
        self._scroll_cb = cb

    def set_scroll_ratio(self, ratio: float) -> None:
        if not self._ready:
            return
        # app.js 의 window.setScrollRatio — 프로그램적 스크롤 시 echo(KSCROLL) 억제 포함.
        self._page.runJavaScript(f"window.setScrollRatio&&window.setScrollRatio({float(ratio)});")


class FallbackPreviewRenderer(PreviewRenderer):
    """QtWebEngine 불가 시 — QTextBrowser 로 degrade (제한적이지만 텍스트는 보임)."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import QTextBrowser

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        # WebEngine 와 달리 template.html 을 안 거치므로 style.css 가 자동 적용되지
        # 않는다 → 본문이 무스타일(앱 다크테마 위 검은 글씨 = "폰트 색상 없음")로 보임.
        # QTextDocument.setDefaultStyleSheet 가 Qt 리치텍스트 CSS 적용의 정석 경로 —
        # setHtml 전에 한 번 등록하면 이후 모든 본문에 body 색/코드강조가 입혀진다.
        self._browser.document().setDefaultStyleSheet(
            load_base_css() + "\n" + pygments_css()
        )
        self._scroll_cb = None
        self._browser.verticalScrollBar().valueChanged.connect(self._on_vsb_changed)

    def widget(self):
        return self._browser

    def show_html(self, html: str, doc_dir: str | None, revision: int) -> None:
        self._browser.setHtml(html)

    # --- 스크롤 동기화 ---
    def set_scroll_callback(self, cb) -> None:
        self._scroll_cb = cb

    def _on_vsb_changed(self, _value: int) -> None:
        if self._scroll_cb is None:
            return
        vsb = self._browser.verticalScrollBar()
        mx = vsb.maximum()
        self._scroll_cb(vsb.value() / mx if mx > 0 else 0.0)

    def set_scroll_ratio(self, ratio: float) -> None:
        vsb = self._browser.verticalScrollBar()
        vsb.setValue(round(ratio * vsb.maximum()))
