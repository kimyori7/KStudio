"""채팅 message list 위젯 — append/clear/streaming chunk 누적/history 직렬화 API.

ChatPanel 분해 Task 8. bubbles/ 패키지에서 깔끔하게 import.

책임:
- role dispatch + streaming chunk 누적 (assistant / thinking 연속 청크 → 한 bubble)
- proposals_preview / whisper_download_request 카드 생성 + signal emit
- message bubble container + 직렬화 API

ChatPanel 에 남는 책임:
- 스크롤 정책 (_on_scroll_range_changed, _scroll_to_bottom) — QScrollArea 가 ChatPanel 거임
- 파일 저장 (_schedule_history_save, _flush_history) — 파일 I/O + QTimer
- append_event 상태 전환 (status label / send/cancel 버튼)

레이아웃:
- self._layout (QVBoxLayout) 의 index 0 = addStretch(1) — 메시지 아래쪽 정렬 (WhatsApp 스타일).
- ChatPanel 은 self._messages_lay = self._message_list._layout 별칭으로 기존 테스트와 완전 호환.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...agent.backends.base import AgentMessage
from ...agent.chat_history import PERSISTABLE_ROLES
from .bubbles import (
    MessageBubble as _MessageBubble,
    ProposalsPreviewCard as _ProposalsPreviewCard,
    WhisperDownloadCard as _WhisperDownloadCard,
)


class MessageListWidget(QWidget):
    """채팅 message bubble container — role dispatch + streaming chunk 누적.

    ChatPanel 이 이 위젯을 _messages_host 로 사용하고,
    self._messages_lay = self._message_list._layout 별칭을 두어
    기존 테스트 (_messages_lay 직접 접근) 와 완전 호환.
    """

    # ProposalsPreviewCard 가 생성됐을 때 ChatPanel 이 signal 받아 signal 연결.
    proposals_card_added = Signal(object)
    # WhisperDownloadCard 가 생성됐을 때.
    whisper_card_added = Signal(object)
    # _clear_messages 완료 후 ChatPanel 의 _schedule_history_save 트리거용.
    messages_cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # stretch 가 *맨 위* (index 0) — 메시지가 아래쪽 정렬 (WhatsApp/Slack 스타일).
        # ChatPanel 은 이 layout 을 self._messages_lay 별칭으로 직접 참조.
        self._layout = QVBoxLayout(self)
        # 오른쪽 8px 마진 — scrollbar 가 등장해도 콘텐츠와 겹치지 않게.
        self._layout.setContentsMargins(0, 0, 8, 0)
        self._layout.setSpacing(4)
        self._layout.addStretch(1)
        # stretch index = 0. _insert_bubble 은 addWidget 으로 stretch *뒤에* append.

        # 마지막으로 추가된 assistant / thinking 말풍선 (streaming chunk 누적 대상).
        # 새 사용자 입력 또는 다른 role 메시지 도착 시 None 으로 reset.
        self._current_assistant_bubble: Optional[_MessageBubble] = None
        self._current_thinking_bubble: Optional[_MessageBubble] = None

        # 최신 active proposals / whisper card — ChatPanel 이 mark_resolved 호출.
        self._active_proposals_card: Optional[_ProposalsPreviewCard] = None
        self._active_whisper_card: Optional[_WhisperDownloadCard] = None

    # ---- 공개 API ----

    def append_agent_message(self, msg: AgentMessage) -> None:
        """role 별 dispatch — ChatPanel.append_message 의 bubble 생성/누적 부분.

        thinking / tool_use / tool_result 의 표시 여부 결정(추론 toggle)은
        ChatPanel.append_message 위임 stub 에서 처리 — 이 위젯은 display policy 없음.
        proposals_preview / whisper_download_request 는 카드 생성 + signal emit.
        assistant / thinking 은 연속 chunk 이면 마지막 bubble 에 누적.
        그 외 (user / tool_use / tool_result / system / error 등) 는 새 bubble.
        """
        if msg.role == "proposals_preview" and msg.proposals is not None:
            card = _ProposalsPreviewCard(msg.proposals)
            self._insert_bubble(card)
            self._active_proposals_card = card
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self.proposals_card_added.emit(card)
            return

        if msg.role == "whisper_download_request":
            meta = _parse_whisper_meta(msg.text)
            card = _WhisperDownloadCard(meta["model_size"])
            self._insert_bubble(card)
            self._active_whisper_card = card
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self.whisper_card_added.emit(card)
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

    def clear_messages(self) -> None:
        """말풍선 전부 제거 — stretch (index 0) 는 유지.

        ChatPanel._clear_messages 와 동일 로직. 완료 후 messages_cleared emit.
        """
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)   # index 1 = stretch 바로 뒤.
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
        self.messages_cleared.emit()

    def message_count(self) -> int:
        """테스트용 — addStretch 1개 제외한 실제 말풍선 개수."""
        return max(0, self._layout.count() - 1)

    def last_bubble_role(self) -> Optional[str]:
        """테스트용 — 가장 최근 말풍선의 role.

        stretch 는 index 0, 말풍선은 그 뒤에 차례로 append → 마지막 = count()-1.
        """
        idx = self._layout.count() - 1
        if idx <= 0:
            return None
        item = self._layout.itemAt(idx)
        w = item.widget() if item else None
        return w.role() if isinstance(w, _MessageBubble) else None

    def reset_streaming_state(self) -> None:
        """streaming bubble 참조 초기화 — append_event 의 done/error 처리용.

        ChatPanel.append_event 가 done/error 이벤트를 받으면 이 메서드 호출.
        이후 같은 role chunk 가 와도 이어붙이지 않고 새 bubble 생성.
        """
        self._current_assistant_bubble = None
        self._current_thinking_bubble = None

    def persistable_messages(self) -> list[tuple[str, str]]:
        """history.jsonl 에 직렬화할 message list — _flush_history 가 호출.

        PERSISTABLE_ROLES (user / assistant) 에 해당하는 bubble 만 반환.
        반환 형식: list[tuple[str, str]] — save_history(path, messages) 와 호환.
        """
        out: list[tuple[str, str]] = []
        # stretch 는 index 0, 말풍선은 그 뒤부터 — 순서대로 (oldest first).
        for i in range(1, self._layout.count()):
            item = self._layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, _MessageBubble) and w.role() in PERSISTABLE_ROLES:
                out.append((w.role(), w._raw_text))
        return out

    def mark_proposals_resolved(self, outcome: str) -> None:
        """ChatPanel.mark_proposals_resolved 와 동일 로직. outcome: 'applied'/'canceled'."""
        if self._active_proposals_card is not None:
            self._active_proposals_card.mark_resolved(outcome)
            self._active_proposals_card = None

    def mark_whisper_download_resolved(self, outcome: str, message: str = "") -> None:
        """ChatPanel.mark_whisper_download_resolved 와 동일 로직.

        outcome: 'done' / 'failed' / 'canceled'.
        """
        if self._active_whisper_card is not None:
            self._active_whisper_card.mark_resolved(outcome, message)
            self._active_whisper_card = None

    # ---- 내부 helper ----

    def _insert_bubble(self, bubble: QWidget) -> None:
        """layout 에 append — stretch (index 0) 뒤에 차례로 쌓임."""
        self._layout.addWidget(bubble)


def _parse_whisper_meta(text: str) -> dict:
    """text 'model_size=base' → {model_size}. ChatPanel._parse_whisper_meta 와 동일."""
    out = {"model_size": "base"}
    for part in (text or "").split():
        if "=" in part:
            k, v = part.split("=", 1)
            if k == "model_size":
                out["model_size"] = v
    return out
