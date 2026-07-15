"""업데이트 통합 카드 다이얼로그 — 안내/다운로드/실패 3상태 한 창.

뷰 전용: 시그널만 내보내고, 설정 저장·다운로드 시작·적용은 controller 책임.
색은 tokens 팔레트 키만 사용 — theme.current_palette() 로 현재 모드
(영상/이미지/문서) 액센트를 자동으로 따라간다.
"""
from __future__ import annotations

import html as _html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from screen_recorder.app.updater.manifest import Manifest
from screen_recorder.ui.app_icon import app_icon
from screen_recorder.ui.theme import current_palette


def format_bytes(n: int) -> str:
    """바이트 → 사람 읽는 단위. KB 이하 정수, MB 소수 1자리, GB 소수 2자리."""
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.2f} GB"


def notes_html(notes: str, p: dict) -> str:
    """릴리스 노트 문자열 → 불릿 목록 HTML(순수). 빈 문자열이면 안내 문구.

    manifest.notes 는 릴리스 파이프라인이 넣는 자유 텍스트 — 줄 단위로 쪼개고
    선행 불릿 기호(-, •, ·)는 벗겨서 우리 스타일로 통일한다.
    """
    lines = [ln.strip().lstrip("-•· ").strip() for ln in (notes or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return (f'<p style="color:{p["text_sub"]};">자세한 변경 내역은 '
                f'업데이트 후 패치 내역에서 확인할 수 있어요.</p>')
    items = "".join(f'<li style="margin:2px 0;">{_html.escape(ln)}</li>'
                    for ln in lines)
    return f'<ul style="margin:0; padding-left:18px; color:{p["text"]};">{items}</ul>'


_STATE_PROMPT, _STATE_DOWNLOADING, _STATE_ERROR = 0, 1, 2


def _dialog_qss(p: dict) -> str:
    """카드 전용 로컬 QSS — 전역 테마 위에 얹는 규칙만. 색은 전부 팔레트 키."""
    return f"""
QDialog {{ background-color: {p["surface_msg"]}; }}
QLabel#updTitle {{ font-size: 14pt; font-weight: 700; color: {p["text_pure"]}; }}
QLabel#updChip {{
    background-color: {p["surface_input"]};
    color: {p["text_sub"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 9pt;
}}
QTextBrowser#updNotes {{
    background-color: {p["surface_input"]};
    border: 1px solid {p["border"]};
    border-radius: 8px;
    padding: 8px;
}}
QLabel#updSub {{ color: {p["text_sub"]}; font-size: 9pt; }}
QLabel#updError {{ color: {p["danger"]}; }}
QPushButton#updPrimary {{
    background-color: {p["selection_bg"]};
    border: 1px solid {p["primary"]};
    color: {p["text_pure"]};
    font-weight: 600;
    padding: 6px 18px;
}}
QPushButton#updPrimary:hover {{ background-color: {p["primary"]}; color: {p["bg"]}; }}
QPushButton#updSkip {{
    background: transparent; border: none;
    color: {p["text_dim"]};
    text-decoration: underline;
    padding: 4px 2px;
}}
QPushButton#updSkip:hover {{ color: {p["text_sub"]}; background: transparent; }}
QProgressBar {{
    background-color: {p["surface_input"]};
    border: none;
    border-radius: 4px;
}}
QProgressBar::chunk {{ background-color: {p["primary"]}; border-radius: 4px; }}
"""


class UpdateDialog(QDialog):
    """새 버전 안내 → 다운로드 진행 → (실패 시) 오류를 한 창에서 전환하는 카드."""

    update_now = Signal()
    skipped = Signal()

    def __init__(self, current_version: str, manifest: Manifest,
                 parent=None, palette: dict | None = None):
        super().__init__(parent)
        p = self._p = palette or current_palette()
        self._canceled = False
        self.setWindowTitle("KStudio 업데이트")
        # WindowModal — 메인 창 조작은 막되 이벤트 루프는 돈다 (비블로킹 show 전제).
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # ---- 헤더: 아이콘 + 제목 + 버전 칩 ----
        header = QHBoxLayout()
        header.setSpacing(12)
        icon_label = QLabel(self)
        icon_label.setPixmap(app_icon().pixmap(40, 40))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self._title = QLabel("새 버전이 준비됐어요", self)
        self._title.setObjectName("updTitle")
        title_col.addWidget(self._title)
        self._chip = QLabel(f"v{current_version}  →  v{manifest.version}", self)
        self._chip.setObjectName("updChip")
        chip_row = QHBoxLayout()          # 칩이 가로로 늘어붙지 않게 내용 폭만.
        chip_row.addWidget(self._chip)
        chip_row.addStretch(1)
        title_col.addLayout(chip_row)
        header.addLayout(title_col, 1)
        root.addLayout(header)

        # ---- 릴리스 노트 ----
        self._notes = QTextBrowser(self)
        self._notes.setObjectName("updNotes")
        self._notes.setOpenExternalLinks(True)
        self._notes.setHtml(notes_html(manifest.notes, p))
        self._notes.setMinimumHeight(120)
        root.addWidget(self._notes, 1)

        # ---- 푸터: 상태별 페이지 ----
        self._footer = QStackedWidget(self)
        self._footer.addWidget(self._build_prompt_footer())
        self._footer.addWidget(self._build_download_footer())
        self._footer.addWidget(self._build_error_footer())
        root.addWidget(self._footer)

        self.setStyleSheet(_dialog_qss(p))

    # ---- 푸터 페이지 빌더 ----
    def _build_prompt_footer(self) -> QWidget:
        w = QWidget(self)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self._skip_btn = QPushButton("이 버전 건너뛰기", w)
        self._skip_btn.setObjectName("updSkip")
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.clicked.connect(self.skipped.emit)
        lay.addWidget(self._skip_btn)
        lay.addStretch(1)
        self._later_btn = QPushButton("나중에", w)
        self._later_btn.clicked.connect(self.reject)
        lay.addWidget(self._later_btn)
        self._now_btn = QPushButton("지금 업데이트", w)
        self._now_btn.setObjectName("updPrimary")
        self._now_btn.setDefault(True)
        self._now_btn.clicked.connect(self._on_update_now)
        lay.addWidget(self._now_btn)
        return w

    def _build_download_footer(self) -> QWidget:
        w = QWidget(self)
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        self._bar = QProgressBar(w)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(8)
        col.addWidget(self._bar)
        row = QHBoxLayout()
        self._size_label = QLabel("다운로드 준비 중…", w)
        self._size_label.setObjectName("updSub")
        row.addWidget(self._size_label)
        row.addStretch(1)
        self._cancel_btn = QPushButton("취소", w)
        self._cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self._cancel_btn)
        col.addLayout(row)
        return w

    def _build_error_footer(self) -> QWidget:
        w = QWidget(self)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self._error_label = QLabel("", w)
        self._error_label.setObjectName("updError")
        self._error_label.setWordWrap(True)
        lay.addWidget(self._error_label, 1)
        self._close_btn = QPushButton("닫기", w)
        self._close_btn.clicked.connect(self.reject)
        lay.addWidget(self._close_btn)
        return w

    # ---- 시그널 핸들러 ----
    def _on_update_now(self) -> None:
        self.start_download()
        self.update_now.emit()

    def _on_cancel(self) -> None:      # Task 4 에서 동작 확정 (여기선 자리만)
        pass

    def start_download(self) -> None:
        """PROMPT → DOWNLOADING 전환 (같은 창)."""
        self._title.setText("업데이트 다운로드 중")
        self._footer.setCurrentIndex(_STATE_DOWNLOADING)
