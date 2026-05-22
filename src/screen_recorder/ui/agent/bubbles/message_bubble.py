"""말풍선 한 줄 위젯 — chat_panel.py 에서 분리 (Task 7).

동작 변경 없음.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeySequence, QPixmap, QImage
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .styles import _BUBBLE_STYLES, _LOG_LINE_ROLES

# chat_panel.py 와 같은 logger — getLogger 는 idempotent (동일 인스턴스 반환).
_chat_log = logging.getLogger("kstudio.chat")


class MessageBubble(QFrame):
    """말풍선 한 줄. role 에 따라 스타일 다름.

    assistant 텍스트는 markdown 렌더링 (`Qt.MarkdownText`) — 굵게/링크/코드 블록 지원.
    image_bytes 가 있으면 텍스트 아래 QPixmap 으로 인라인 표시 (최대 너비 480px).
    """

    _IMG_MAX_W = 480

    def __init__(
        self,
        role: str,
        text: str,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._role = role
        self._raw_text = text
        is_log_line = role in _LOG_LINE_ROLES
        self._label = QLabel(text)
        # **모든 role wordWrap=True** — log-line 도 긴 args 가 들어오면 wrap 해야 함.
        # 이전엔 log-line wordWrap=False 로 두었는데, 그 결과 tool_result 의 긴 preview text
        # (~120 chars) 가 single-line sizeHint 를 반환 → VBoxLayout 의 컬럼 너비가 그 wide 값
        # 따라가 → assistant/user bubble (wordWrap=True) 도 wide 컬럼 안에서 wrap 안 함.
        # 사용자 보고 (2026-05-13: "줄바꿈 안되").
        self._label.setWordWrap(True)
        # **TextSelectableByKeyboard 필수** — 없으면 Qt 가 QLabel 에 KeyPress 이벤트 라우팅
        # 자체를 안 함 (focusPolicy=ClickFocus 만으로는 부족). 사용자 보고 2026-05-13: Ctrl+C
        # 가 텍스트로 안 가고 다른 경로(예: 위젯 스크린샷)로 흘러감. by-keyboard 추가로 비로소
        # QLabel 이 키 이벤트 수신 → 우리 eventFilter 가 Ctrl+C 가로채 plain text 로 강제.
        self._label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard | Qt.LinksAccessibleByMouse
        )
        self._label.setOpenExternalLinks(True)
        # Ctrl+C 가로채기 — 마크다운 QLabel 은 클립보드에 image/rich 포맷을 같이 올려 paste
        # target 이 이미지로 잡는 회귀. eventFilter 로 직접 plain text 만 clipboard 에 넣음.
        # focusPolicy=ClickFocus — 마우스 클릭/드래그 시 focus 획득.
        self._label.setFocusPolicy(Qt.ClickFocus)
        self._label.installEventFilter(self)
        # MinimumExpanding — minSizeHint=0 (wrap 허용) + 추가 공간 있으면 채움. Expanding 은
        # sizeHint 무시하고 무한 확장 시도해 wrap 회귀.
        self._label.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        self._label.setMinimumWidth(0)
        # assistant / thinking 만 markdown — 도구 호출/결과는 monospace 유지.
        if role in ("assistant", "thinking"):
            self._label.setTextFormat(Qt.MarkdownText)
            self._label.setText(text)
        else:
            self._label.setTextFormat(Qt.PlainText)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2 if is_log_line else 4)
        lay.addWidget(self._label)

        # 인라인 이미지 — tool_result 의 frame_at / timeline_strip 결과.
        self._image_label: Optional[QLabel] = None
        if image_bytes:
            pix = QPixmap()
            ok = pix.loadFromData(image_bytes)
            if ok and not pix.isNull():
                if pix.width() > self._IMG_MAX_W:
                    pix = pix.scaledToWidth(self._IMG_MAX_W, Qt.SmoothTransformation)
                img_label = QLabel()
                img_label.setPixmap(pix)
                img_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
                img_label.setStyleSheet("background:#000;border-radius:4px;padding:2px;")
                # 이미지 라벨은 절대 키보드 focus 받지 말 것 — focus 받으면 Ctrl+C 가
                # pixmap 으로 향해 클립보드에 이미지 박힘 (사용자 보고: VSCode 붙여넣기 시 스샷).
                img_label.setFocusPolicy(Qt.NoFocus)
                lay.addWidget(img_label)
                self._image_label = img_label

        self.setStyleSheet(_BUBBLE_STYLES.get(role, _BUBBLE_STYLES["assistant"]))
        # 버블 자체에도 eventFilter — child key event 가 부모로 전파될 때 잡기. 또
        # focus 가 image_label 등 우리가 막지 못한 곳에 있어도 ShortcutOverride/KeyPress 가
        # 부모(_MessageBubble) 거쳐 우리 손에 들어옴.
        self.installEventFilter(self)

    def role(self) -> str:
        return self._role

    def append_text(self, text: str) -> None:
        """스트리밍 청크 누적 — assistant 메시지가 여러 텍스트 블록으로 올 때.

        markdown 모드면 누적 텍스트 전체를 다시 setText (포맷 재해석).
        markdown 문서가 늘어나면서 QLabel 의 사이즈 캐시가 stale 일 수 있음 — updateGeometry
        강제 호출로 부모 레이아웃 (스크롤 영역) 이 재계산하게.
        """
        self._raw_text += text
        self._label.setText(self._raw_text)
        if self._role in ("assistant", "thinking"):
            self._label.updateGeometry()
            self._fix_height_for_markdown()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 너비 바뀌면 markdown 표/code block 의 heightForWidth 재계산.
        if self._role in ("assistant", "thinking"):
            self._fix_height_for_markdown()

    def _fix_height_for_markdown(self) -> None:
        """QLabel 의 sizeHint().height() 는 markdown 표·code block 일 때 underestimate →
        말풍선 맨 밑줄이 잘림 (사용자 보고 2026-05-13/14: '표같이 틀같은곳에 들어가서').

        QTextDocument 로 같은 마크다운을 실제 layout 한 뒤 그 높이를 minimumHeight 로 강제.
        QLabel 도 내부적으로 QTextDocument 를 쓰지만 sizeHint 계산이 cache 와 layout 시점
        차이로 stale 일 수 있음. 명시적 측정이 안전.

        2026-05-14 후속 보고: 표·bullet 섞인 긴 메시지에서 여전히 맨 밑 1~2줄 잘림.
        원인 3개:
        1. `int(doc.size().height())` 가 floor → sub-pixel 부분 손실 (h.5px → h px).
        2. +4 buffer 가 너무 작음 — 마지막 줄의 descent (글꼴 baseline 아래 g/y/p 등 꼬리)
           + QLabel 내부 margin + bubble CSS padding 변환의 누적 오차 흡수 부족.
        3. setMinimumHeight 만 호출 — 부모 (스크롤 컨테이너) layout 이 재계산 트리거 못 받음.

        Fix:
        - `math.ceil` 로 fractional 올림.
        - buffer 를 +16 으로 (line descent + safety) — 빈 공간이 약간 늘지만 잘림보다 낫고
          정상 메시지에선 sizeHint 가 더 클 가능성 높아 실제론 영향 미미.
        - setMinimumHeight 후 `self.updateGeometry()` 호출로 bubble 의 sizeHint 도 강제 갱신.
        """
        import math
        from PySide6.QtGui import QTextDocument
        w = self._label.width()
        if w <= 0:
            return
        doc = QTextDocument()
        doc.setDefaultFont(self._label.font())
        doc.setMarkdown(self._raw_text or "")
        # padding 좌우 약간 빼기 — QLabel.text() 가 viewport-사용가능 폭 안에서 wrap 함.
        doc.setTextWidth(max(50, w - 4))
        h = int(math.ceil(doc.size().height())) + 16
        # 너무 작은 텍스트는 그냥 자연 sizeHint 따르게 (작은 메시지 강제 키우지 않음).
        if h > self._label.sizeHint().height():
            self._label.setMinimumHeight(h)
            # 부모 (스크롤 컨테이너) layout 갱신 트리거 — minimumHeight 만으로는 sizeHint 가
            # 즉시 안 바뀌어 ScrollArea 가 옛 높이로 그릴 가능성. updateGeometry 가 invalidate.
            self.updateGeometry()

    def eventFilter(self, obj, event):
        """Ctrl+C 처리 — 선택된 텍스트만 plain text 로 클립보드에 (이미지/HTML 동반 X).

        Qt 의 마크다운 QLabel 은 setMimeData 에 text + html + image 다 올림 → paste target 이
        image 우선 선택하면 사용자가 "텍스트 복사했는데 이미지로 paste" 경험.
        QMimeData.setText 만 호출해 ONLY plain text 로 강제.
        """
        et = event.type()
        # ShortcutOverride 도 가로채야 — Qt 가 ShortcutOverride 단계에서 Ctrl+C 핸들러 결정.
        # KeyPress 만으론 default QLabel copy (HTML/image 동반) 가 우선될 수 있음.
        # obj 검사 안 함 — 버블 자체 / label / image_label 어디서 와도 처리.
        if et in (QEvent.KeyPress, QEvent.ShortcutOverride):
            matches_copy = event.matches(QKeySequence.Copy)
            # 모든 key 이벤트 로깅 — Ctrl+C 가 정말 도착하는지, 어디서 오는지 추적.
            try:
                obj_name = type(obj).__name__
                if obj is self._label:
                    obj_name = "TEXT_label"
                elif obj is self:
                    obj_name = "BUBBLE_self"
                elif obj is self._image_label:
                    obj_name = "IMAGE_label"
                key_str = QKeySequence(int(event.modifiers()) | int(event.key())).toString()
                et_name = "KeyPress" if et == QEvent.KeyPress else "ShortcutOverride"
                _chat_log.debug(
                    "eventFilter %s key=%s obj=%s role=%s matches_copy=%s",
                    et_name, key_str, obj_name, self._role, matches_copy,
                )
            except Exception:
                pass
            if matches_copy:
                selected = self._label.selectedText()
                _chat_log.info(
                    "Ctrl+C role=%s selected_len=%d preview=%r",
                    self._role, len(selected) if selected else 0,
                    (selected[:60] if selected else "") + ("…" if selected and len(selected) > 60 else ""),
                )
                if selected:
                    from PySide6.QtWidgets import QApplication
                    # QLabel.selectedText() 는 line separator 로   (paragraph sep)
                    # 사용 — 일반 paste 대상에선 보이지 않음. 일반 \n 으로 치환.
                    plain = selected.replace(" ", "\n").replace(" ", "\n")
                    # clipboard.setText() — 모든 mime 포맷 비우고 text/plain 만 등록.
                    # setMimeData(text-only) 도 비슷하지만 setText 가 더 보수적/명시적.
                    clip = QApplication.clipboard()
                    clip.setText(plain)
                    # 우리가 set 한 직후 clipboard 상태 — 다른 정보 동반됐는지 즉시 확인.
                    try:
                        mime = clip.mimeData()
                        formats = list(mime.formats()) if mime else []
                        _chat_log.info(
                            "clipboard set: text_len=%d formats=%s has_image=%s",
                            len(plain), formats,
                            bool(mime and mime.hasImage()),
                        )
                    except Exception as e:
                        _chat_log.warning("clipboard log failed: %s", e)
                    event.accept()
                    return True   # 이벤트 소비 — default copy 차단.
        return super().eventFilter(obj, event)
