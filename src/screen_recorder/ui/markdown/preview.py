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

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from .render import pygments_css, render_markdown_to_html

# 검색 매치 배경색 — search_bar 의 에디터 하이라이트와 동일 톤(amber).
_SEARCH_BG = QColor("#4a3c12")

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

    # --- 폰트 줌 ---
    def set_zoom(self, factor: float) -> None:
        """미리보기 전체 배율 설정 (1.0 = 기본). 기본 no-op."""

    def set_zoom_callback(self, cb) -> None:
        """사용자가 Ctrl+휠로 줌을 요청할 때 cb(step: int) 로 알림 (+1/-1). 기본 no-op."""

    # --- 검색 하이라이트 ---
    def highlight_search(self, query: str, case: bool = False) -> None:
        """렌더된 본문에서 query 와 일치하는 단어를 강조. 빈 문자열이면 해제. 기본 no-op.

        에디터는 raw 마크다운, 미리보기는 렌더 결과물이라 글자가 다를 수 있어(`**굵게**`
        의 `*` 등) 매치가 100% 일치하진 않는다 — 평문 단어 검색은 양쪽 모두 잡힌다.
        """

    # --- 선택 범위 동기화 (data-source-line 기반) ---
    def set_selection_callback(self, cb) -> None:
        """미리보기에서 선택이 바뀔 때 cb(start_line, end_line, text) 로 알림. 기본 no-op.
        (start_line < 0 이면 선택 해제.)"""

    def highlight_source_lines(self, start_line: int, end_line: int) -> None:
        """편집기 선택에 대응하는 원문 줄 범위를 미리보기에서 강조. 기본 no-op."""

    def clear_source_highlight(self) -> None:
        """미리보기의 줄범위 강조 해제. 기본 no-op."""

    def clear_native_selection(self) -> None:
        """미리보기의 네이티브(드래그) 텍스트 선택 해제. 기본 no-op."""


class MarkdownPreview(QWidget):
    # 사용자가 미리보기를 스크롤할 때 비율(0..1) 방출 — MarkdownTab 이 에디터와 동기화.
    scrolled = Signal(float)
    # 사용자가 Ctrl+휠로 줌을 요청할 때 단계(+1/-1) 방출 — MarkdownTab 이 적용 + 영속.
    zoom_requested = Signal(int)
    # 미리보기 선택 변경 — (start_line, end_line, text). start_line<0 = 해제.
    selection_changed = Signal(int, int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._revision = 0
        self._search_query = ""    # 재렌더 후 복원용 (편집 중 검색 유지)
        self._search_case = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._renderer = self._make_renderer()
        self._renderer.set_scroll_callback(self.scrolled.emit)
        self._renderer.set_zoom_callback(self.zoom_requested.emit)
        self._renderer.set_selection_callback(self.selection_changed.emit)
        layout.addWidget(self._renderer.widget())

    def highlight_source_lines(self, start_line: int, end_line: int) -> None:
        self._renderer.highlight_source_lines(start_line, end_line)

    def clear_source_highlight(self) -> None:
        self._renderer.clear_source_highlight()

    def clear_native_selection(self) -> None:
        self._renderer.clear_native_selection()

    def set_scroll_ratio(self, ratio: float) -> None:
        self._renderer.set_scroll_ratio(ratio)

    def set_zoom(self, factor: float) -> None:
        self._renderer.set_zoom(factor)

    def highlight_search(self, query: str, case: bool = False) -> None:
        self._search_query = query or ""
        self._search_case = bool(case)
        self._renderer.highlight_search(self._search_query, self._search_case)

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
        # 재렌더로 사라진 검색 하이라이트 복원 (검색하며 편집 중일 때).
        if self._search_query:
            self._renderer.highlight_search(self._search_query, self._search_case)


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
                # app.js 가 Ctrl+휠을 "KZOOM:<+1|-1>" 로 보냄 — MarkdownTab 이 적용/영속.
                if isinstance(message, str) and message.startswith("KZOOM:"):
                    if outer._zoom_cb is not None:
                        try:
                            outer._zoom_cb(int(message[len("KZOOM:"):]))
                        except (ValueError, TypeError):
                            pass
                    return
                # app.js 가 선택을 "KSEL:{json}" / "KSELCLEAR:" 로 보냄 — 줄범위 선택 동기화.
                if isinstance(message, str) and message.startswith("KSEL:"):
                    if outer._sel_cb is not None:
                        try:
                            d = json.loads(message[len("KSEL:"):])
                            outer._sel_cb(int(d["s"]), int(d["e"]), str(d.get("t", "")))
                        except (ValueError, TypeError, KeyError):
                            pass
                    return
                if isinstance(message, str) and message.startswith("KSELCLEAR:"):
                    if outer._sel_cb is not None:
                        outer._sel_cb(-1, -1, "")
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
        # 흰색 플래시 위생: style.css(body #1e1e1e)는 loadFinished 후 JS 로 주입되므로, 그
        # 전까지 WebEngine 기본 흰 배경이 잠깐 보인다("미리보기가 흰색이었다가" — 2026-05-29
        # 사용자 보고). 페이지 base 배경을 본문색과 같게 두면 콘텐츠/CSS 로드 전에도 다크다.
        # (창 전체 깜빡임의 HWND 재생성 fix 와는 별개의 위생 — preview 영역 한정.)
        self._page.setBackgroundColor(QColor("#1e1e1e"))
        self._ready = False
        self._pending: tuple[str, str | None, int] | None = None
        # 마지막으로 주입한 본문 — template 이 다시 로드되면(#content 빈 상태) 재주입해
        # 자가 복구한다 (렌더 프로세스 재시작 등. Reload 메뉴 자체는 제거했지만 방어).
        self._last: tuple[str, str | None, int] | None = None
        self._scroll_cb = None
        self._zoom_cb = None
        self._sel_cb = None
        self._zoom_factor = 1.0
        self._base_css = load_base_css()
        self._css = pygments_css()
        self._page.loadFinished.connect(self._on_load_finished)
        self._view.renderProcessTerminated.connect(
            lambda status, code: _log.error(
                "WebEngine render proc terminated: %s/%s", status, code
            )
        )
        self._page.setUrl(QUrl.fromLocalFile(str(_ASSETS / "template.html")))
        # 기본 Chromium 메뉴(Back/Forward/Reload/Save page/View source)는 주입형
        # 미리보기에서 전부 무의미하거나 유해(Reload=본문 소실) — 최소 메뉴로 교체.
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)

    def widget(self):
        return self._view

    def _show_context_menu(self, pos) -> None:
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWidgets import QMenu

        from .preview_menu import context_menu_items

        link = ""
        req = self._view.lastContextMenuRequest()
        if req is not None and req.linkUrl().isValid():
            link = req.linkUrl().toString()
        actions = {
            "copy": QWebEnginePage.WebAction.Copy,
            "copy_link": QWebEnginePage.WebAction.CopyLinkToClipboard,
            "select_all": QWebEnginePage.WebAction.SelectAll,
        }
        menu = QMenu(self._view)
        for key, label in context_menu_items(self._page.hasSelection(), link):
            menu.addAction(label, lambda k=key: self._page.triggerAction(actions[k]))
        menu.exec(self._view.mapToGlobal(pos))

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
        # 줌은 네비게이션(template 로드) 시 1.0 으로 리셋되는 Qt 동작이 있어, 로드 완료
        # 후 저장된 배율을 다시 적용해야 복원된 크기가 유지된다.
        self._view.setZoomFactor(self._zoom_factor)
        if self._pending is not None:
            html, dd, rev = self._pending
            self._pending = None
            self._inject(html, dd, rev)
        elif self._last is not None:
            # 재로드로 #content 가 비었을 때(app.js 의 latestRevision 도 리셋됨) 마지막
            # 본문을 재주입 — 없으면 다음 편집 전까지 빈 화면으로 남는다.
            self._inject(*self._last)

    def show_html(self, html: str, doc_dir: str | None, revision: int) -> None:
        self._last = (html, doc_dir, revision)
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

    # --- 폰트 줌 ---
    def set_zoom_callback(self, cb) -> None:
        self._zoom_cb = cb

    def set_zoom(self, factor: float) -> None:
        # Chromium 네이티브 줌 — 본문/코드/표 전체가 비율대로 확대. 로드 전이라도 값을
        # 저장해 두고 loadFinished 에서 재적용(네비게이션 리셋 방지).
        self._zoom_factor = float(factor)
        if self._ready:
            self._view.setZoomFactor(self._zoom_factor)

    # --- 검색 하이라이트 ---
    def highlight_search(self, query: str, case: bool = False) -> None:
        if not self._ready:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage
        # findText 는 렌더된 모든 매치를 강조하고 첫 매치로 스크롤. ""=해제.
        flags = QWebEnginePage.FindFlag(0)
        if case:
            flags |= QWebEnginePage.FindFlag.FindCaseSensitively
        self._page.findText(query or "", flags)

    # --- 선택 범위 동기화 ---
    def set_selection_callback(self, cb) -> None:
        self._sel_cb = cb

    def highlight_source_lines(self, start_line: int, end_line: int) -> None:
        if self._ready:
            self._page.runJavaScript(
                f"window.highlightSourceLines&&window.highlightSourceLines({int(start_line)},{int(end_line)});"
            )

    def clear_source_highlight(self) -> None:
        if self._ready:
            self._page.runJavaScript("window.clearSourceHighlight&&window.clearSourceHighlight();")

    def clear_native_selection(self) -> None:
        # 편집기에서 선택 해제(클릭) 시 미리보기의 드래그 선택도 함께 해제 (대칭 완성).
        if self._ready:
            self._page.runJavaScript("window.clearNativeSelection&&window.clearNativeSelection();")


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
        # 줌 기준 폰트 크기 — set_zoom(factor) 가 base*factor 로 위젯 폰트를 조정한다.
        # CSS body 에 font-size 가 없어 위젯 폰트가 본문 기본 크기를 결정.
        self._base_pt = max(1.0, self._browser.fontInfo().pointSizeF())
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

    # --- 폰트 줌 ---
    def set_zoom_callback(self, cb) -> None:
        # Fallback 은 Ctrl+휠 줌을 지원하지 않음 (버튼으로 조정). 콜백은 저장만.
        self._zoom_cb = cb

    def set_zoom(self, factor: float) -> None:
        # 전역 테마 QSS(QWidget{font})가 setFont() 를 덮어쓰므로 위젯별 stylesheet 로 지정
        # (편집기와 동일 — 2026-05-29 진단). base*factor 를 절대 pt 로.
        pt = max(1, round(self._base_pt * float(factor)))
        self._browser.setStyleSheet(f"QTextBrowser {{ font-size:{pt}pt; }}")
        self._browser.ensurePolished()

    # --- 검색 하이라이트 ---
    def highlight_search(self, query: str, case: bool = False) -> None:
        sels: list = []
        if query:
            doc = self._browser.document()
            flags = QTextDocument.FindFlag(0)
            if case:
                flags |= QTextDocument.FindFlag.FindCaseSensitively
            cur = QTextCursor(doc)
            while True:
                cur = doc.find(query, cur, flags)
                if cur.isNull():
                    break
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cur
                fmt = QTextCharFormat()
                fmt.setBackground(_SEARCH_BG)
                sel.format = fmt
                sels.append(sel)
        self._browser.setExtraSelections(sels)
