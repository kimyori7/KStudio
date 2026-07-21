"""MarkdownTab — 코드 에디터 + 실시간 미리보기 + 3뷰 전환 (EditTab 계약 미러)."""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from .icons import load_icon
from .markdown.disk_poll import DiskPoller
from .markdown.editor import MarkdownEditor
from .markdown.highlighter import MarkdownHighlighter
from .markdown.preview import MarkdownPreview
from .markdown.search_bar import MarkdownSearchBar

_log = logging.getLogger(__name__)

# 디스크 확인 주기 — 통지 유실 대비 안전망(disk_poll.py 참고). 2초는 "에이전트가
# 고친 걸 눈치채기엔 충분히 빠르고, stat 한 번이라 있으나 마나 한 비용" 의 절충.
POLL_INTERVAL_MS = 2000


class SaveResult(Enum):
    """저장 결과 — 호출자가 취소(조용히)와 실제 쓰기 실패(경고)를 구분하기 위함."""
    SAVED = "saved"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ViewMode(Enum):
    EDITOR = "editor"
    PREVIEW = "preview"
    SPLIT = "split"
    DIFF = "diff"


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
    # 드래그-드롭으로 본 파일을 라이브러리에 등록 요청 — DIFF 칸 채움(경로). main_window 가
    # path 중복 제거 후 DOCUMENT entry 추가.
    diff_doc_loaded = Signal(object)        # Path
    # 편집기에 .md 드롭 → 새 문서 탭으로 열기 요청. main_window 가 _open_markdown_path 로
    # (열기 + 라이브러리 등록).
    open_document_requested = Signal(object)  # Path

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
        # 편집기에 .md 드롭 → 새 문서로 열기 요청을 위로 전달.
        self.editor.file_open_requested.connect(self.open_document_requested.emit)
        self._highlighter = MarkdownHighlighter(self.editor.document())
        self.preview = MarkdownPreview()

        # 뷰모드 토글 버튼
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        self._btn_group = QButtonGroup(self)
        self._buttons: dict[ViewMode, QPushButton] = {}
        for mode, label in ((ViewMode.EDITOR, "✎ 편집"),
                            (ViewMode.PREVIEW, "👁 미리보기"),
                            (ViewMode.SPLIT, "⊟ 나란히"),
                            (ViewMode.DIFF, "⇄ 비교")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, m=mode: self.set_view_mode(m))
            self._btn_group.addButton(btn)
            self._buttons[mode] = btn
            bar.addWidget(btn)
        # 수동 새로고침 — 모드가 아닌 액션 버튼(체크 없음). 외부 변경 감지가 어떤
        # 이유로든 놓쳐도 사용자가 즉시 복구할 수 있는 안전망(2026-07-14 사용자 요청).
        self.refresh_btn = QPushButton("⟳ 새로고침")
        self.refresh_btn.setToolTip("디스크의 최신 내용을 다시 불러오고 미리보기를 다시 그립니다")
        self.refresh_btn.setFocusPolicy(Qt.NoFocus)
        self.refresh_btn.clicked.connect(self.refresh_from_disk)
        bar.addWidget(self.refresh_btn)
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

        # 외부 변경 반영 — 열린 파일의 '부모 디렉터리'를 감시(QFileSystemWatcher). 디스크가
        # 외부 에디터로 바뀌면 "최신 내용으로 불러올까요?" 확인 팝업을 띄우고, 사용자가
        # [예] 를 눌렀을 때만 반영한다(조용히 덮어쓰지 않음 — 사용자 요청 2026-06-01).
        # ⚠ 파일을 직접 감시(addPath(file))하면 Windows 에서 그 파일에 핸들이 걸려 외부
        # 에디터의 atomic save(temp→rename 교체)가 WinError 5 로 막힌다(VS Code·에이전트).
        # 부모 디렉터리 감시는 파일을 잠그지 않으면서 atomic save·제자리쓰기 둘 다 잡고
        # rename 으로도 풀리지 않는다(2026-06-29 실측).
        # _disk_text = 마지막으로 디스크와 동기화한 내용(로드/저장/reload/거절 시 갱신). 외부
        # 변경 판별 기준 — 편집기 현재 텍스트가 아니라 이 값과 비교해야 '저장 직후 타이핑'
        # 오탐을 피한다(advisor 2026-06-01). directoryChanged 는 버스트로 오므로 150ms 디바운스.
        # _reload_prompt_open = 모달 팝업이 떠 있는 동안 재진입 차단(exec 의 중첩 루프에서
        # 디바운스 타이머가 _reload_check 를 다시 부를 수 있음).
        self._disk_text: str | None = None
        self._reload_prompt_open = False
        # 읽기 실패(쓰기 잠금 등) 연속 횟수 — 상한까지 디바운스 재장전으로 재시도.
        # 조용히 버리면 마지막 변경이 영영 반영 안 됨(2026-07-14, Phase 108 과 같은 부류).
        self._fs_read_retries = 0
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_debounce = QTimer(self)
        self._fs_debounce.setSingleShot(True)
        self._fs_debounce.setInterval(150)
        self._fs_debounce.timeout.connect(self._reload_check)
        self._fs_watcher.directoryChanged.connect(self._on_dir_changed)

        # 통지와 독립된 두 번째 경로 — 주기적 디스크 확인(2026-07-21). 통지가 유실되는
        # 것이 실측돼(disk_poll.py 주석) 통지 하나에만 의존하는 설계를 버렸다. 사용자가
        # 하루 종일 손으로 누르던 ⟳ 새로고침이 매번 동작했다는 사실이 근거 — 그 수동
        # 동작을 자동화한 것이다. stat 만 보므로 탭당 비용은 무시할 수준.
        self._disk_poller = DiskPoller()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_disk)
        self._poll_timer.start()

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

        # 비교(DIFF) 뷰 — lazy 생성(처음 DIFF 진입 시). 모드 전환에도 살아 있어 오른쪽 유지.
        self._view_mode = ViewMode.SPLIT
        self._diff_view = None

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
        tab._disk_text = text           # 외부 변경 판별 기준
        tab._set_saved_path(path)       # _saved_path 갱신 + 파일 감시 시작
        tab._dirty = False              # 막 로드한 파일은 깨끗한 상태
        tab.save_state_changed.emit()
        tab._refresh_preview(text)
        # 파일 열기의 기본 보기는 미리보기 — 열람이 주 용도(사용자 요청 2026-07-14).
        # 새(빈) 문서는 작성이 목적이라 from_blank 는 나란히(SPLIT) 유지.
        tab.set_view_mode(ViewMode.PREVIEW)
        return tab

    # --- EditTab 계약 ---
    def source_label(self) -> str:
        return self._source_label

    def saved_path(self) -> Path | None:
        return self._saved_path

    def needs_save(self) -> bool:
        # 왼쪽(탭 문서) 미저장 OR 비교(DIFF) 오른쪽 칸 미저장 → 탭 ● 마커.
        right_dirty = self._diff_view is not None and self._diff_view.right_dirty
        return (self._saved_path is None) or self._dirty or right_dirty

    def mark_saved(self, path: Path) -> None:
        self._set_saved_path(path)
        self._dirty = False
        self.save_state_changed.emit()

    def _set_saved_path(self, path: Path | None) -> None:
        """_saved_path 를 갱신하고 QFileSystemWatcher 가 그 파일의 '부모 디렉터리'를 감시하게 한다.

        ⚠ 파일을 직접 감시하면 Windows 에서 핸들이 걸려 외부 에디터의 atomic save
        (temp→rename 교체)가 WinError 5 로 막힌다(VS Code 등) → 부모 디렉터리를 감시한다.
        모든 _saved_path 할당의 단일 길목 — 열기/저장/비교칸 채움 어디로 와도 감시가
        새 파일의 부모 폴더로 따라간다."""
        watched = self._fs_watcher.files() + self._fs_watcher.directories()
        if watched:
            self._fs_watcher.removePaths(watched)
        self._saved_path = Path(path) if path is not None else None
        if self._saved_path is not None:
            d = self._saved_path.parent
            if d.exists():
                ok = self._fs_watcher.addPath(str(d))
                if not ok:
                    # 감시 등록 실패 — 외부 변경 팝업이 영영 안 뜨는 원인이 되므로 남긴다.
                    _log.warning("외부 변경 감시 등록 실패: %s", d)
            else:
                _log.warning("외부 변경 감시 불가 — 부모 폴더 없음: %s", d)
        # 폴링 기준도 같은 길목에서 맞춘다 — 열기/저장/비교칸 어디로 와도 '지금 디스크'
        # 가 기준이 되어, 우리 앱 자신의 저장이 외부 변경으로 보고되지 않는다.
        self._disk_poller.watch(self._saved_path)

    def _on_text_changed(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.save_state_changed.emit()

    # --- 저장 ---
    def save(self) -> SaveResult:
        # 비교 모드에서 오른쪽 칸에 포커스가 있으면 그 칸을 자기 파일로 저장(포커스 칸 저장 규칙).
        if (self._view_mode is ViewMode.DIFF and self._diff_view is not None
                and self._diff_view.right_has_focus()):
            return self._save_diff_right()
        if self._saved_path is None:
            return self.save_as()
        return SaveResult.SAVED if self._write_to(self._saved_path) else SaveResult.FAILED

    def _save_diff_right(self) -> SaveResult:
        """비교 뷰 오른쪽 칸을 자기 파일로 저장(경로 없으면 Save As)."""
        dv = self._diff_view
        path = dv.right_path
        if path is None:
            fn, _ = QFileDialog.getSaveFileName(
                self, "오른쪽 문서 저장", "", "Markdown (*.md *.markdown)"
            )
            if not fn:
                return SaveResult.CANCELLED
            path = Path(fn)
        try:
            path.write_text(dv.right_text(), encoding="utf-8")
        except OSError as e:
            _log.error("DIFF 오른쪽 저장 실패: %s", e)
            return SaveResult.FAILED
        dv.mark_right_saved(path)
        return SaveResult.SAVED

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
        text = self.editor.toPlainText()
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            _log.error("Markdown 저장 실패: %s", e)
            return False
        self._disk_text = text   # 자기 저장 → 외부 변경 오탐 방지(이 값과 비교)
        self.mark_saved(path)
        return True

    # --- 뷰모드 ---
    def set_view_mode(self, mode: ViewMode) -> None:
        self._view_mode = mode
        self._buttons[mode].setChecked(True)
        # 비교(DIFF) 모드 — 편집/미리보기 splitter 를 숨기고 DiffView 만 표시.
        if mode is ViewMode.DIFF:
            dv = self._ensure_diff_view()
            self._splitter.setVisible(False)
            dv.setVisible(True)
            self._editor_font_group.setVisible(False)
            self._preview_font_group.setVisible(False)
            return
        if self._diff_view is not None:
            self._diff_view.setVisible(False)
        self._splitter.setVisible(True)
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

    # --- 비교(DIFF) 뷰 ---
    def _ensure_diff_view(self):
        """DiffView 를 lazy 생성하고 레이아웃에 추가(처음 숨김). 왼쪽은 탭 문서 공유."""
        if self._diff_view is None:
            from .markdown.diff_view import DiffView
            dv = DiffView()
            dv.set_left_document(self.editor.document())   # 왼쪽 = 현재 문서(공유)
            dv.right_dirty_changed.connect(self.save_state_changed.emit)
            dv.request_fill.connect(self._on_diff_request_fill)
            dv.pane_filled.connect(self._on_diff_pane_filled)
            dv.hide()
            self.layout().addWidget(dv, stretch=1)
            self._diff_view = dv
        return self._diff_view

    def diff_has_empty_pane(self) -> bool:
        """라이브러리 클릭 라우팅용 — DIFF 모드이고 채울 빈 칸이 있는가."""
        return (self._view_mode is ViewMode.DIFF and self._diff_view is not None
                and self._diff_view.has_empty_pane())

    def fill_diff_next(self, path: Path) -> None:
        self._ensure_diff_view().fill_next(Path(path))

    def _on_diff_request_fill(self, side: str) -> None:
        """빈 칸 클릭 → 파일 선택창에서 고른 .md 를 그 칸에 로드."""
        fn, _ = QFileDialog.getOpenFileName(
            self, "비교할 문서 선택", "", "Markdown (*.md *.markdown)"
        )
        if fn and self._diff_view is not None:
            self._diff_view.load_side(side, Path(fn))

    def _on_diff_pane_filled(self, side: str, path) -> None:
        """왼쪽(=탭 문서)이 파일로 채워지면 빈 탭이 그 파일이 된다 — saved_path 연결.

        어느 칸이든 파일로 채워졌으면(드롭/파일창) 라이브러리 등록을 요청한다 — 라이브러리
        클릭으로 온 파일은 main_window 가 path 로 중복 제거하므로 안전.
        """
        if side == "left":
            try:
                self._disk_text = _read_text_with_fallback(Path(path))
            except OSError:
                self._disk_text = self.editor.toPlainText()
            self._set_saved_path(Path(path))   # 감시 시작
            self._dirty = False
            self.save_state_changed.emit()
        self.diff_doc_loaded.emit(Path(path))

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

    # --- 외부 변경 반영 (QFileSystemWatcher) ---
    def _on_dir_changed(self, path: str) -> None:
        """감시 폴더 변경 통지 → 디바운스 재장전. 동작은 이전 lambda 와 동일.

        ⚠ 진단 로그(2026-07-21) — "외부 변경 팝업이 안 뜬다" 재발 3회차. 지금까지의
        수정은 전부 _reload_check 안쪽(중간층)만 손봤는데, 조용한 실패의 원인이
        세 가지인데 로그로 구분이 안 됐다. 이 한 줄이 셋을 가른다:
          - 실제 변경이 있었는데 '감시 신호' 없음        → OS→Qt 통지가 안 옴(감시 죽음)
          - '감시 신호' 는 있는데 '동일 내용'/'감지' 없음 → 디바운스 굶김
            (150ms 단발 타이머를 매 통지가 start() 로 리셋 — 통지가 150ms 보다
             촘촘하면 _reload_check 가 영영 실행되지 않는다)
          - '감시 신호' → '동일 내용 — 무시'            → 판별 기준(_disk_text) 문제
        원인 확정 후 제거하거나 DEBUG 로 낮출 것.
        """
        _log.info("감시 신호: %s", path)
        self._fs_debounce.start()

    def _poll_disk(self) -> None:
        """주기적 안전망 — 통지가 유실돼도 외부 변경을 잡는다.

        값싼 stat 비교로 후보만 거르고, 실제 판단은 통지 경로와 똑같이 _reload_check
        에 맡긴다(팝업 정책·dirty 경고·거절 기억이 한 곳에만 있게).
        모달이 떠 있는 동안은 건너뛴다 — _reload_check 의 재진입 가드와 같은 이유.
        """
        if self._reload_prompt_open or self._saved_path is None:
            return
        if not self._disk_poller.check():
            return
        _log.info("폴링: 디스크 변화 감지 — 검사 실행: %s", self._saved_path)
        self._reload_check()

    def _reload_check(self) -> None:
        """감시 중인 파일이 외부에서 바뀌었으면 확인 팝업을 띄우고, [예] 일 때만 반영한다.

        - 디스크 == 마지막 동기화 내용(_disk_text): 우리 저장/허위 이벤트 → no-op
        - 외부 변경: "최신 내용으로 불러올까요?" 팝업 → 예=reload / 아니오=현재 유지
          (미저장 편집이 있으면 팝업에 '편집 내용이 사라집니다' 경고)
        """
        if self._reload_prompt_open:
            # 팝업이 떠 있는 동안 도착한 변경 통지 — 버리면 안 된다. 모달 중 마지막
            # 변경의 디바운스가 여기서 소멸하면 [아니오]/Esc 뒤 팝업·갱신이 영영 안
            # 온다(에이전트 연속 편집 중 사용자 보고 2026-07-13). 디바운스를 다시
            # 걸어 모달이 닫힌 뒤 재검사한다([예]는 disk==_disk_text 라 no-op).
            self._fs_debounce.start()
            return
        p = self._saved_path
        if p is None:
            return
        # 부모 디렉터리 감시는 atomic rename 으로도 잘 안 풀리지만, 폴더가 지워졌다
        # 다시 생기는 드문 경우를 대비해 감시를 보장한다.
        d = p.parent
        if d.exists() and str(d) not in self._fs_watcher.directories():
            self._fs_watcher.addPath(str(d))
        if not p.exists():
            _log.info("외부 변경 검사: 파일 없음(삭제/교체 중) — 보류: %s", p)
            return   # 삭제는 범위 밖 — 열린 탭/편집 보존
        try:
            disk = _read_text_with_fallback(p)
        except OSError as e:
            # 일시 실패(외부 에디터의 쓰기 잠금 등)일 수 있다 — 버리면 마지막 변경이
            # 영영 반영 안 되므로(2026-07-14) 상한까지 디바운스 재장전으로 재시도.
            # 상한 초과(영구 실패: 권한 등)면 포기 — 무한 150ms 루프 방지. 다음 실제
            # 파일 이벤트가 오면 처음부터 다시 시도된다.
            self._fs_read_retries += 1
            if self._fs_read_retries <= 5:
                _log.info("외부 변경 검사: 읽기 실패(%s) — 재시도 %d/5", e, self._fs_read_retries)
                self._fs_debounce.start()
            else:
                _log.warning("외부 변경 검사: 읽기 실패 지속 — 포기: %s (%s)", p, e)
            return
        self._fs_read_retries = 0
        if disk == self._disk_text:
            # 진단 로그(2026-07-21) — 여기서 조용히 끝난 건지, 애초에 여기까지
            # 못 온 건지가 구분이 안 돼 3회 오진했다. _on_dir_changed 참고.
            _log.info("외부 변경 검사: 동일 내용 — 무시: %s", p)
            return   # 자기 저장 또는 동일 내용 — 반영할 외부 변경 없음
        _log.info("외부 변경 감지 — 확인 팝업 표시: %s (dirty=%s)", p, self._dirty)
        self._reload_prompt_open = True
        try:
            confirmed = self._confirm_external_reload(self._dirty)
        finally:
            self._reload_prompt_open = False
        _log.info("외부 변경 팝업 답: %s", "예(반영)" if confirmed else "아니오(유지)")
        if confirmed:
            # 모달이 떠 있는 동안 파일이 또 바뀌었을 수 있다(블로킹 nested 루프). 적용
            # 직전 디스크를 다시 읽어 '팝업 이후'의 최신본까지 반영한다(재읽기 실패 시 스냅샷).
            try:
                latest = _read_text_with_fallback(p)
            except OSError:
                latest = disk
            self._apply_external_reload(latest)
        else:
            # 거절한 버전을 기억 — 같은 내용으로 다시 묻지 않음(허위 이벤트 반복 차단).
            self._disk_text = disk

    def _confirm_external_reload(self, dirty: bool) -> bool:
        """'최신 내용으로 불러올까요?' 모달 확인. 테스트에서 patch 가능하게 분리.

        반환 True = 사용자가 [예](최신화) 선택.
        """
        if dirty:
            msg = ("이 문서가 외부에서 변경되었습니다.\n"
                   "미저장 편집이 있습니다 — 최신 내용으로 불러오면 편집한 내용이 사라집니다.\n\n"
                   "최신 내용으로 불러올까요?")
        else:
            msg = "이 문서가 외부에서 변경되었습니다.\n\n최신 내용으로 불러올까요?"
        ans = QMessageBox.question(
            self, "외부 변경 감지", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return ans == QMessageBox.StandardButton.Yes

    def _apply_external_reload(self, text: str) -> None:
        """디스크 내용으로 편집기를 교체 — 커서 위치와 세로 스크롤 비율을 보존."""
        vsb = self.editor.verticalScrollBar()
        mx = vsb.maximum()
        ratio = vsb.value() / mx if mx > 0 else 0.0
        cur_pos = self.editor.textCursor().position()
        self.editor.setPlainText(text)   # textChanged → _dirty True 가 되므로 아래서 복구
        self._disk_text = text
        self._dirty = False
        cur = self.editor.textCursor()
        cur.setPosition(min(cur_pos, len(text)))
        self.editor.setTextCursor(cur)
        vsb.setValue(round(ratio * vsb.maximum()))
        self.save_state_changed.emit()
        self._refresh_preview(text)

    def refresh_from_disk(self) -> None:
        """수동 새로고침(⟳ 버튼) — 감시 재장전 + 디스크 최신본 반영/미리보기 재렌더.

        외부 변경 감지가 어떤 이유로든 놓친 상황의 사용자 안전망(2026-07-14):
        - 감시 재장전: _set_saved_path 재호출(removePaths→addPath)로 죽은 watch 복구
        - 외부 변경 있음: 깨끗하면 즉시 반영(버튼 클릭 = 명시적 동의), 미저장 편집이
          있으면 잃음 경고 확인 후에만 반영(조용히 덮어쓰지 않음 정책 유지)
        - 외부 변경 없음: 편집 내용은 건드리지 않고 미리보기만 재렌더
          (미리보기 렌더러가 죽었을 때의 수동 복구 수단 겸용)
        """
        p = self._saved_path
        if p is None:
            self._refresh_preview(self.editor.toPlainText())
            return
        self._set_saved_path(p)   # 감시 재장전
        try:
            disk = _read_text_with_fallback(p)
        except OSError as e:
            _log.warning("수동 새로고침: 읽기 실패 %s (%s)", p, e)
            self._refresh_preview(self.editor.toPlainText())
            return
        if disk == self._disk_text:
            self._refresh_preview(self.editor.toPlainText())
            return
        if self._dirty and not self._confirm_external_reload(True):
            return
        _log.info("수동 새로고침: 디스크 반영 %s", p)
        self._apply_external_reload(disk)

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
            # 편집기 클릭으로 선택이 풀리면 미리보기의 네이티브 드래그 선택도 해제 (대칭).
            self.preview.clear_native_selection()
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
