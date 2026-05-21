"""Claude 와 대화하는 채팅 패널 (QDockWidget).

레이아웃:
- 상단: 메시지 리스트 (스크롤 영역, 각 메시지 = QFrame).
- 하단: 멀티라인 입력창(_ChatInputEdit, QPlainTextEdit 기반) + 보내기 버튼.
  Enter=보내기, Shift+Enter=줄바꿈. 입력이 길어지면 최대 5줄까지 자동 확장.
- 진행 상태: 입력창 위에 작은 상태 라벨 ("도구 사용: get_video_state...").

신호 흐름:
- 사용자 입력 → user_submitted(str) → MainWindow 가 AgentRuntime.send() 호출.
- AgentRuntime.message_received(AgentMessage) → ChatPanel.append_message().
- AgentRuntime.event_received(AgentEvent) → ChatPanel.update_status().

직접 AgentRuntime 을 들고 있지 않음 — 의존성 역전. 테스트에서 시그널만 emit 해도
UI 갱신 검증 가능.
"""
from __future__ import annotations

import logging
from typing import Optional

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QBuffer, QEvent, QIODevice, Signal, Slot
from PySide6.QtGui import QKeySequence, QKeyEvent, QPixmap, QImage
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFrame, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ...agent.chat_history import (
    MAX_MESSAGES, PERSISTABLE_ROLES, load_history, save_history,
)
from ...agent.models import ModelRegistry, check_runtime_available
from ...agent.plan_gate import PlanGate
from ...agent.runtime import AgentMessage, AgentEvent


# 채팅 디버그 로그 — 사용자가 보고할 때 ~/AppData/Local/KStudio/logs/chat_debug.log 를
# 첨부하면 정확한 이벤트 흐름 파악 가능. Ctrl+C 같은 UI 회귀 디버깅이 핵심 용도.
# setup_logging() 의 root 로거에 합치면 app.log 안에 묻혀버려 분리.
_chat_log = logging.getLogger("kstudio.chat")


def _ensure_chat_log_handler() -> None:
    """첫 호출 시 chat_debug.log 파일 핸들러 부착. 한 번만 실행."""
    if getattr(_chat_log, "_kstudio_handler_added", False):
        return
    try:
        log_dir = Path.home() / "AppData" / "Local" / "KStudio" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(log_dir / "chat_debug.log", encoding="utf-8")
        h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        _chat_log.addHandler(h)
        _chat_log.setLevel(logging.DEBUG)
        # root 로 전파 막음 — app.log 오염 방지.
        _chat_log.propagate = False
        _chat_log._kstudio_handler_added = True  # type: ignore[attr-defined]
        _chat_log.info("==== chat_debug.log started ====")
    except OSError:
        pass


# 모델 옵션 — (display, model_id). 정액제 사용자도 모델 선택 자유롭게.
# Opus 가 가장 똑똑하지만 토큰 비싸고 Pro 플랜 quota 낮음. Sonnet 이 기본 추천.
# 짧은 라벨 — 입력 바 위 좁은 공간에 깔끔히 들어가도록.
MODEL_OPTIONS: list[tuple[str, str]] = [
    ("Sonnet 4.6", "claude-sonnet-4-6"),
    ("Opus 4.7", "claude-opus-4-7"),
    ("Haiku 4.5", "claude-haiku-4-5-20251001"),
]
DEFAULT_MODEL_ID = MODEL_OPTIONS[0][1]


# 모델별 컨텍스트 윈도 한계 — 입력 토큰이 이 값에 가까워지면 /compact 권유.
# 1M 컨텍스트 변형도 있지만 default 200k 가정. 정확한 한계 모르면 200k 폴백.
# Qwen2.5-Omni 7B 는 native 32k — 훨씬 빨리 가득 차므로 별도 한계.
_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-sonnet-4-6":        200_000,
    "claude-opus-4-7":          200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "qwen25-omni-7b":            32_768,
}
_DEFAULT_CONTEXT_LIMIT = 200_000


def _context_limit_for(model_id: str) -> int:
    return _MODEL_CONTEXT_LIMITS.get(model_id, _DEFAULT_CONTEXT_LIMIT)


def _ctx_color_for(pct: float) -> str:
    """컨텍스트 사용률 % 별 동그라미 색 — Discord 상태 아이콘 톤.

    낮음(녹) → 중간(노랑) → 높음(빨강) 점진. 70% 이상이면 사용자에게 /compact 또는 /clear 신호.
    """
    if pct < 40.0:
        return "#22c55e"   # green
    if pct < 70.0:
        return "#eab308"   # yellow
    return "#ef4444"       # red


# 슬래시 명령 — 채팅창 입력 시작에 '/' 면 명령으로 라우팅.
# (값은 시그널/내부 핸들러 둘 다에서 식별용 키)
SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/clear",   "대화 + 누적 토큰 카운터 초기화 (영상/제안 큐는 그대로)"),
    ("/compact", "지금까지 대화를 Claude 가 요약해서 컨텍스트 줄임"),
    ("/help",    "사용 가능한 명령 목록"),
]


# "채팅 앱" 같은 말풍선 느낌을 빼고 평문(터미널 로그) 스타일로 — 사용자 요청 2026-05-19.
# 일반 대화 (user / assistant / thinking / system) 는 배경/테두리/radius/padding 없이
# 텍스트 색만으로 role 구분. tool_use / tool_result 는 기존대로 한 줄 로그.
# 액션이 필요한 카드 (error, proposals_preview) 는 시각 강조 유지.
_BUBBLE_STYLES = {
    "user":              "color:#f1f5f9;font-weight:600;",
    "assistant":         "color:#e2e8f0;",
    "thinking":          "color:#64748b;font-style:italic;font-size:11px;",
    "system":            "color:#94a3b8;font-style:italic;font-size:11px;",
    "tool_use":          "color:#fcd34d;padding:0px 2px;font-family:Consolas,monospace;font-size:10px;",
    "tool_result":       "color:#86efac;padding:0px 2px;font-family:Consolas,monospace;font-size:10px;",
    "error":             "background:#3f1d1d;color:#fca5a5;border:1px solid #7f1d1d;border-radius:6px;padding:6px 10px;",
    "proposals_preview": "background:#0c1322;color:#dbeafe;border:1px solid #38bdf8;border-radius:8px;padding:10px 12px;",
    "plan_card": "background:#1a2533;color:#e0f2fe;border:1px solid #0ea5e9;"
                 "border-radius:8px;padding:10px 12px;",
}

# 로그 스타일 (배경 없음) role 들 — spacing 더 좁게 + 줄바꿈 안 함.
_LOG_LINE_ROLES = frozenset(("tool_use", "tool_result"))


_ACTION_LABEL_KO = {"add": "추가", "remove": "삭제", "modify": "수정"}
_TYPE_LABEL_KO = {
    "caption": "캡션", "cut": "자르기", "speed": "배속",
    "zoom": "줌", "broll": "곁들임", "arrow": "화살표",
}


def _format_proposal_line(p: dict) -> str:
    """카드의 proposals 리스트 한 줄 — 사람 읽을 수 있는 요약."""
    action = _ACTION_LABEL_KO.get(p.get("action", ""), p.get("action", "?"))
    eff_type = _TYPE_LABEL_KO.get(p.get("type", ""), p.get("type", ""))
    payload = p.get("payload", {}) or {}
    if p.get("action") == "remove":
        eid = payload.get("effect_id", "?")
        return f"• {action}: 효과 {eid}"
    if p.get("action") == "modify":
        eid = payload.get("effect_id", "?")
        keys = [k for k in payload.keys() if k != "effect_id"]
        return f"• {action}: 효과 {eid} ({', '.join(keys)})"
    # add
    in_ms = payload.get("in_ms", 0)
    out_ms = payload.get("out_ms", 0)
    detail = f"{in_ms}ms~{out_ms}ms"
    if payload.get("text"):
        text = str(payload["text"])
        if len(text) > 30:
            text = text[:27] + "…"
            detail += f" \"{text}\""
        else:
            detail += f" \"{text}\""
    elif payload.get("rate"):
        detail += f" rate={payload['rate']}"
    elif payload.get("src"):
        src = str(payload["src"]).split("/")[-1].split("\\")[-1]
        detail += f" src={src}"
    return f"• {action} {eff_type}: {detail}"


class _MessageBubble(QFrame):
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
                    # QLabel.selectedText() 는 line separator 로   (paragraph sep)
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


# Whisper 모델 옵션 — (model_size, display_label, size_mb, description).
_WHISPER_MODEL_OPTIONS: list[tuple[str, str, int, str]] = [
    ("tiny",     "tiny",     39,   "가장 가벼움, 정확도 낮음"),
    ("base",     "base",     74,   "균형 — 한국어 권장"),
    ("small",    "small",    244,  "정확도 더 좋음"),
    ("medium",   "medium",   769,  "한국어 강함, 다소 느림"),
    ("large-v3", "large-v3", 1550, "최고 정확도, 매우 무거움"),
]


class _WhisperDownloadCard(QFrame):
    """Whisper 모델 다운로드 동의 카드 — Claude 의 download_whisper_model 호출 시.

    카드에 모델 크기 드롭다운 — Claude 가 요청한 크기가 기본 선택. 사용자가 다른
    크기로 변경 가능. [✓ 다운로드] 클릭 시 *선택된 크기* 가 실제 다운로드 됨.
    Claude 권한 없이 사용자 클릭만 실제 트리거.
    """

    download_clicked = Signal(str)    # 선택된 model_size 전달.
    cancel_clicked = Signal()

    def __init__(
        self,
        requested_size: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background:#1a1530;color:#ddd6fe;border:1px solid #a78bfa;"
            "border-radius:8px;padding:10px 12px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)

        title = QLabel("📥 Whisper 자막 모델 다운로드")
        title.setStyleSheet("color:#c4b5fd;font-weight:bold;font-size:13px;")
        title.setWordWrap(True)
        lay.addWidget(title)

        info = QLabel(
            "Claude 가 영상 자막 추출을 위해 모델 다운로드를 요청합니다. "
            "원하는 크기를 골라주세요 — 작을수록 빠르지만 정확도 낮음, "
            "클수록 정확하지만 디스크/메모리 더 씀. 한 번 받으면 재사용."
        )
        info.setStyleSheet("color:#ddd6fe;font-size:11px;")
        info.setWordWrap(True)
        lay.addWidget(info)

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        size_label = QLabel("모델 크기:")
        size_label.setStyleSheet("color:#c4b5fd;font-size:11px;")
        self._size_combo = QComboBox()
        for model_size, display, mb, desc in _WHISPER_MODEL_OPTIONS:
            self._size_combo.addItem(
                f"{display} (~{mb}MB — {desc})", userData=model_size,
            )
        # Claude 가 요청한 크기를 기본 선택.
        for i, (ms, _, _, _) in enumerate(_WHISPER_MODEL_OPTIONS):
            if ms == requested_size:
                self._size_combo.setCurrentIndex(i)
                break
        self._size_combo.setStyleSheet(
            "QComboBox{background:#1e1b4b;color:#ddd6fe;border:1px solid #a78bfa;"
            "border-radius:4px;padding:3px 6px;font-size:11px;}"
        )
        size_row.addWidget(size_label)
        size_row.addWidget(self._size_combo, 1)
        lay.addLayout(size_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#a5b4fc;font-size:11px;font-style:italic;")
        self._status.setVisible(False)
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._dl_btn = QPushButton("✓ 다운로드")
        self._dl_btn.setStyleSheet(
            "QPushButton{background:#7c3aed;color:white;border:none;border-radius:4px;padding:6px 12px;font-weight:bold;}"
            "QPushButton:hover{background:#6d28d9;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._dl_btn.clicked.connect(self._on_download)
        self._cancel_btn = QPushButton("✗ 취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:white;border:none;border-radius:4px;padding:6px 12px;}"
            "QPushButton:hover{background:#991b1b;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._dl_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        self._decided = False

    def _on_download(self) -> None:
        if self._decided:
            return
        self._decided = True
        chosen = self._size_combo.currentData() or "base"
        self._dl_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._size_combo.setEnabled(False)
        self._status.setText(f"⏳ '{chosen}' 다운로드 중… (네트워크 속도에 따라 수 초~수 분)")
        self._status.setVisible(True)
        self.download_clicked.emit(str(chosen))

    def _on_cancel(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._dl_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._size_combo.setEnabled(False)
        self.cancel_clicked.emit()

    def mark_resolved(self, outcome: str, message: str = "") -> None:
        self._decided = True
        self._dl_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._size_combo.setEnabled(False)
        if outcome == "done":
            self._dl_btn.setText("✓ 다운로드 완료")
            self._status.setText(message or "디스크에 저장됨.")
            self._status.setVisible(True)
        elif outcome == "failed":
            self._dl_btn.setText("✗ 실패")
            self._status.setText(f"다운로드 실패: {message}")
            self._status.setVisible(True)
        elif outcome == "canceled":
            self._cancel_btn.setText("✗ 취소됨")


class _ProposalsPreviewCard(QFrame):
    """propose_* 큐의 변경 사항을 미리 보여주고 적용/취소 받는 카드 (interactive bubble).

    Apply / Cancel 버튼 클릭 시 시그널 emit. 한 번 클릭되면 버튼 비활성화 (재클릭 방지).
    """

    apply_clicked = Signal()
    cancel_clicked = Signal()

    def __init__(
        self,
        proposals: list[dict],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(_BUBBLE_STYLES["proposals_preview"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)

        title = QLabel(f"📝 Claude 의 편집 제안 {len(proposals)}개 — 적용할까요?")
        title.setStyleSheet("color:#7dd3fc;font-weight:bold;")
        title.setWordWrap(True)
        lay.addWidget(title)

        list_text = "\n".join(_format_proposal_line(p) for p in proposals)
        body = QLabel(list_text)
        body.setStyleSheet("color:#dbeafe;font-family:Consolas,monospace;font-size:11px;")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(body)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._apply_btn = QPushButton("✓ 적용")
        self._apply_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;border:none;border-radius:4px;padding:6px 12px;font-weight:bold;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._apply_btn.clicked.connect(self._on_apply)
        self._cancel_btn = QPushButton("✗ 취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:white;border:none;border-radius:4px;padding:6px 12px;}"
            "QPushButton:hover{background:#991b1b;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        self._decided = False

    def _on_apply(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._lock()
        self.apply_clicked.emit()

    def _on_cancel(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._lock()
        self.cancel_clicked.emit()

    def _lock(self) -> None:
        self._apply_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)

    def mark_resolved(self, outcome: str) -> None:
        """외부에서 (다른 경로로 적용/취소된 경우) 카드 상태 표시."""
        self._decided = True
        self._lock()
        if outcome == "applied":
            self._apply_btn.setText("✓ 적용됨")
        elif outcome == "canceled":
            self._cancel_btn.setText("✗ 취소됨")


class _PlanCard(QFrame):
    """편집 plan 카드 — submit_plan 도구가 emit 한 (plan_id, summary, markdown) 표시.

    상태: pending → (approved | rejected).
    ✓ → approved 시그널 + 헤더에 (진행 중) 표시.
    ✗ → textarea + [전송]/[그냥 닫기] 등장. 둘 다 rejected(reason) emit (전송=입력 내용, 그냥 닫기="").
    mark_externally_resolved — PlanGate.cancel_all 처럼 외부에서 결정된 경우.
    """

    approved = Signal()
    rejected = Signal(str)   # reason — "" 면 사유 없이 거부.

    def __init__(
        self,
        plan_id: str,
        summary: str,
        markdown: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._plan_id = plan_id
        self._summary = summary
        self.setStyleSheet(_BUBBLE_STYLES["plan_card"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)

        # 헤더 — 📋 아이콘 + summary + ✓/✗ 버튼 같은 줄.
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        self._title = QLabel(f"📋 {summary}")
        self._title.setStyleSheet("color:#7dd3fc;font-weight:bold;")
        self._title.setWordWrap(True)
        header_row.addWidget(self._title, 1)

        self._approve_btn = QPushButton("✓ 진행")
        self._approve_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;border:none;"
            "border-radius:4px;padding:6px 12px;font-weight:bold;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._approve_btn.clicked.connect(self._on_approve)
        self._reject_btn = QPushButton("✗ 취소")
        self._reject_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:white;border:none;"
            "border-radius:4px;padding:6px 12px;}"
            "QPushButton:hover{background:#991b1b;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._reject_btn.clicked.connect(self._on_reject)
        header_row.addWidget(self._approve_btn)
        header_row.addWidget(self._reject_btn)
        lay.addLayout(header_row)

        # 본문 — markdown.
        self._body = QLabel(markdown)
        self._body.setStyleSheet("color:#e0f2fe;")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.MarkdownText)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        lay.addWidget(self._body)

        # 거부 사유 입력 영역 — 초기엔 숨김.
        self._reason_label = QLabel("거부 사유 (선택):")
        self._reason_label.setStyleSheet("color:#fca5a5;font-size:11px;")
        self._reason_label.setVisible(False)
        lay.addWidget(self._reason_label)

        self._reason_input = QPlainTextEdit()
        self._reason_input.setStyleSheet(
            "QPlainTextEdit{background:#0f172a;color:#e0f2fe;border:1px solid #334155;"
            "border-radius:4px;padding:4px 6px;font-size:12px;}"
        )
        self._reason_input.setFixedHeight(60)
        self._reason_input.setVisible(False)
        lay.addWidget(self._reason_input)

        reason_btn_row = QHBoxLayout()
        reason_btn_row.setSpacing(6)
        self._send_reason_btn = QPushButton("전송")
        self._send_reason_btn.setStyleSheet(
            "QPushButton{background:#1e293b;color:#e0f2fe;border:1px solid #475569;"
            "border-radius:4px;padding:4px 10px;}"
            "QPushButton:hover{background:#334155;}"
        )
        self._send_reason_btn.clicked.connect(self._on_send_reason)
        self._send_reason_btn.setVisible(False)
        self._close_no_reason_btn = QPushButton("그냥 닫기")
        self._close_no_reason_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#94a3b8;border:1px solid #475569;"
            "border-radius:4px;padding:4px 10px;}"
            "QPushButton:hover{background:#1e293b;}"
        )
        self._close_no_reason_btn.clicked.connect(self._on_close_no_reason)
        self._close_no_reason_btn.setVisible(False)
        reason_btn_row.addWidget(self._send_reason_btn)
        reason_btn_row.addWidget(self._close_no_reason_btn)
        reason_btn_row.addStretch(1)
        lay.addLayout(reason_btn_row)

        self._decided = False

    def plan_id(self) -> str:
        return self._plan_id

    def _on_approve(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._lock_main_buttons()
        # 헤더에 "(진행 중)" 추가 (중복 방지).
        suffix = " (진행 중)"
        if suffix not in self._title.text():
            self._title.setText(self._title.text() + suffix)
        self.approved.emit()

    def _on_reject(self) -> None:
        if self._decided:
            return
        # decided 는 아직 — textarea 보여주고 [전송]/[그냥 닫기] 기다림.
        self._lock_main_buttons()
        self._reason_label.setVisible(True)
        self._reason_input.setVisible(True)
        self._send_reason_btn.setVisible(True)
        self._close_no_reason_btn.setVisible(True)
        self._reason_input.setFocus()

    def _on_send_reason(self) -> None:
        if self._decided:
            return
        self._decided = True
        reason = self._reason_input.toPlainText().strip()
        self._send_reason_btn.setEnabled(False)
        self._close_no_reason_btn.setEnabled(False)
        self._reason_input.setReadOnly(True)
        self.rejected.emit(reason)

    def _on_close_no_reason(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._send_reason_btn.setEnabled(False)
        self._close_no_reason_btn.setEnabled(False)
        self._reason_input.setReadOnly(True)
        self.rejected.emit("")

    def _lock_main_buttons(self) -> None:
        self._approve_btn.setEnabled(False)
        self._reject_btn.setEnabled(False)

    def mark_externally_resolved(self, outcome: str) -> None:
        """외부에서 (예: cancel_all) 결정된 경우 — 버튼 비활성 + 헤더 갱신.

        outcome: 'approved' / 'rejected' / 'cancelled'.
        """
        self._decided = True
        self._lock_main_buttons()
        self._send_reason_btn.setEnabled(False)
        self._close_no_reason_btn.setEnabled(False)
        suffix = {"approved": " (진행 중)", "rejected": " (거부됨)", "cancelled": " (취소됨)"}.get(outcome, "")
        if suffix and suffix not in self._title.text():
            self._title.setText(self._title.text() + suffix)


class _ChatInputEdit(QPlainTextEdit):
    """Chat용 멀티라인 입력 — Enter=보내기, Shift+Enter=줄바꿈.

    QLineEdit 와 달리 긴 텍스트 입력 시 줄바꿈으로 전체 내용이 보임. 높이는
    내용에 따라 1~5 줄 사이로 자동 조절.

    한글 IME 처리: Qt 의 QPlainTextEdit 는 document 가 비어있을 때 placeholder 를
    그림. 한글 IME 조합 중 (예: 'ㄱ' 만 입력) 에는 글자가 document 가 아닌 IME preedit
    영역에 있어서 document 는 비어있는 상태 → placeholder 가 입력 글자와 겹쳐 보임.
    `inputMethodEvent` 를 가로채 preedit 가 있으면 placeholder 를 임시로 "" 로 바꿈.
    """

    submit_requested = Signal()
    # Ctrl+V 등으로 클립보드 이미지 붙여넣음 — PNG bytes 한 장. ChatPanel 이 받아 pending 첨부.
    image_pasted = Signal(bytes)

    _MIN_LINES = 1
    _MAX_LINES = 5

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _sz: self._adjust_height()
        )
        # IME 조합 중 placeholder 숨기기 위한 원본 저장.
        self._original_placeholder: str = ""
        # 문서가 비워질 때 (backspace 등) placeholder 복원.
        self.textChanged.connect(self._restore_placeholder_if_empty)
        self._adjust_height()

    def setPlaceholderText(self, text: str) -> None:
        """공개 API 오버라이드 — 외부에서 placeholder 변경 시 *원본* 도 기억."""
        self._original_placeholder = text or ""
        super().setPlaceholderText(text)

    def inputMethodEvent(self, event) -> None:
        """한글 IME 조합 이벤트 — preedit 가 있는 동안 placeholder 숨김.

        - preedit 비어있지 않음 (예: 'ㄱ' 조합 중): placeholder = "".
        - preedit 비어있고 document 도 비어있음 (조합 취소 / 외부 reset): placeholder 복원.
        - preedit 비어있고 document 비어있지 않음 (commit 직후): Qt 가 자동으로 placeholder
          숨기므로 우리는 손대지 않음.
        """
        super().inputMethodEvent(event)
        preedit = event.preeditString() if event is not None else ""
        if preedit:
            super().setPlaceholderText("")
        elif not self.toPlainText():
            super().setPlaceholderText(self._original_placeholder)

    def _restore_placeholder_if_empty(self) -> None:
        """document 가 비워지면 (backspace 등) placeholder 다시 보이게."""
        if not self.toPlainText():
            super().setPlaceholderText(self._original_placeholder)

    def insertFromMimeData(self, source) -> None:
        """Ctrl+V — 이미지면 첨부, 텍스트면 일반 paste. **텍스트 우선**.

        Qt 의 markdown QLabel 등은 클립보드에 텍스트 + HTML 을 같이 올림. 일부 환경에선
        이미지 미리보기도 함께 들어가는데, 우리가 이미지 우선이면 사용자가 채팅 본문을
        복사해 paste 할 때 image-only paste 로 잘못 잡힘 (사용자 보고 2026-05-13).
        텍스트가 있으면 텍스트, 없을 때만 이미지 → 첨부.
        """
        try:
            formats = list(source.formats()) if source else []
            _chat_log.info(
                "Ctrl+V formats=%s has_text=%s has_image=%s text_len=%d",
                formats,
                bool(source and source.hasText()),
                bool(source and source.hasImage()),
                len(source.text()) if source and source.hasText() else 0,
            )
        except Exception:
            pass
        if source is None:
            super().insertFromMimeData(source)
            return
        # 텍스트가 있으면 무조건 텍스트 paste — 채팅 본문 복사 시나리오 보호.
        if source.hasText() and source.text().strip():
            super().insertFromMimeData(source)
            return
        # 이미지-only paste (스크린샷 클립보드 등) → 첨부로 emit.
        if source.hasImage():
            qimg = QImage(source.imageData())
            if not qimg.isNull():
                buf = QBuffer()
                buf.open(QIODevice.WriteOnly)
                if qimg.save(buf, "PNG"):
                    _chat_log.info("Ctrl+V: image attached (%d bytes)", len(buf.data()))
                    self.image_pasted.emit(bytes(buf.data()))
                    return
        super().insertFromMimeData(source)

    def _adjust_height(self) -> None:
        fm_h = self.fontMetrics().lineSpacing()
        margins = self.contentsMargins()
        frame = int(self.frameWidth()) * 2
        lines = max(self._MIN_LINES, min(self._MAX_LINES, self.document().blockCount()))
        h = fm_h * lines + margins.top() + margins.bottom() + frame + 6
        self.setFixedHeight(h)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)   # 줄바꿈.
            else:
                self.submit_requested.emit()
                return
        else:
            super().keyPressEvent(event)


class ChatPanel(QDockWidget):
    """Claude 와의 대화 패널. MainWindow 에 right-dock 으로 부착."""

    user_submitted = Signal(str, list)         # (prompt, pasted_image_bytes_list)
    model_changed = Signal(str)                # 사용자가 모델 변경 (model_id)
    cancel_requested = Signal()                # 사용자가 진행 중 응답 취소
    proposals_apply_confirmed = Signal()       # 미리보기 카드의 적용 클릭
    proposals_apply_canceled = Signal()        # 미리보기 카드의 취소 클릭
    show_thinking_changed = Signal(bool)       # 추론 보기 토글
    whisper_download_confirmed = Signal(str)   # Whisper 다운로드 카드 [다운로드] 클릭 (chosen model_size)
    whisper_download_canceled = Signal()       # Whisper 다운로드 카드 [취소] 클릭
    # 슬래시 명령 — runtime 측에 알려야 client 재연결/요약 트리거 가능.
    clear_requested = Signal()                 # /clear — 새 세션 시작 (client disconnect)
    compact_requested = Signal()               # /compact — Claude 에게 요약 부탁

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        initial_model_id: Optional[str] = None,
        initial_show_thinking: bool = True,
        plan_gate: Optional[PlanGate] = None,
        agent: Optional["object"] = None,
    ) -> None:
        # NOTE: agent 파라미터는 의존성 역전 원칙 (docstring 참조) 의 의도적 예외.
        # set_model 가드가 model 변경을 차단했는지 ChatPanel 이 직접 알아야 콤보 fallback
        # 가능 → AgentRuntime 의 _model 상태를 즉시 비교해야 함. signal/slot 만으로는
        # synchronous 결과 회신이 어려움. MainWindow 가 agent=runtime 으로 주입.
        super().__init__("Claude 에이전트", parent)
        self.setObjectName("AgentChatPanel")
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        # AgentRuntime 참조 — 콤보 fallback 시 set_model 직접 호출 + _model 비교 용.
        self._agent = agent
        # 채팅 디버그 로그 활성화 — 첫 ChatPanel 생성 시 한 번만 파일 핸들러 부착.
        _ensure_chat_log_handler()
        _chat_log.info("ChatPanel constructed model=%s show_thinking=%s",
                       initial_model_id, initial_show_thinking)

        body = QWidget(self)
        body.setMinimumWidth(320)
        v = QVBoxLayout(body)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # ---- 메시지 리스트 ----
        # 채팅 표준: stretch 를 *맨 위*에 둬서 메시지가 아래쪽 정렬 (WhatsApp / Slack 스타일).
        # 콘텐츠가 viewport 보다 짧을 때 빈 공간이 *위*에 생기고, 콘텐츠가 늘어나면 아래에서
        # 차오르는 자연스러운 흐름. 이전 (stretch 아래) 은 콘텐츠 위 정렬이라 viewport 아래에
        # 빈 공간이 쌓여 보이는 문제 — 사용자가 "빈곳 늘어남" 으로 인지.
        self._messages_host = QWidget()
        self._messages_lay = QVBoxLayout(self._messages_host)
        # 오른쪽 8px 마진 — scrollbar 가 등장해도 콘텐츠가 scrollbar 와 겹치지 않게.
        # 사용자 보고 (2026-05-13): "스크롤바가 채팅 일부 가린다".
        self._messages_lay.setContentsMargins(0, 0, 8, 0)
        self._messages_lay.setSpacing(4)  # 기본 spacing 더 좁게 (log-line 들 많음).
        self._messages_lay.addStretch(1)
        # stretch index = 0 (맨 위). _insert_bubble 은 stretch *뒤에* 삽입.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # 가로 스크롤 절대 금지 — markdown 긴 줄이 wrap 되지 않고 viewport 넘어가던 사용자 보고
        # (2026-05-13: "채팅창 줄바꿈이 안되"). horizontal AsNeeded 가 켜져 있으면 QLabel
        # wordWrap 이 scrollbar 가 처리할 거라 생각해서 wrap 안 함. AlwaysOff 로 강제하면
        # widgetResizable=True 와 결합해 inner widget 폭 = viewport 폭 → wrap 작동.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._messages_host)
        self._scroll.setStyleSheet("QScrollArea{background:#0a0f1e;border:none;}")
        # viewport resize 가 일어날 때 inner widget 의 maxWidth 를 viewport 폭으로 명시 강제.
        # widgetResizable=True 만으로는 안전하지 않음 — tool_result 같이 wordWrap 무시하는
        # 단일라인 sizeHint 가 wide 일 때 inner widget 이 sizeHint 따라 wide 해질 수 있음.
        # 명시 maxWidth = 모든 자식 bubble 의 강제 wrap 보장.
        self._scroll.viewport().installEventFilter(self)
        v.addWidget(self._scroll, 1)
        # 자동 스크롤: 사용자가 맨 아래 있을 때만 새 메시지에 자동 따라감.
        # 위로 스크롤해 과거 메시지 읽는 중이면 streaming 으로 강제 점프 안 함.
        # rangeChanged 가 layout 완료 후 발화 — _scroll_to_bottom 보다 정확.
        self._auto_scroll = True
        self._scroll.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        # ---- 상태 라벨 (진행 중 / 완료 단발 메시지) ----
        self._status = QLabel("")
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;padding:2px 4px;")
        self._status.setWordWrap(True)   # dock 좁아도 잘리지 않음.
        self._status.setVisible(False)
        v.addWidget(self._status)

        # 컨텍스트 바 → 모델 row 의 동그라미 아이콘으로 이동 (아래 model_row 참조).

        # ---- 모델 선택 + ctx 동그라미 + 추론 보기 (한 줄, compact) ----
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        model_row.setContentsMargins(0, 0, 0, 0)
        self._model_combo = QComboBox()
        # ModelRegistry 기반 — built-in 4개 (Sonnet/Opus/Haiku/Qwen) 자동 표시.
        # MODEL_OPTIONS 하드코딩 fallback 은 더 이상 사용 안 함 (backward-compat 으로 상수만 유지).
        self._model_registry = ModelRegistry()
        for meta in self._model_registry.all_models():
            display = meta.display_name
            # claude 외 runtime — 의존성 미설치면 "(설치 필요)" 라벨 + 사용자가 클릭하면
            # set_model 가드가 차단 → 콤보 fallback. 의존성 표시는 정보용일 뿐 disable 안 함.
            if meta.runtime != "claude" and not check_runtime_available(meta.runtime):
                display = f"{display} (설치 필요)"
            self._model_combo.addItem(display, userData=meta.id)
        # 초기 인덱스 — initial_model_id (저장된 ID) 매칭, 없으면 agent 의 현재 model,
        # 그것도 없으면 DEFAULT_MODEL_ID (Sonnet).
        desired_id = initial_model_id
        if not desired_id and self._agent is not None:
            desired_id = getattr(self._agent, "_model", None)
        if not desired_id:
            desired_id = DEFAULT_MODEL_ID
        initial_idx = 0
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == desired_id:
                initial_idx = i
                break
        self._model_combo.setCurrentIndex(initial_idx)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._model_combo.setStyleSheet(
            "QComboBox{background:#1e293b;color:#e2e8f0;border:1px solid #334155;"
            "border-radius:4px;padding:2px 6px;font-size:11px;}"
        )
        # combo 자체가 가로로 가능한 작게 — 라벨(예: "Sonnet 4.6") 너비만큼.
        self._model_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._model_combo.setMinimumContentsLength(8)
        model_row.addWidget(self._model_combo)

        # 컨텍스트 사용률 동그라미 + % 라벨 — 첫 응답 전엔 숨김, 응답 후 색상 + 숫자.
        self._ctx_dot = QLabel()
        self._ctx_dot.setFixedSize(14, 14)
        self._ctx_dot.setVisible(False)
        self._ctx_dot.setToolTip("")
        self._set_ctx_dot_color("#64748b")
        model_row.addWidget(self._ctx_dot)

        self._ctx_pct_label = QLabel("")
        self._ctx_pct_label.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
        self._ctx_pct_label.setVisible(False)
        model_row.addWidget(self._ctx_pct_label)

        # /clear /compact 버튼 — 슬래시 명령과 동일 흐름. % 라벨 오른쪽에 붙음.
        _slash_btn_style = (
            "QPushButton{background:#1e293b;color:#cbd5e1;border:1px solid #334155;"
            "border-radius:3px;padding:1px 6px;font-size:11px;}"
            "QPushButton:hover{background:#334155;color:#f1f5f9;}"
        )
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setToolTip("/clear — 대화 초기화, 새 세션 시작")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setStyleSheet(_slash_btn_style)
        self._clear_btn.clicked.connect(lambda: self._handle_slash_command("/clear"))
        model_row.addWidget(self._clear_btn)

        self._compact_btn = QPushButton("Compact")
        self._compact_btn.setToolTip("/compact — Claude 에게 지금까지 대화 요약 요청")
        self._compact_btn.setCursor(Qt.PointingHandCursor)
        self._compact_btn.setStyleSheet(_slash_btn_style)
        self._compact_btn.clicked.connect(lambda: self._handle_slash_command("/compact"))
        model_row.addWidget(self._compact_btn)

        model_row.addStretch(1)

        # 추론(thinking) 표시 ON/OFF — Claude 의 내부 추론 + 도구 호출/결과 박스를 가리거나 보임.
        self._thinking_check = QCheckBox("추론 보기")
        self._thinking_check.setChecked(bool(initial_show_thinking))
        self._thinking_check.setStyleSheet(
            "QCheckBox{color:#94a3b8;font-size:11px;}"
            "QCheckBox::indicator{width:13px;height:13px;}"
        )
        self._thinking_check.setToolTip(
            "추론 보기: ON 이면 Claude 의 내부 사고 + 도구 호출/결과 표시. OFF 면 대화만."
        )
        self._thinking_check.toggled.connect(self._on_show_thinking_toggled)
        model_row.addWidget(self._thinking_check)
        v.addLayout(model_row)

        # 첨부 표시 — Ctrl+V 로 이미지 붙여넣으면 "📎 N개 첨부됨 [✕ 취소]" 표시.
        # QFrame 안에 라벨 + 취소 버튼 — 사용자가 잘못 paste 한 이미지 제거 가능.
        self._attach_row = QFrame()
        self._attach_row.setStyleSheet(
            "QFrame{background:#1e1b4b;border-radius:4px;}"
        )
        _attach_lay = QHBoxLayout(self._attach_row)
        _attach_lay.setContentsMargins(8, 3, 6, 3)
        _attach_lay.setSpacing(6)
        self._attach_label = QLabel("")
        self._attach_label.setStyleSheet("color:#a5b4fc;font-size:11px;background:transparent;")
        _attach_lay.addWidget(self._attach_label, 1)
        self._attach_cancel_btn = QPushButton("✕ 취소")
        self._attach_cancel_btn.setCursor(Qt.PointingHandCursor)
        self._attach_cancel_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#c4b5fd;border:1px solid #7c3aed;"
            "border-radius:3px;padding:1px 6px;font-size:11px;}"
            "QPushButton:hover{background:#7c3aed;color:white;}"
        )
        self._attach_cancel_btn.clicked.connect(self._on_attach_cancel)
        _attach_lay.addWidget(self._attach_cancel_btn)
        self._attach_row.setVisible(False)
        v.addWidget(self._attach_row)

        # ---- 입력 행 ----
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        input_row.setAlignment(Qt.AlignBottom)
        self._input = _ChatInputEdit()
        self._input.setPlaceholderText(
            "Claude 에게 질문 또는 명령... (Enter=보내기, Shift+Enter=줄바꿈)"
        )
        self._input.setStyleSheet(
            "QPlainTextEdit{background:#0f172a;color:#e2e8f0;border:1px solid #334155;"
            "border-radius:4px;padding:4px 6px;font-size:12px;}"
        )
        self._input.submit_requested.connect(self._on_submit)
        self._send_btn = QPushButton("보내기")
        self._send_btn.clicked.connect(self._on_submit)
        self._cancel_btn = QPushButton("취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:#fef2f2;border:none;border-radius:4px;padding:4px 8px;}"
            "QPushButton:hover{background:#991b1b;}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._cancel_btn.setVisible(False)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn)
        input_row.addWidget(self._cancel_btn)
        v.addLayout(input_row)

        self.setWidget(body)

        # 마지막으로 추가된 assistant / thinking 말풍선 (스트리밍 chunk 누적 대상).
        # 새 사용자 입력 또는 다른 role 메시지(tool_use 등) 도착 시 None 으로 reset.
        # SDK 의 include_partial_messages 가 thinking 도 partial 로 보내므로 누적 필수 —
        # 누적 안 하면 partial 마다 새 박스가 추가돼서 화면이 점프하며 빈 박스가 쌓임.
        self._current_assistant_bubble: Optional[_MessageBubble] = None
        self._current_thinking_bubble: Optional[_MessageBubble] = None
        # 최신 active proposals card — 외부에서 mark_resolved 호출 가능.
        self._active_proposals_card: Optional[_ProposalsPreviewCard] = None
        # 최신 active whisper download card.
        self._active_whisper_card: Optional[_WhisperDownloadCard] = None

        # 대화 영속화 — set_history_path 로 활성화. 메시지 추가마다 디바운스 저장.
        self._history_path: Optional[Path] = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)  # 1초 디바운스.
        self._save_timer.timeout.connect(self._flush_history)

        # 누적 토큰 사용량 — 매 ResultMessage 에 done detail 로 도착.
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        # 최근 턴의 입력 토큰 = 현재 컨텍스트 사용량 근사 (Claude 가 매 턴 전체 대화를 다시 읽음).
        self._last_input_tokens = 0
        # Ctrl+V 로 붙여넣은 PNG bytes 대기열 — 다음 submit 때 전달.
        self._pending_images: list[bytes] = []
        # 입력 위젯의 image_pasted 시그널 연결 — pending 에 추가 + 첨부 표시 갱신.
        self._input.image_pasted.connect(self._on_image_pasted)

        # PlanGate 연결 — plan_submitted 시그널 → _PlanCard 삽입.
        # plan_id → _PlanCard registry — plan_resolved 시 stale card 갱신용.
        self._plan_cards: dict[str, "_PlanCard"] = {}
        self._plan_gate: Optional[PlanGate] = plan_gate
        if self._plan_gate is not None:
            self._plan_gate.plan_submitted.connect(self._on_plan_submitted)
            self._plan_gate.plan_resolved.connect(self._on_plan_resolved)

    # ---- 외부 진입점 ----
    def append_message(self, msg: AgentMessage) -> None:
        """AgentRuntime.message_received 와 직접 연결 가능.

        thinking / tool_use / tool_result 는 새 말풍선으로. assistant 는 연속 청크
        면 이전 말풍선에 누적. tool_result 의 image_bytes 있으면 인라인 표시.
        proposals_preview 는 interactive 카드 (적용/취소 버튼) 로 표시.
        """
        # 추론 표시 OFF 면 thinking 뿐 아니라 도구 호출/결과도 숨김 — 사용자/Claude 대화만 보기.
        # tool_use/tool_result 는 Claude 의 *내부 작업* 이라 일반 대화 흐름에서 잡음으로 인식.
        if (msg.role in ("thinking", "tool_use", "tool_result")
                and not self._thinking_check.isChecked()):
            return
        if msg.role == "proposals_preview" and msg.proposals is not None:
            card = _ProposalsPreviewCard(msg.proposals)
            card.apply_clicked.connect(self.proposals_apply_confirmed)
            card.cancel_clicked.connect(self.proposals_apply_canceled)
            self._insert_bubble(card)
            self._active_proposals_card = card
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self._scroll_to_bottom()
            return
        if msg.role == "whisper_download_request":
            # text 에 "model_size=base" 형식으로 Claude 가 제안한 크기.
            meta = self._parse_whisper_meta(msg.text)
            card = _WhisperDownloadCard(meta["model_size"])
            card.download_clicked.connect(self.whisper_download_confirmed)
            card.cancel_clicked.connect(self.whisper_download_canceled)
            self._insert_bubble(card)
            self._active_whisper_card = card
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self._scroll_to_bottom()
            return
        # 같은 role 연속 streaming chunk 면 마지막 bubble 에 누적.
        if (msg.role == "assistant"
                and self._current_assistant_bubble is not None
                and not msg.image_bytes):
            self._current_assistant_bubble.append_text(msg.text)
        elif (msg.role == "thinking"
                and self._current_thinking_bubble is not None):
            self._current_thinking_bubble.append_text(msg.text)
        else:
            bubble = _MessageBubble(
                msg.role, msg.text,
                image_bytes=msg.image_bytes, image_mime=msg.image_mime,
            )
            self._insert_bubble(bubble)
            if msg.role == "assistant":
                self._current_assistant_bubble = bubble
                self._current_thinking_bubble = None
            elif msg.role == "thinking":
                self._current_thinking_bubble = bubble
                self._current_assistant_bubble = None
            else:
                # tool_use / tool_result / system / error 등 — streaming 누적 대상 아님.
                self._current_assistant_bubble = None
                self._current_thinking_bubble = None
        self._scroll_to_bottom()
        self._schedule_history_save()

    def mark_proposals_resolved(self, outcome: str) -> None:
        """외부에서 적용/취소 처리 완료 후 카드 상태 갱신.

        outcome: "applied" / "canceled".
        """
        if self._active_proposals_card is not None:
            self._active_proposals_card.mark_resolved(outcome)
            self._active_proposals_card = None

    @Slot(str, str)
    def mark_whisper_download_resolved(self, outcome: str, message: str = "") -> None:
        """Whisper 다운로드 카드 상태 갱신. outcome: 'done' / 'failed' / 'canceled'.

        @Slot 데코레이터로 QMetaObject.invokeMethod 에서 호출 가능하게 등록.
        """
        if self._active_whisper_card is not None:
            self._active_whisper_card.mark_resolved(outcome, message)
            self._active_whisper_card = None

    @staticmethod
    def _parse_whisper_meta(text: str) -> dict:
        """text 'model_size=base' → {model_size}."""
        out = {"model_size": "base"}
        for part in (text or "").split():
            if "=" in part:
                k, v = part.split("=", 1)
                if k == "model_size":
                    out["model_size"] = v
        return out

    def append_event(self, evt: AgentEvent) -> None:
        """AgentRuntime.event_received 와 직접 연결 가능. 상태 라벨 + 보내기/취소 전환."""
        if evt.kind == "started":
            self._status.setText("Claude 가 응답 중… (도구 호출/추론 과정도 아래에 표시됨)")
            self._status.setVisible(True)
            self._send_btn.setVisible(False)
            self._cancel_btn.setVisible(True)
        elif evt.kind == "tool_use":
            self._status.setText(f"🔧 {evt.detail}")
            self._status.setVisible(True)
        elif evt.kind == "tool_result":
            pass
        elif evt.kind == "done":
            # detail 포맷 "in=N out=M" — 누적 토큰 + last_input 갱신.
            self._update_token_totals(evt.detail)
            self._update_ctx_bar()
            # 상태 라벨은 단발 메시지만 (컨텍스트는 ctx_bar 가 영속 표시).
            self._status.setText("완료")
            self._send_btn.setVisible(True)
            self._cancel_btn.setVisible(False)
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
        elif evt.kind == "error":
            err_bubble = _MessageBubble("error", f"⚠ 오류: {evt.detail}")
            self._insert_bubble(err_bubble)
            self._status.setVisible(False)
            self._send_btn.setVisible(True)
            self._cancel_btn.setVisible(False)
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self._scroll_to_bottom()

    def message_count(self) -> int:
        """테스트용 — addStretch 1개 제외한 실제 말풍선 개수."""
        return max(0, self._messages_lay.count() - 1)

    def last_bubble_role(self) -> Optional[str]:
        """테스트용 — 가장 최근 말풍선의 role.

        stretch 는 index 0, 말풍선은 그 뒤에 차례로 append → 마지막 = count()-1.
        """
        idx = self._messages_lay.count() - 1
        if idx <= 0:
            return None
        item = self._messages_lay.itemAt(idx)
        w = item.widget() if item else None
        return w.role() if isinstance(w, _MessageBubble) else None

    def current_model_id(self) -> str:
        return self._model_combo.currentData() or DEFAULT_MODEL_ID

    def show_thinking(self) -> bool:
        return self._thinking_check.isChecked()

    # ---- 대화 영속화 ----
    def set_history_path(self, path: Path) -> None:
        """디스크 경로 설정 + 즉시 로드."""
        self._history_path = Path(path)
        history = load_history(self._history_path)
        if history:
            sep = AgentMessage(
                role="system",
                text=f"이전 세션의 대화 {len(history)}건 복원됨.",
            )
            self.append_message(sep)
            for role, text in history:
                self.append_message(AgentMessage(role=role, text=text))

    def flush_history_now(self) -> None:
        """앱 종료 시 호출 — 디바운스 우회 즉시 저장."""
        self._save_timer.stop()
        self._flush_history()

    def _schedule_history_save(self) -> None:
        if self._history_path is not None:
            self._save_timer.start()  # 기존 타이머 리스타트.

    def _flush_history(self) -> None:
        if self._history_path is None:
            return
        try:
            messages: list[tuple[str, str]] = []
            # stretch 는 index 0, 말풍선은 그 뒤부터 — 순서대로 (oldest first).
            for i in range(1, self._messages_lay.count()):
                item = self._messages_lay.itemAt(i)
                w = item.widget() if item else None
                if isinstance(w, _MessageBubble) and w.role() in PERSISTABLE_ROLES:
                    messages.append((w.role(), w._raw_text))
            save_history(self._history_path, messages)
        except Exception:
            import logging
            logging.exception("chat history save failed")

    # ---- 내부 ----
    def _on_show_thinking_toggled(self, checked: bool) -> None:
        self.show_thinking_changed.emit(bool(checked))

    def _on_cancel_clicked(self) -> None:
        """진행 중 응답 취소 — runtime 이 task 를 cancel 시키고 error 이벤트로 종료."""
        self.cancel_requested.emit()
        self._cancel_btn.setEnabled(False)   # 다음 done/error 시 다시 활성.
        self._status.setText("취소 중…")

    def _update_token_totals(self, detail: str) -> None:
        """done detail ('in=1234 out=567 last_in=12345') 파싱.

        - in:       이 응답 안 모든 API 호출의 input_tokens 합 (누적용).
        - out:      output_tokens 합 (누적용).
        - last_in:  *마지막* API 호출 한 번의 context size (컨텍스트 % 용 — 200k 안에서 정확).

        SDK 가 ResultMessage.usage 에 응답 전체를 합산해서 줘서, 도구 호출 N번이면 input
        토큰이 N배 부풀려짐. last_in 은 마지막 AssistantMessage 의 usage 에서 별도 추출 —
        진짜 컨텍스트 윈도 사용량과 일치.
        """
        if not detail:
            return
        last_in_seen = False
        try:
            for part in detail.split():
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                n = int(v)
                if k == "in":
                    self._total_input_tokens += n
                    # last_in 이 따로 안 오면 backward compat 으로 in 을 last 로 사용.
                    if not last_in_seen:
                        self._last_input_tokens = n
                elif k == "out":
                    self._total_output_tokens += n
                elif k == "last_in":
                    self._last_input_tokens = n
                    last_in_seen = True
        except ValueError:
            pass

    def _context_summary(self) -> str:
        """상태 라벨 끝에 붙는 ' · 컨텍스트 12.3k/200k (6%)' 문자열.

        last_input_tokens 가 0 이면 (아직 응답 없음) 빈 string.
        """
        if self._last_input_tokens <= 0:
            return ""
        limit = _context_limit_for(self.current_model_id())
        pct = (self._last_input_tokens / limit) * 100.0 if limit > 0 else 0.0
        def _fmt(n: int) -> str:
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
        warn = " ⚠" if pct >= 70 else ""
        return f" · ctx {_fmt(self._last_input_tokens)}/{_fmt(limit)} ({pct:.0f}%){warn}"

    def _set_ctx_dot_color(self, hex_color: str) -> None:
        """동그라미 색 — stylesheet 로 원형 + 색 + 살짝 border."""
        self._ctx_dot.setStyleSheet(
            f"background:{hex_color};border:1px solid #0f172a;border-radius:7px;"
        )

    def _update_ctx_bar(self) -> None:
        """컨텍스트 동그라미 + % 라벨 — 첫 응답 후 영속 표시.

        색 = 사용률 (녹/노/빨). 라벨 = "X%" 숫자. tooltip = 상세 (ctx X/Y · 누적 in/out).
        """
        if self._last_input_tokens <= 0 and self._total_input_tokens <= 0:
            self._ctx_dot.setVisible(False)
            self._ctx_pct_label.setVisible(False)
            return
        limit = _context_limit_for(self.current_model_id())
        pct = (self._last_input_tokens / limit) * 100.0 if limit > 0 else 0.0
        def _fmt(n: int) -> str:
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
        warn = " ⚠" if pct >= 70 else ""
        tooltip = (
            f"컨텍스트: {_fmt(self._last_input_tokens)} / {_fmt(limit)} ({pct:.0f}%){warn}\n"
            f"누적: in={self._total_input_tokens:,}  out={self._total_output_tokens:,}\n"
            f"70% 이상이면 /compact 또는 /clear 권장."
        )
        self._ctx_dot.setToolTip(tooltip)
        self._set_ctx_dot_color(_ctx_color_for(pct))
        self._ctx_dot.setVisible(True)
        # % 라벨 — 동그라미 색과 글자 색 동조.
        self._ctx_pct_label.setText(f"{pct:.0f}%{warn}")
        self._ctx_pct_label.setStyleSheet(
            f"color:{_ctx_color_for(pct)};font-size:11px;background:transparent;font-weight:600;"
        )
        self._ctx_pct_label.setToolTip(tooltip)
        self._ctx_pct_label.setVisible(True)

    def _refresh_context_status(self) -> None:
        """수동 trigger — /clear 직후처럼 done 이벤트 없이 갱신 필요한 경우."""
        self._update_ctx_bar()
        if self._last_input_tokens > 0 or self._total_output_tokens > 0:
            self._status.setText(f"준비됨{self._context_summary()}")
            self._status.setVisible(True)
        else:
            self._status.setVisible(False)

    def _on_model_changed(self, idx: int) -> None:
        model_id = self._model_combo.itemData(idx)
        if not model_id:
            return
        # agent 가 주입된 경우 — set_model 직접 호출 후 _model 비교로 가드 차단 여부 판단.
        # 차단 시 콤보 fallback (signal 도 emit 안 함 — preference 저장 슬롯이 잘못된 ID 받지 않도록).
        if self._agent is not None:
            before = getattr(self._agent, "_model", None)
            self._agent.set_model(str(model_id))
            after = getattr(self._agent, "_model", None)
            if after != model_id:
                # 가드가 model 변경을 차단했음 (warning 시스템 메시지는 runtime 이 이미 emit).
                # 콤보를 이전 모델로 되돌림. signal recursion 방지를 위해 blockSignals.
                for i in range(self._model_combo.count()):
                    if self._model_combo.itemData(i) == before:
                        self._model_combo.blockSignals(True)
                        self._model_combo.setCurrentIndex(i)
                        self._model_combo.blockSignals(False)
                        break
                return
        # 변경 성공 (또는 agent 없는 테스트 fixture) — 시스템 메시지 + 시그널 emit.
        self.append_message(AgentMessage(
            role="system",
            text=f"모델 전환: {self._model_combo.itemText(idx)}",
        ))
        self.model_changed.emit(str(model_id))

    def _on_submit(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        _chat_log.info("submit text_len=%d n_attached_images=%d preview=%r",
                       len(text), len(self._pending_images),
                       (text[:80] + "…") if len(text) > 80 else text)
        self._input.clear()
        self._current_assistant_bubble = None
        self._current_thinking_bubble = None
        # 사용자가 새 메시지 보낼 때는 자동 스크롤 강제 활성 — 답이 보여야 하니까.
        self._auto_scroll = True
        # 슬래시 명령 — Claude 호출 없이 로컬 처리.
        if text.startswith("/"):
            if self._handle_slash_command(text):
                return
            # 알 수 없는 명령은 system 메시지 안내 후 종료.
            self.append_message(AgentMessage(
                role="system",
                text=f"알 수 없는 명령: `{text}`. `/help` 로 사용 가능한 명령 확인.",
            ))
            return
        # pending 이미지 첨부 (Ctrl+V paste) 있으면 같이 전달, 없으면 빈 list.
        images = list(self._pending_images)
        self._pending_images.clear()
        self._refresh_attach_label()
        # 사용자 말풍선은 이미지 썸네일도 같이 보여줌 — 첫 이미지만 (여러 장이면 텍스트로 표기).
        first_img = images[0] if images else None
        msg_text = text
        if len(images) > 1:
            msg_text = f"{text}\n\n[+{len(images) - 1} more images]"
        self.append_message(AgentMessage(
            role="user", text=msg_text,
            image_bytes=first_img, image_mime="image/png" if first_img else None,
        ))
        self.user_submitted.emit(text, images)

    def _handle_slash_command(self, text: str) -> bool:
        """슬래시 명령 처리. True 면 처리됨, False 면 unknown → 안내 메시지.

        /clear   — 모든 말풍선 제거 + 누적 토큰 0 + clear_requested emit (runtime 이 client 끊고
                    다음 send 시 새 세션).
        /compact — compact_requested emit (runtime 이 Claude 에게 요약 부탁 + history 교체).
        /help    — 가용 명령 목록 system 메시지로.
        """
        cmd = text.split()[0].lower()
        _chat_log.info("slash_command %s", cmd)
        if cmd == "/clear":
            self._clear_messages()
            self._total_input_tokens = 0
            self._total_output_tokens = 0
            self._last_input_tokens = 0
            self._ctx_dot.setVisible(False)   # 컨텍스트 동그라미도 숨김.
            self.append_message(AgentMessage(
                role="system",
                text="대화 초기화 완료. 다음 메시지는 새 세션으로 시작합니다.",
            ))
            self._refresh_context_status()
            self.clear_requested.emit()
            return True
        if cmd == "/compact":
            self.append_message(AgentMessage(
                role="system",
                text="Claude 에게 지금까지 대화 요약 요청 중…",
            ))
            self.compact_requested.emit()
            return True
        if cmd == "/help":
            lines = ["**사용 가능한 명령**:"]
            for name, desc in SLASH_COMMANDS:
                lines.append(f"- `{name}` — {desc}")
            self.append_message(AgentMessage(role="system", text="\n".join(lines)))
            return True
        return False

    def eventFilter(self, obj, event):
        """scroll viewport 의 resize 를 잡아 inner widget maxWidth 강제 — wrap 보장.

        widgetResizable=True 와 horizontalScrollBarPolicy=AlwaysOff 만으로는 충분하지 않음.
        자식 bubble 의 sizeHint 가 wide 면 그 따라 _messages_host 가 wide 해져 wrap 무력화.
        viewport resize 마다 명시 setMaximumWidth 로 강제.
        """
        from PySide6.QtCore import QEvent
        if obj is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._messages_host.setMaximumWidth(event.size().width())
        return super().eventFilter(obj, event)

    def _on_image_pasted(self, png_bytes: bytes) -> None:
        """Ctrl+V — 입력창에 이미지 붙여넣었을 때 pending 에 누적."""
        if not png_bytes:
            return
        self._pending_images.append(png_bytes)
        self._refresh_attach_label()

    def _refresh_attach_label(self) -> None:
        """pending 첨부 row 갱신. 0 이면 숨김. 라벨 텍스트 + 취소 버튼 같이 표시."""
        n = len(self._pending_images)
        if n <= 0:
            self._attach_row.setVisible(False)
            return
        self._attach_label.setText(
            f"📎 이미지 {n}개 첨부됨 — 보내기 시 Claude 에게 함께 전송"
        )
        self._attach_row.setVisible(True)

    def _on_attach_cancel(self) -> None:
        """첨부된 이미지 전부 취소 — pending 비우고 라벨 숨김."""
        self._pending_images.clear()
        self._refresh_attach_label()

    def _clear_messages(self) -> None:
        """말풍선 전부 제거 — stretch (index 0) 는 유지.

        stretch 뒤의 항목들만 takeAt(1) 로 반복 제거. stretch 까지 제거하면 다음
        insert 시 아래쪽 정렬이 깨짐.
        """
        while self._messages_lay.count() > 1:
            item = self._messages_lay.takeAt(1)   # index 1 = stretch 바로 뒤.
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._active_proposals_card = None
        self._active_whisper_card = None
        self._current_assistant_bubble = None
        self._current_thinking_bubble = None
        # 영속화도 즉시 반영.
        self._schedule_history_save()

    def _insert_bubble(self, bubble: _MessageBubble) -> None:
        # stretch 가 *맨 위* (index 0) 에 있으니, 그 *뒤*에 차례로 append.
        # 결과: stretch / oldest_bubble / ... / newest_bubble — 콘텐츠는 아래로 쌓임.
        self._messages_lay.addWidget(bubble)

    @Slot(str, str, str)
    def _on_plan_submitted(self, plan_id: str, summary: str, markdown: str) -> None:
        """PlanGate.plan_submitted → 새 _PlanCard 생성 + 메시지 영역에 삽입."""
        card = _PlanCard(plan_id=plan_id, summary=summary, markdown=markdown)
        # plan_id 를 lambda 에 capture — 여러 plan 동시 처리 시 섞이지 않음.
        card.approved.connect(lambda pid=plan_id: self._plan_gate.approve(pid))
        card.rejected.connect(lambda reason, pid=plan_id: self._plan_gate.reject(pid, reason))
        self._plan_cards[plan_id] = card
        self._messages_lay.addWidget(card)
        self._scroll_to_bottom()

    @Slot(str, str)
    def _on_plan_resolved(self, plan_id: str, outcome: str) -> None:
        """PlanGate.plan_resolved → 기존 PlanCard 의 버튼 잠금 + 헤더 갱신.

        cancel_all 이 외부 트리거 (새 메시지 / cancel) 로 발생한 경우 stale card 가
        클릭 가능한 채로 남는 UX 갭 fix. approve/reject 도 emit 하지만 그 경로는
        이미 card 가 self._decided=True 라 동작 noop.
        """
        card = self._plan_cards.pop(plan_id, None)
        if card is None:
            return
        card.mark_externally_resolved(outcome)

    def _scroll_to_bottom(self) -> None:
        """즉시 한 번 — 이후 rangeChanged 가 layout 후 다시 호출해 정확히 정렬."""
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_scroll_range_changed(self, _min: int, _max: int) -> None:
        """메시지/스트리밍으로 컨텐츠 크기 변할 때 — auto_scroll 이면 바닥 유지."""
        if self._auto_scroll:
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_scroll_value_changed(self, value: int) -> None:
        """사용자가 직접 스크롤한 경우 — 맨 아래면 auto 재활성, 위로 가면 비활성."""
        bar = self._scroll.verticalScrollBar()
        # 20px 임계값 — 사용자가 살짝 위로 스크롤했어도 auto 유지 (한 줄 분량 여유).
        self._auto_scroll = value >= bar.maximum() - 20
