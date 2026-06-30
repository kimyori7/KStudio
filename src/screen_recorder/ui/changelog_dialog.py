"""패치 내역 다이얼로그 — 시작 팝업·전체 보기 공유. HTML 빌더는 순수."""
from __future__ import annotations

import html as _html

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTextBrowser, QDialogButtonBox,
)


def changelog_html(entries: list[tuple[str, list[str]]]) -> str:
    """(version, [notes]) 목록 → 표시용 HTML(순수). 빈 목록이면 안내 문구."""
    if not entries:
        return "<p>표시할 패치 내역이 없습니다.</p>"
    parts: list[str] = []
    for version, notes in entries:
        parts.append(f"<h3>v{_html.escape(version)}</h3>")
        parts.append("<ul>")
        for note in notes:
            parts.append(f"<li>{_html.escape(note)}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


class ChangelogDialog(QDialog):
    """읽기전용 스크롤 다이얼로그. 두 용도(시작 팝업·전체 보기)가 공유."""

    def __init__(self, entries, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(480, 420)
        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setHtml(changelog_html(entries))
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
