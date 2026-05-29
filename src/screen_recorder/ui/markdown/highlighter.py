"""Markdown 구문 하이라이터 — block state 로 fenced code 추적.

범위(spec §4): 제목/목록·체크박스/인용/fenced code(``` 와 ~~~)/inline code/
링크·이미지/굵게·기울임. inline code 안 강조 억제. 표는 색칠하지 않음.
"""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

NORMAL = 0
IN_CODE = 1


def _fmt(color: str, *, bold: bool = False, italic: bool = False,
         mono: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    if mono:
        f.setFontFixedPitch(True)
    return f


class MarkdownHighlighter(QSyntaxHighlighter):
    _FENCE = re.compile(r"^\s*(```|~~~)")
    _HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
    _QUOTE = re.compile(r"^\s*>")
    _LIST = re.compile(r"^\s*([-*+]|\d+\.)\s")
    _CHECK = re.compile(r"^\s*[-*+]\s\[[ xX]\]\s")
    _INLINE_CODE = re.compile(r"`[^`\n]+`")
    _LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
    _BOLD = re.compile(r"(?<!\\)\*\*[^*\n]+\*\*")
    _ITALIC = re.compile(r"(?<!\\)(?<!\*)\*[^*\n]+\*(?!\*)")

    def __init__(self, document) -> None:
        super().__init__(document)
        self._f_heading = _fmt("#569cd6", bold=True)
        self._f_quote = _fmt("#6a9955", italic=True)
        self._f_list = _fmt("#c586c0")
        self._f_code = _fmt("#ce9178", mono=True)
        self._f_link = _fmt("#4ec9b0")
        self._f_bold = _fmt("#d4d4d4", bold=True)
        self._f_italic = _fmt("#d4d4d4", italic=True)
        self._f_fence = _fmt("#808080")

    def highlightBlock(self, text: str) -> None:
        prev = self.previousBlockState()
        # fenced code 진입/종료 처리
        if self._FENCE.match(text):
            self.setFormat(0, len(text), self._f_fence)
            # 이전이 코드 안이었으면 이 fence 는 '종료' → 다음은 NORMAL
            self.setCurrentBlockState(NORMAL if prev == IN_CODE else IN_CODE)
            return
        if prev == IN_CODE:
            self.setFormat(0, len(text), self._f_code)
            self.setCurrentBlockState(IN_CODE)
            return
        self.setCurrentBlockState(NORMAL)

        if self._HEADING.match(text):
            self.setFormat(0, len(text), self._f_heading)
            return
        if self._QUOTE.match(text):
            self.setFormat(0, len(text), self._f_quote)
        m = self._CHECK.match(text) or self._LIST.match(text)
        if m:
            self.setFormat(0, m.end(), self._f_list)
        for rx, fmt in ((self._BOLD, self._f_bold), (self._ITALIC, self._f_italic),
                        (self._LINK, self._f_link)):
            for mt in rx.finditer(text):
                self.setFormat(mt.start(), mt.end() - mt.start(), fmt)
        # inline code 는 마지막에 덮어써 강조 위에 우선.
        for mt in self._INLINE_CODE.finditer(text):
            self.setFormat(mt.start(), mt.end() - mt.start(), self._f_code)
