"""MessageListWidget — append / clear / message_count / streaming 누적 / persistable_messages.

Task 8 신규 테스트.
"""
from __future__ import annotations

import pytest


# ============================================================
# 기본 상태
# ============================================================

def test_widget_starts_empty(qapp):
    from screen_recorder.ui.agent.message_list import MessageListWidget
    w = MessageListWidget()
    assert w.message_count() == 0
    assert w.last_bubble_role() is None


def test_widget_has_stretch_at_index_0(qapp):
    """초기 상태에서 stretch 가 index 0 — 메시지 아래쪽 정렬 보장."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    w = MessageListWidget()
    item0 = w._layout.itemAt(0)
    assert item0 is not None
    assert item0.widget() is None, "index 0 은 stretch (spacer) 여야 함"
    assert item0.spacerItem() is not None


# ============================================================
# append_agent_message
# ============================================================

def test_widget_appends_user_message(qapp):
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="user", text="안녕"))
    assert w.message_count() == 1
    assert w.last_bubble_role() == "user"


def test_widget_appends_distinct_bubbles_for_user_and_assistant(qapp):
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="user", text="hi"))
    w.append_agent_message(AgentMessage(role="assistant", text="안녕"))
    assert w.message_count() == 2
    assert w.last_bubble_role() == "assistant"


def test_widget_merges_consecutive_assistant_chunks(qapp):
    """streaming — 같은 turn 의 assistant chunk 가 한 bubble 로 누적."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="user", text="hi"))
    w.append_agent_message(AgentMessage(role="assistant", text="안"))
    w.append_agent_message(AgentMessage(role="assistant", text="녕"))
    # user 1 + assistant 1 (누적) = 2
    assert w.message_count() == 2
    assert w.last_bubble_role() == "assistant"


def test_widget_merges_consecutive_thinking_chunks(qapp):
    """streaming — thinking chunk 도 누적."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="thinking", text="우선 "))
    w.append_agent_message(AgentMessage(role="thinking", text="생각해보면 "))
    w.append_agent_message(AgentMessage(role="thinking", text="이렇다."))
    assert w.message_count() == 1
    # bubble 의 텍스트가 합쳐졌는지.
    idx = w._layout.count() - 1
    bubble = w._layout.itemAt(idx).widget()
    assert "이렇다" in bubble._raw_text
    assert "생각해보면" in bubble._raw_text


def test_widget_new_role_breaks_streaming_accumulation(qapp):
    """tool_use 삽입 후 다시 assistant 오면 새 bubble."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="assistant", text="A"))
    w.append_agent_message(AgentMessage(role="tool_use", text="get()"))
    w.append_agent_message(AgentMessage(role="assistant", text="B"))
    # assistant + tool_use + assistant = 3 bubble (B 는 새 bubble 로 시작)
    assert w.message_count() == 3


def test_widget_thinking_reset_after_tool_use(qapp):
    """tool_use 후 thinking 가 새로 시작되면 별도 bubble."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="thinking", text="우선 상태 보자"))
    w.append_agent_message(AgentMessage(role="tool_use", text="🔧 get_video_state()"))
    w.append_agent_message(AgentMessage(role="thinking", text="이제 답변 작성"))
    assert w.message_count() == 3


# ============================================================
# clear_messages
# ============================================================

def test_widget_clear(qapp):
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="user", text="x"))
    w.clear_messages()
    assert w.message_count() == 0
    assert w.last_bubble_role() is None


def test_widget_clear_preserves_stretch(qapp):
    """clear 후에도 stretch 가 index 0 에 그대로 — 다음 메시지 정렬 보장."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="user", text="x"))
    w.clear_messages()
    item0 = w._layout.itemAt(0)
    assert item0.spacerItem() is not None, "stretch 가 사라지면 다음 메시지 정렬 깨짐"


def test_widget_clear_emits_messages_cleared(qapp):
    """clear_messages 가 messages_cleared signal emit."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    emitted = []
    w = MessageListWidget()
    w.messages_cleared.connect(lambda: emitted.append(True))
    w.append_agent_message(AgentMessage(role="user", text="x"))
    w.clear_messages()
    assert emitted, "messages_cleared signal 이 emit 되지 않음"


# ============================================================
# reset_streaming_state
# ============================================================

def test_reset_streaming_state_prevents_accumulation(qapp):
    """reset_streaming_state 후 같은 role 이 와도 새 bubble 생성."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="assistant", text="A"))
    assert w.message_count() == 1
    w.reset_streaming_state()
    w.append_agent_message(AgentMessage(role="assistant", text="B"))
    # A 와 B 는 별도 bubble.
    assert w.message_count() == 2


# ============================================================
# persistable_messages
# ============================================================

def test_widget_persistable_messages_returns_role_text_pairs(qapp):
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="user", text="안녕"))
    w.append_agent_message(AgentMessage(role="assistant", text="네"))
    out = w.persistable_messages()
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0] == ("user", "안녕")
    assert out[1] == ("assistant", "네")


def test_widget_persistable_messages_excludes_thinking(qapp):
    """thinking 은 PERSISTABLE_ROLES 에 없어서 저장 대상 아님.
    system / user / tool_use / tool_result / assistant / error 는 포함.
    """
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="thinking", text="생각"))
    w.append_agent_message(AgentMessage(role="user", text="hi"))
    w.append_agent_message(AgentMessage(role="assistant", text="답변"))
    out = w.persistable_messages()
    # thinking 은 제외 — user + assistant 만.
    roles = [r for r, _ in out]
    assert "thinking" not in roles
    assert "user" in roles
    assert "assistant" in roles


def test_widget_persistable_messages_empty_after_clear(qapp):
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    w = MessageListWidget()
    w.append_agent_message(AgentMessage(role="user", text="x"))
    w.clear_messages()
    assert w.persistable_messages() == []


# ============================================================
# proposals_card_added / whisper_card_added signal
# ============================================================

def test_proposals_card_added_signal_emitted(qapp):
    """proposals_preview 메시지 → proposals_card_added signal emit."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    cards = []
    w = MessageListWidget()
    w.proposals_card_added.connect(lambda c: cards.append(c))
    w.append_agent_message(AgentMessage(
        role="proposals_preview",
        text="",
        proposals=[{"action": "add", "type": "caption",
                    "payload": {"in_ms": 0, "out_ms": 1000, "text": "hi"}}],
    ))
    assert len(cards) == 1


def test_whisper_card_added_signal_emitted(qapp):
    """whisper_download_request 메시지 → whisper_card_added signal emit."""
    from screen_recorder.ui.agent.message_list import MessageListWidget
    from screen_recorder.agent.backends.base import AgentMessage
    cards = []
    w = MessageListWidget()
    w.whisper_card_added.connect(lambda c: cards.append(c))
    w.append_agent_message(AgentMessage(
        role="whisper_download_request",
        text="model_size=base",
    ))
    assert len(cards) == 1
