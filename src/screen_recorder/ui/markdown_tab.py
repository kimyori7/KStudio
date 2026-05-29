"""MarkdownTab — 코드 에디터 + 실시간 미리보기 + 3뷰 전환 (EditTab 계약 미러)."""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from .icons import load_icon
from .markdown.editor import MarkdownEditor
from .markdown.highlighter import MarkdownHighlighter
from .markdown.preview import MarkdownPreview
from .markdown.search_bar import MarkdownSearchBar

_log = logging.getLogger(__name__)


class SaveResult(Enum):
    """저장 결과 — 호출자가 취소(조용히)와 실제 쓰기 실패(경고)를 구분하기 위함."""
    SAVED = "saved"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ViewMode(Enum):
    EDITOR = "editor"
    PREVIEW = "preview"
    SPLIT = "split"


def _read_text_with_fallback(path: Path) -> str:
    """UTF-8 우선 → utf-8-sig(BOM) → cp949 폴백. 모두 실패하면 replace 로 강제 디코드."""
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


class MarkdownTab(QWidget):
    save_state_changed = Signal()
    # 폰트 크기 변경 알림 — (편집기 pt, 미리보기 zoom). main_window 가 받아 영속(디바운스).
    font_settings_changed = Signal(int, float)

    # 폰트 크기 한계/기본값 — 편집기는 포인트, 미리보기는 배율.
    EDITOR_MIN_PT = 8
    EDITOR_MAX_PT = 32
    EDITOR_DEFAULT_PT = 11
    PREVIEW_MIN_ZOOM = 0.5
    PREVIEW_MAX_ZOOM = 3.0
    PREVIEW_DEFAULT_ZOOM = 1.0
    PREVIEW_ZOOM_STEP = 0.1

    def __init__(
        self, *, source_label: str = "new",
        editor_font_pt: int = EDITOR_DEFAULT_PT,
        preview_zoom: float = PREVIEW_DEFAULT_ZOOM,
    ) -> None:
        super().__init__()
        self._source_label = source_label
        self._saved_path: Path | None = None

        # 폰트 크기 상태 — 단일 출처. 버튼/Ctrl+휠 모두 여기를 거쳐 적용 + 영속.
        self._editor_pt = max(
            self.EDITOR_MIN_PT, min(self.EDITOR_MAX_PT, int(editor_font_pt))
        )
        self._preview_zoom = max(
            self.PREVIEW_MIN_ZOOM, min(self.PREVIEW_MAX_ZOOM, float(preview_zoom))
        )

        self._dirty = False
        self.editor = MarkdownEditor()
        self._highlighter = MarkdownHighlighter(self.editor.document())
        self.preview = MarkdownPreview()

        # 뷰모드 토글 버튼
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        self._btn_group = QButtonGroup(self)
        self._buttons: dict[ViewMode, QPushButton] = {}
        for mode, label in ((ViewMode.EDITOR, "✎ 편집"),
                            (ViewMode.PREVIEW, "👁 미리보기"),
                            (ViewMode.SPLIT, "⊟ 나란히")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, m=mode: self.set_view_mode(m))
            self._btn_group.addButton(btn)
            self._buttons[mode] = btn
            bar.addWidget(btn)
        bar.addStretch(1)

        # 폰트 크기 컨트롤 — 편집/미리보기 각각 A−/A+ + 공용 '기본' 리셋 (우측 정렬).
        # 편집기 그룹은 편집·나란히, 미리보기 그룹은 미리보기·나란히 모드에서 표시.
        self._editor_font_group = self._make_font_group(
            "편집", lambda: self._bump_editor(-1), lambda: self._bump_editor(+1)
        )
        self._preview_font_group = self._make_font_group(
            "미리보기", lambda: self._bump_preview(-1), lambda: self._bump_preview(+1)
        )
        reset_btn = QPushButton(" 기본")
        reset_btn.setIcon(load_icon("rotate-ccw", size=15))
        reset_btn.setIconSize(QSize(15, 15))
        reset_btn.setFocusPolicy(Qt.NoFocus)
        reset_btn.setToolTip("글자 크기를 기본값으로 되돌리기")
        reset_btn.clicked.connect(self._reset_fonts)
        bar.addWidget(self._editor_font_group)
        bar.addWidget(self._preview_font_group)
        bar.addWidget(reset_btn)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self.editor)
        self._splitter.addWidget(self.preview)
        self._splitter.setSizes([500, 500])

        # 찾기/바꾸기 바 — 에디터 기준 검색, 미리보기는 위치만 따라감(on_navigate).
        # Ctrl+F=찾기 / Ctrl+H=찾기+바꾸기. WidgetWithChildrenShortcut 라 이 탭에 포커스가
        # 있을 때만 발화(전역 단축키가 다른 모드/위젯의 키를 가로채는 문제 회피).
        self._search_bar = MarkdownSearchBar(
            self.editor,
            on_navigate=self._sync_preview_to_editor,
            on_query_changed=self._on_search_query,
        )
        self._search_bar.hide()
        self._search_shortcuts: list[QShortcut] = []
        for seq, slot in (
            (QKeySequence.StandardKey.Find, self._search_bar.open_find),
            (QKeySequence.StandardKey.Replace, self._search_bar.open_replace),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self._search_shortcuts.append(sc)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self._search_bar)
        layout.addWidget(self._splitter, stretch=1)

        # 편집 → 미리보기 갱신(디바운스) + dirty 추적(즉시).
        # QPlainTextEdit.setPlainText 는 modified 플래그를 올리지 않으므로(프로그램적 치환),
        # document().isModified() 대신 textChanged 기반 명시 _dirty 로 추적한다.
        self.editor.content_changed.connect(self._refresh_preview)
        self.editor.textChanged.connect(self._on_text_changed)

        # 스크롤 동기화 (나란히 모드) — 한쪽을 움직이면 같은 세로 비율로 다른 쪽도 이동.
        # 폰트 크기/렌더 높이가 달라도 0..1 비율 기준이라 위/아래 끝이 맞는다.
        # _syncing 플래그로 에디터→미리보기→에디터 무한 루프 차단.
        self._syncing = False
        self.editor.verticalScrollBar().valueChanged.connect(self._on_editor_scrolled)
        self.preview.scrolled.connect(self._on_preview_scrolled)

        # Ctrl+휠 줌 — 에디터/미리보기 둘 다 단계 신호를 보내면 여기서 적용 + 영속.
        self.editor.zoom_requested.connect(self._bump_editor)
        self.preview.zoom_requested.connect(self._bump_preview)

        # 선택 범위 동기화 (data-source-line 매핑) — 편집기↔미리보기 양방향.
        # _sel_syncing 으로 편집기→미리보기→편집기 루프 차단. _last_preview_sel 은
        # 미리보기 모드에서 선택 후 편집 모드로 전환 시 그 선택을 유지하기 위한 저장.
        self._sel_syncing = False
        self._last_preview_sel: tuple[int, int, str] | None = None
        self.editor.selectionChanged.connect(self._on_editor_selection)
        self.preview.selection_changed.connect(self._on_preview_selection)

        # 저장된 초기 크기 적용 (영속 emit 없이 — 생성 시 디스크 쓰기 방지).
        self.editor.set_font_point_size(self._editor_pt)
        self.preview.set_zoom(self._preview_zoom)

        self.set_view_mode(ViewMode.SPLIT)
        self._refresh_preview(self.editor.toPlainText())

    # --- 팩토리 ---
    @classmethod
    def from_blank(
        cls, *, editor_font_pt: int = EDITOR_DEFAULT_PT,
        preview_zoom: float = PREVIEW_DEFAULT_ZOOM,
    ) -> "MarkdownTab":
        # 미저장 blank → saved_path None 이라 needs_save() 가 항상 True.
        return cls(source_label="new",
                   editor_font_pt=editor_font_pt, preview_zoom=preview_zoom)

    @classmethod
    def from_file(
        cls, path: Path, *, editor_font_pt: int = EDITOR_DEFAULT_PT,
        preview_zoom: float = PREVIEW_DEFAULT_ZOOM,
    ) -> "MarkdownTab":
        path = Path(path)
        text = _read_text_with_fallback(path)
        tab = cls(source_label="opened",
                  editor_font_pt=editor_font_pt, preview_zoom=preview_zoom)
        tab.editor.setPlainText(text)   # textChanged → _dirty True 가 되므로
        tab._saved_path = path
        tab._dirty = False              # 막 로드한 파일은 깨끗한 상태
        tab.save_state_changed.emit()
        tab._refresh_preview(text)
        return tab

    # --- EditTab 계약 ---
    def source_label(self) -> str:
        return self._source_label

    def saved_path(self) -> Path | None:
        return self._saved_path

    def needs_save(self) -> bool:
        return (self._saved_path is None) or self._dirty

    def mark_saved(self, path: Path) -> None:
        self._saved_path = path
        self._dirty = False
        self.save_state_changed.emit()

    def _on_text_changed(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.save_state_changed.emit()

    # --- 저장 ---
    def save(self) -> SaveResult:
        if self._saved_path is None:
            return self.save_as()
        return SaveResult.SAVED if self._write_to(self._saved_path) else SaveResult.FAILED

    def save_as(self, path: Path | None = None) -> SaveResult:
        if path is None:
            fn, _ = QFileDialog.getSaveFileName(
                self, "Markdown 저장", "", "Markdown (*.md *.markdown)"
            )
            if not fn:
                return SaveResult.CANCELLED   # 사용자 취소 — 쓰기 시도 안 함
            path = Path(fn)
        return SaveResult.SAVED if self._write_to(Path(path)) else SaveResult.FAILED

    def _write_to(self, path: Path) -> bool:
        """UTF-8 로 기록. 성공 시에만 _saved_path/dirty 갱신 (쓰기 실패 시 상태 불변)."""
        try:
            path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as e:
            _log.error("Markdown 저장 실패: %s", e)
            return False
        self.mark_saved(path)
        return True

    # --- 뷰모드 ---
    def set_view_mode(self, mode: ViewMode) -> None:
        self._buttons[mode].setChecked(True)
        edit_on = mode in (ViewMode.EDITOR, ViewMode.SPLIT)
        preview_on = mode in (ViewMode.PREVIEW, ViewMode.SPLIT)
        self.editor.setVisible(edit_on)
        self.preview.setVisible(preview_on)
        # 보이는 창의 폰트 컨트롤만 노출 — 나란히면 둘 다(각각 조절).
        self._editor_font_group.setVisible(edit_on)
        self._preview_font_group.setVisible(preview_on)
        # 미리보기에서 선택한 뒤 편집 모드로 오면 그 범위를 편집기에 한 번 선택 유지.
        # consume-once: 적용 후 비운다 — 안 그러면 이후 편집/모드전환마다 옛 선택이
        # 재적용돼 커서·포커스를 빼앗는다(테스트가 못 잡는 회귀, advisor 지적 2026-05-29).
        if mode is ViewMode.EDITOR and self._last_preview_sel is not None:
            rng = self._editor_range_for_lines(*self._last_preview_sel)
            self._last_preview_sel = None
            if rng is not None:
                self._apply_editor_selection(*rng)
                self.editor.setFocus()

    # --- 폰트 크기 ---
    def _make_font_group(self, label: str, on_minus, on_plus) -> QWidget:
        """'<라벨> [A−][A+]' 묶음 위젯 — SVG 아이콘 버튼.

        텍스트 'A−/A+' 는 전역 QPushButton padding(6px 14px)에 눌려 좁은 버튼에서
        글자가 잘려 안 보였다(사용자 보고 2026-05-29) → SVG 아이콘 + padding 축소.
        버튼은 포커스 안 받음(전역 단축키 영향 회피).
        """
        grp = QWidget()
        lay = QHBoxLayout(grp)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        cap = QLabel(label)
        cap.setStyleSheet("color:#9a9a9a;")
        lay.addWidget(cap)
        for icon_name, slot, tip in (
            ("font-decrease", on_minus, f"{label} 글자 줄이기"),
            ("font-increase", on_plus, f"{label} 글자 키우기"),
        ):
            btn = QPushButton()
            btn.setIcon(load_icon(icon_name, size=18))
            btn.setIconSize(QSize(18, 18))
            # 전역 padding(6px 14px)이면 아이콘 버튼이 과도하게 넓어짐 → 축소(아이콘 전용).
            btn.setStyleSheet("QPushButton { padding: 3px 7px; min-height: 0; }")
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
        return grp

    def _emit_font_settings(self) -> None:
        self.font_settings_changed.emit(self._editor_pt, self._preview_zoom)

    def _bump_editor(self, steps: int) -> None:
        self._editor_pt = max(
            self.EDITOR_MIN_PT, min(self.EDITOR_MAX_PT, self._editor_pt + int(steps))
        )
        self.editor.set_font_point_size(self._editor_pt)
        self._emit_font_settings()

    def _bump_preview(self, steps: int) -> None:
        z = self._preview_zoom + int(steps) * self.PREVIEW_ZOOM_STEP
        z = max(self.PREVIEW_MIN_ZOOM, min(self.PREVIEW_MAX_ZOOM, z))
        self._preview_zoom = round(z, 2)   # 0.1 스텝 부동소수 오차 정리
        self.preview.set_zoom(self._preview_zoom)
        self._emit_font_settings()

    def _reset_fonts(self) -> None:
        self._editor_pt = self.EDITOR_DEFAULT_PT
        self._preview_zoom = self.PREVIEW_DEFAULT_ZOOM
        self.editor.set_font_point_size(self._editor_pt)
        self.preview.set_zoom(self._preview_zoom)
        self._emit_font_settings()

    def _refresh_preview(self, text: str) -> None:
        doc_dir = self._saved_path.parent if self._saved_path else None
        self.preview.set_content(text, doc_dir)

    # --- 스크롤 동기화 ---
    def _on_editor_scrolled(self, _value: int) -> None:
        if self._syncing:
            return
        vsb = self.editor.verticalScrollBar()
        mx = vsb.maximum()
        ratio = vsb.value() / mx if mx > 0 else 0.0
        self._syncing = True
        try:
            self.preview.set_scroll_ratio(ratio)
        finally:
            self._syncing = False

    def _on_preview_scrolled(self, ratio: float) -> None:
        if self._syncing:
            return
        vsb = self.editor.verticalScrollBar()
        self._syncing = True
        try:
            vsb.setValue(round(ratio * vsb.maximum()))
        finally:
            self._syncing = False

    def _on_search_query(self, query: str, case: bool) -> None:
        """검색어 변경 → 미리보기에서도 같은 단어를 강조 (사용자 요청 2026-05-29)."""
        self.preview.highlight_search(query, case)

    # --- 선택 범위 동기화 (data-source-line 매핑, 2026-05-29) ---
    def _on_editor_selection(self) -> None:
        """편집기에서 선택하면 미리보기의 해당 원문 줄 블록을 강조 (나란히 양방향)."""
        if self._sel_syncing:
            return
        cur = self.editor.textCursor()
        if not cur.hasSelection():
            self.preview.clear_source_highlight()
            return
        doc = self.editor.document()
        s = doc.findBlock(cur.selectionStart()).blockNumber()
        e = doc.findBlock(cur.selectionEnd()).blockNumber()
        self.preview.highlight_source_lines(s, e)

    def _on_preview_selection(self, start_line: int, end_line: int, text: str) -> None:
        """미리보기에서 선택하면 편집기에서 대응 텍스트를 실제 선택.

        편집 모드로 전환해도 유지되도록 _last_preview_sel 에 저장(숨은 편집기에도 적용).
        start_line<0 = 선택 해제.
        """
        if start_line < 0:                       # KSELCLEAR — 미리보기 선택 해제
            self._last_preview_sel = None
            if self._sel_syncing:
                return
            # 편집기 선택도 함께 해제 (대칭 — 사용자 보고 2026-05-29: 미리보기에서
            # 선택 취소가 편집기에 안 먹힘). KSELCLEAR 는 미리보기에 선택이 있었을 때만
            # 오므로 그 편집기 선택은 미리보기 미러 → 함께 해제가 맞다.
            cur = self.editor.textCursor()
            if cur.hasSelection():
                self._sel_syncing = True
                try:
                    cur.clearSelection()
                    self.editor.setTextCursor(cur)
                finally:
                    self._sel_syncing = False
            return
        self._last_preview_sel = (start_line, end_line, text)
        if self._sel_syncing:
            return
        rng = self._editor_range_for_lines(start_line, end_line, text)
        if rng is not None:
            self._apply_editor_selection(*rng)

    def _editor_range_for_lines(
        self, start_line: int, end_line: int, text: str
    ) -> tuple[int, int] | None:
        """원문 줄 범위 → 편집기 문자 위치 범위. 가능하면 그 줄 안에서 선택 텍스트로 정밀화.

        source-line 매핑으로 '어느 줄'인지는 정확히 알고(중복 단어 구분), 그 줄 구간 안에서
        선택 텍스트를 찾아 글자 단위로 좁힌다. 못 찾으면(서식 기호 차이 등) 줄 전체를 선택.
        """
        doc = self.editor.document()
        sb = doc.findBlockByNumber(start_line)
        if not sb.isValid():
            return None
        line_start = sb.position()
        eb = doc.findBlockByNumber(end_line)
        if eb.isValid():
            line_end = eb.position() + eb.length() - 1   # length 는 블록 구분자 포함 → -1
        else:
            line_end = doc.characterCount() - 1
        if text:
            seg = doc.toPlainText()[line_start:line_end]
            idx = seg.find(text.strip())
            if idx >= 0:
                s = line_start + idx
                return (s, s + len(text.strip()))
        return (line_start, line_end)

    def _apply_editor_selection(self, start_pos: int, end_pos: int) -> None:
        self._sel_syncing = True
        try:
            cur = self.editor.textCursor()
            cur.setPosition(start_pos)
            cur.setPosition(end_pos, QTextCursor.KeepAnchor)
            self.editor.setTextCursor(cur)
            self.editor.ensureCursorVisible()
        finally:
            self._sel_syncing = False

    def _sync_preview_to_editor(self) -> None:
        """검색 결과로 에디터가 이동했을 때 미리보기를 같은 세로 비율로 따라가게 한다."""
        if self._syncing:
            return
        vsb = self.editor.verticalScrollBar()
        mx = vsb.maximum()
        ratio = vsb.value() / mx if mx > 0 else 0.0
        self._syncing = True
        try:
            self.preview.set_scroll_ratio(ratio)
        finally:
            self._syncing = False

    def cleanup(self) -> None:
        """탭 닫힘 시 WebEngine 리소스 정리 (TabArea 가 호출)."""
        try:
            self.preview.deleteLater()
        except RuntimeError:
            pass
