"""ChatPanel — 슬래시 명령 + 컨텍스트 표시 + thinking 누적 + 멀티라인 입력.

QDockWidget 라 qtbot.addWidget 으로 등록 후 시그널 발화 검증.
"""
from __future__ import annotations

import pytest

from screen_recorder.agent.runtime import AgentEvent, AgentMessage
from screen_recorder.ui.agent.chat_panel import (
    SLASH_COMMANDS, ChatPanel, _context_limit_for,
)


@pytest.fixture
def panel(qtbot):
    p = ChatPanel(initial_model_id="claude-sonnet-4-6", initial_show_thinking=True)
    qtbot.addWidget(p)
    return p


# ============================================================
# 슬래시 명령 — /clear, /compact, /help
# ============================================================
def test_clear_command_resets_messages_and_emits(panel, qtbot):
    panel.append_message(AgentMessage(role="user", text="안녕"))
    panel.append_message(AgentMessage(role="assistant", text="네"))
    assert panel.message_count() == 2

    panel._input.setPlainText("/clear")
    with qtbot.waitSignal(panel.clear_requested, timeout=500):
        panel._on_submit()

    # 알림용 system 메시지 1개만 남음 ("대화 초기화 완료").
    assert panel.message_count() == 1
    assert panel.last_bubble_role() == "system"


def test_clear_command_resets_token_counters(panel, qtbot):
    panel._total_input_tokens = 50_000
    panel._total_output_tokens = 1_000
    panel._last_input_tokens = 30_000
    panel._input.setPlainText("/clear")
    with qtbot.waitSignal(panel.clear_requested, timeout=500):
        panel._on_submit()
    assert panel._total_input_tokens == 0
    assert panel._total_output_tokens == 0
    assert panel._last_input_tokens == 0


def test_compact_command_emits(panel, qtbot):
    panel._input.setPlainText("/compact")
    with qtbot.waitSignal(panel.compact_requested, timeout=500):
        panel._on_submit()
    # system 알림 메시지 추가됐어야 함.
    assert panel.last_bubble_role() == "system"


def test_help_command_lists_commands(panel):
    panel._input.setPlainText("/help")
    panel._on_submit()
    # 마지막 메시지가 system 이고 SLASH_COMMANDS 이름 포함.
    assert panel.last_bubble_role() == "system"
    # _raw_text 확인 — 마지막 bubble (stretch 가 0번, 말풍선은 그 뒤).
    last_idx = panel._messages_lay.count() - 1
    bubble = panel._messages_lay.itemAt(last_idx).widget()
    text = bubble._raw_text
    for name, _desc in SLASH_COMMANDS:
        assert name in text, f"/help 결과에 {name} 없음"


def test_unknown_slash_command_shows_hint(panel):
    panel._input.setPlainText("/madeup")
    panel._on_submit()
    assert panel.last_bubble_role() == "system"
    # user_submitted 시그널은 발화되지 않아야 (Claude 한테 보내지 않음).
    # qtbot 검증 대신 user 메시지 안 추가됐는지로 확인.
    # system 메시지 하나만 있음.
    assert panel.message_count() == 1


def test_slash_command_does_not_emit_user_submitted(panel, qtbot):
    """/clear 같은 슬래시 명령은 Claude 한테 prompt 로 안 가야 함."""
    with qtbot.assertNotEmitted(panel.user_submitted, wait=100):
        panel._input.setPlainText("/clear")
        panel._on_submit()


def test_non_slash_text_emits_user_submitted(panel, qtbot):
    """일반 텍스트는 user_submitted (text, images=[]) 발화."""
    panel._input.setPlainText("안녕 Claude")
    with qtbot.waitSignal(panel.user_submitted, timeout=500) as blocker:
        panel._on_submit()
    assert blocker.args == ["안녕 Claude", []]


# ============================================================
# 컨텍스트 사용량 표시
# ============================================================
def test_context_summary_empty_when_no_response_yet(panel):
    """아직 응답 못 받았으면 context summary 빈 string."""
    assert panel._context_summary() == ""


def test_context_summary_after_done_event(panel):
    """done 이벤트의 in=N 토큰이 last_input_tokens 에 들어가고 % 계산."""
    panel.append_event(AgentEvent(kind="done", detail="in=20000 out=500"))
    summary = panel._context_summary()
    assert "ctx" in summary
    assert "20.0k" in summary
    assert "200.0k" in summary
    assert "10%" in summary   # 20000 / 200000 = 10%


def test_context_summary_warning_at_high_usage(panel):
    """70% 이상이면 ⚠ 마크."""
    panel.append_event(AgentEvent(kind="done", detail="in=150000 out=100"))
    summary = panel._context_summary()
    assert "⚠" in summary
    assert "75%" in summary


def test_ctx_dot_hidden_initially(panel):
    """첫 응답 전엔 컨텍스트 바 숨김."""
    assert not panel._ctx_dot.isVisible()


def test_ctx_dot_visible_after_done(panel, qtbot):
    """done 이벤트로 토큰 도착 → 컨텍스트 동그라미 표시 + tooltip 에 상세."""
    panel.show()   # 부모 없는 위젯이라 visibility 갱신 위해 show.
    qtbot.waitExposed(panel)
    panel.append_event(AgentEvent(kind="done", detail="in=12345 out=678"))
    assert panel._ctx_dot.isVisible()
    tip = panel._ctx_dot.toolTip()
    assert "컨텍스트" in tip
    assert "12.3k" in tip
    assert "200.0k" in tip
    assert "누적" in tip
    assert "12,345" in tip
    assert "678" in tip


def test_ctx_dot_cleared_on_slash_clear(panel, qtbot):
    """/clear 시 컨텍스트 바 숨김."""
    panel.show()
    qtbot.waitExposed(panel)
    panel.append_event(AgentEvent(kind="done", detail="in=12345 out=678"))
    assert panel._ctx_dot.isVisible()
    panel._input.setPlainText("/clear")
    panel._on_submit()
    assert not panel._ctx_dot.isVisible()


def test_context_limit_lookup():
    """알려진 모델은 정확한 limit, 모르는 모델은 폴백."""
    assert _context_limit_for("claude-sonnet-4-6") == 200_000
    assert _context_limit_for("claude-opus-4-7") == 200_000
    assert _context_limit_for("claude-haiku-4-5-20251001") == 200_000
    # 알 수 없는 ID → 200k 폴백 (raise 안 함).
    assert _context_limit_for("madeup-model-9000") == 200_000


def test_token_accumulation(panel):
    """여러 done 이벤트의 in/out 누적 + last_input 은 *최신* 값."""
    panel.append_event(AgentEvent(kind="done", detail="in=1000 out=200"))
    panel.append_event(AgentEvent(kind="done", detail="in=5000 out=300"))
    assert panel._total_input_tokens == 6000
    assert panel._total_output_tokens == 500
    assert panel._last_input_tokens == 5000


# ============================================================
# thinking 누적 — partial chunk 가 빈 박스 누적 안 만드는지
# ============================================================
def test_thinking_partial_chunks_accumulate(panel):
    """thinking partial 3개 도착 — bubble 1개만 생기고 텍스트 누적."""
    before = panel.message_count()
    panel.append_message(AgentMessage(role="thinking", text="음 "))
    panel.append_message(AgentMessage(role="thinking", text="이 영상은 "))
    panel.append_message(AgentMessage(role="thinking", text="20초입니다."))
    after = panel.message_count()
    assert after - before == 1, "thinking 누적 안 돼서 여러 bubble 생김"
    # bubble 의 텍스트가 합쳐졌는지 (stretch index 0, 말풍선 그 뒤).
    idx = panel._messages_lay.count() - 1
    bubble = panel._messages_lay.itemAt(idx).widget()
    assert "20초입니다" in bubble._raw_text
    assert "이 영상은" in bubble._raw_text


def test_thinking_reset_after_tool_use(panel):
    """tool_use 후 thinking 가 새로 시작되면 별도 bubble."""
    panel.append_message(AgentMessage(role="thinking", text="우선 상태 보자"))
    panel.append_message(AgentMessage(role="tool_use", text="🔧 get_video_state()"))
    panel.append_message(AgentMessage(role="thinking", text="이제 답변 작성"))
    # thinking - tool_use - thinking 3개 bubble.
    assert panel.message_count() == 3


def test_thinking_hidden_when_toggle_off(panel):
    """추론 보기 OFF 면 thinking 메시지 무시."""
    panel._thinking_check.setChecked(False)
    before = panel.message_count()
    panel.append_message(AgentMessage(role="thinking", text="비밀 추론"))
    panel.append_message(AgentMessage(role="thinking", text="더 비밀"))
    assert panel.message_count() == before


# ============================================================
# 멀티라인 입력
# ============================================================
def test_multiline_input_widget_type(panel):
    """QPlainTextEdit 기반 — toPlainText() 호출 가능."""
    panel._input.setPlainText("line1\nline2\nline3")
    text = panel._input.toPlainText()
    assert text == "line1\nline2\nline3"


def test_multiline_input_submitted_preserves_newlines(panel, qtbot):
    """줄바꿈 있는 입력도 그대로 user_submitted 로 전달."""
    panel._input.setPlainText("첫 줄\n둘째 줄")
    with qtbot.waitSignal(panel.user_submitted, timeout=500) as blocker:
        panel._on_submit()
    assert blocker.args == ["첫 줄\n둘째 줄", []]


# ============================================================
# 레이아웃 — 빈곳 누적 fix 검증.
# 채팅 표준 UX: stretch 가 *맨 위* — 메시지가 viewport 바닥 기준으로 쌓임.
# ============================================================
def test_stretch_anchored_to_top(panel):
    """초기 상태에서 stretch 가 index 0 — 빈 채팅에서 메시지 자리 비워두기."""
    # 첫 항목이 stretch (위젯이 아닌 spacer item).
    item0 = panel._messages_lay.itemAt(0)
    assert item0 is not None
    assert item0.widget() is None, "index 0 은 stretch (spacer) 여야 함"
    assert item0.spacerItem() is not None


def test_bubbles_append_after_stretch_in_order(panel):
    """말풍선 3개 추가 — index 1,2,3 에 oldest→newest 순으로."""
    panel.append_message(AgentMessage(role="user", text="첫번째"))
    panel.append_message(AgentMessage(role="assistant", text="둘째"))
    panel.append_message(AgentMessage(role="user", text="셋째"))
    # stretch + 3 bubbles = count 4.
    assert panel._messages_lay.count() == 4
    # index 1 = oldest, index 3 = newest.
    b1 = panel._messages_lay.itemAt(1).widget()
    b2 = panel._messages_lay.itemAt(2).widget()
    b3 = panel._messages_lay.itemAt(3).widget()
    assert b1._raw_text == "첫번째"
    assert b2._raw_text == "둘째"
    assert b3._raw_text == "셋째"
    # last_bubble_role 도 last bubble (셋째 user) 와 일치.
    assert panel.last_bubble_role() == "user"


def test_tool_log_lines_are_compact(panel):
    """tool_use / tool_result 는 log-line 스타일 — 작은 폰트, 패딩 거의 0, 배경/테두리 없음.

    2026-05-13 변경: wordWrap 도 True (이전엔 False 라 long sizeHint 가 wrap 회귀 일으킴).
    """
    panel.show()
    panel.resize(400, 600)

    a = _make_bubble(panel, "assistant", "이 영상은 1분짜리 입니다.")
    t_use = _make_bubble(panel, "tool_use", "🔧 get_video_state()")
    t_res = _make_bubble(panel, "tool_result", "← (info)")

    # 모든 role 이 wrap True — wide sizeHint 회귀 방지.
    assert t_use._label.wordWrap() is True
    assert t_res._label.wordWrap() is True
    assert a._label.wordWrap() is True


def _make_bubble(panel, role: str, text: str):
    """헬퍼 — panel 에 메시지 추가 후 마지막 _MessageBubble 반환."""
    from screen_recorder.ui.agent.chat_panel import _MessageBubble
    panel.append_message(AgentMessage(role=role, text=text))
    last_idx = panel._messages_lay.count() - 1
    w = panel._messages_lay.itemAt(last_idx).widget()
    assert isinstance(w, _MessageBubble)
    return w


# ============================================================
# 줄바꿈 (wordWrap) — 모든 role 에서 viewport 폭 안에 들어가는지.
# 사용자 보고 (2026-05-13): "채팅창 줄바꿈이 안되" — markdown / tool_result 가 viewport
# 넘어가던 회귀. 검증은 (1) bubble 자체 wordWrap True, (2) viewport resize 후 messages_host
# 의 maxWidth 가 viewport 폭과 일치하는지.
# ============================================================
def test_all_bubbles_wordwrap_enabled(panel):
    """assistant / thinking / user / tool_use / tool_result 모두 wordWrap=True 여야.

    log-line role 도 긴 args 들어오면 wrap 해야 — 안 그러면 wide sizeHint 가 column 너비를
    부풀려 다른 bubble 들의 wrap 까지 무력화.
    """
    from screen_recorder.ui.agent.chat_panel import _MessageBubble
    for role in ("assistant", "thinking", "user", "tool_use", "tool_result", "system", "error"):
        panel.append_message(AgentMessage(role=role, text="x" * 100))
    # 마지막 message_count 만큼 bubble 들 모두 wordWrap True.
    for i in range(1, panel._messages_lay.count()):
        item = panel._messages_lay.itemAt(i)
        w = item.widget() if item else None
        if isinstance(w, _MessageBubble):
            assert w._label.wordWrap() is True, f"{w.role()} bubble wordWrap=False — wrap 회귀"


def test_viewport_resize_constrains_inner_widget(panel, qtbot):
    """scroll viewport resize 시 inner widget 의 maxWidth 가 viewport 폭으로 강제."""
    panel.show()
    qtbot.waitExposed(panel)
    panel.resize(400, 600)
    qtbot.wait(50)   # eventFilter 처리 대기.
    viewport_w = panel._scroll.viewport().width()
    assert viewport_w > 0
    assert panel._messages_host.maximumWidth() <= viewport_w + 1, (
        f"messages_host maxWidth={panel._messages_host.maximumWidth()} > viewport {viewport_w} — "
        f"wrap 제약 못 걸림"
    )


def test_long_assistant_text_fits_viewport(panel, qtbot):
    """긴 markdown 어시스턴트 텍스트가 viewport 폭 안에 들어가는지 (= wrap 작동).

    bubble 의 실제 width 가 viewport 폭 이하여야 — 초과면 wrap 실패 (사용자 보고).
    """
    panel.show()
    panel.resize(420, 700)
    qtbot.waitExposed(panel)
    qtbot.wait(50)

    long_md = (
        "## 응답 시작\n\n"
        "- **첫 줄**: 1280px 이미지에서 약 x≈476, y≈84 → 정규화: x=0.37, y=0.07\n"
        "- **둘째 줄**: 더 긴 텍스트가 들어와도 wrap 되어야 함 — 한 줄에 모든 정보가 다 들어가지 않는 게 정상\n"
        "- 셋째 줄: A B C D E F G H I J K L M N O P Q R S T U V W X Y Z"
    )
    panel.append_message(AgentMessage(role="assistant", text=long_md))
    qtbot.wait(100)   # layout 처리.

    # 마지막 bubble 의 width 가 viewport 폭 이하인지.
    from screen_recorder.ui.agent.chat_panel import _MessageBubble
    last_idx = panel._messages_lay.count() - 1
    bubble = panel._messages_lay.itemAt(last_idx).widget()
    assert isinstance(bubble, _MessageBubble)
    viewport_w = panel._scroll.viewport().width()
    # bubble width 는 viewport 폭 안. wrap 작동하면 width = parent 폭으로 제한.
    assert bubble.width() <= viewport_w + 1, (
        f"bubble width={bubble.width()} > viewport {viewport_w} — wrap 실패"
    )


def test_long_tool_result_does_not_widen_column(panel, qtbot):
    """긴 tool_result preview text 가 messages_host 폭 부풀리지 않는지.

    이전 회귀의 핵심: tool_result wordWrap=False 일 때 sizeHint 가 wide → VBox 컬럼 wide →
    모든 bubble 이 wide 컬럼 안에서 wrap 무력. wordWrap=True 로 바꿔 회귀 차단.
    """
    panel.show()
    panel.resize(420, 700)
    qtbot.waitExposed(panel)
    qtbot.wait(50)

    # 보통 tool_result preview 는 ~120 chars (`_extract_image_and_preview` 가 truncate).
    long_preview = "← " + ("abcdefghij " * 12)   # 약 130 chars
    panel.append_message(AgentMessage(role="tool_result", text=long_preview))
    qtbot.wait(100)

    viewport_w = panel._scroll.viewport().width()
    assert panel._messages_host.width() <= viewport_w + 1, (
        f"messages_host {panel._messages_host.width()} > viewport {viewport_w} — wide column 누수"
    )


def test_clear_preserves_stretch(panel):
    """/clear 후에도 stretch 가 index 0 에 그대로 — 다음 메시지가 바닥 기준 유지."""
    panel.append_message(AgentMessage(role="user", text="첫번째"))
    panel.append_message(AgentMessage(role="assistant", text="응답"))
    panel._input.setPlainText("/clear")
    panel._on_submit()
    # /clear 가 알림 system 메시지 1개 남기지만, stretch 는 index 0 유지.
    item0 = panel._messages_lay.itemAt(0)
    assert item0.spacerItem() is not None, "stretch 가 사라지면 다음 메시지 정렬 깨짐"


# ============================================================
# 한글 IME — preedit 중에 placeholder 숨김 (자음 하나만 입력해도 사라져야).
# ============================================================
def test_ime_preedit_hides_placeholder(panel):
    """preedit 'ㄱ' 만 들어와도 placeholder 즉시 ""."""
    from PySide6.QtGui import QInputMethodEvent
    original = panel._input.placeholderText()
    assert original, "fixture 가 placeholder 설정해야 의미 있는 테스트"

    ev = QInputMethodEvent("ㄱ", [])   # preedit="ㄱ", commit=""
    panel._input.inputMethodEvent(ev)
    assert panel._input.placeholderText() == "", \
        "IME 조합 중엔 placeholder 가 숨겨져야 (사용자 입력과 겹치지 않게)"


def test_ime_commit_keeps_placeholder_hidden_then_restores(panel):
    """commit 후 text 차있으면 placeholder 굳이 복원 안 함 — Qt 가 자동 숨김.

    backspace 로 비우면 placeholder 다시 보여야.
    """
    from PySide6.QtGui import QInputMethodEvent
    original = panel._input.placeholderText()

    # 1) preedit "ㄱ" — placeholder 숨김.
    panel._input.inputMethodEvent(QInputMethodEvent("ㄱ", []))
    assert panel._input.placeholderText() == ""

    # 2) commit "가" — text 가 "가" 가 되고 preedit 비어짐. placeholder 가 무엇이든
    #    Qt 가 자동으로 안 그림 (text 있음).
    commit_ev = QInputMethodEvent("", [])
    commit_ev.setCommitString("가")
    panel._input.inputMethodEvent(commit_ev)
    assert panel._input.toPlainText() == "가"

    # 3) 사용자가 전부 지움 → textChanged → placeholder 복원.
    panel._input.clear()
    assert panel._input.placeholderText() == original, \
        "텍스트 비워지면 원래 placeholder 다시 보여야"


def test_ime_cancel_restores_placeholder(panel):
    """조합 취소 (preedit 만 비워짐, commit 없음) — placeholder 복원."""
    from PySide6.QtGui import QInputMethodEvent
    original = panel._input.placeholderText()

    panel._input.inputMethodEvent(QInputMethodEvent("ㄱ", []))
    assert panel._input.placeholderText() == ""

    # IME 취소 — preedit 도 commit 도 없음.
    panel._input.inputMethodEvent(QInputMethodEvent("", []))
    assert panel._input.placeholderText() == original


def test_paste_text_prefers_text_even_with_image(panel):
    """클립보드에 text + image 같이 있으면 텍스트 우선 paste — 채팅 본문 복사 보호."""
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    mime = QMimeData()
    mime.setText("복사한 텍스트")
    # 이미지도 함께 (테스트 클립보드 시뮬레이션).
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(0xff0000)
    mime.setImageData(img)

    panel._input.insertFromMimeData(mime)
    # 텍스트가 입력창에 들어갔어야. image_pasted 시그널 발화 X.
    assert "복사한 텍스트" in panel._input.toPlainText()


def test_paste_image_only_emits_signal(panel, qtbot):
    """클립보드에 이미지만 있으면 image_pasted 시그널 발화 + 입력창은 변화 없음."""
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    mime = QMimeData()
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(0x00ff00)
    mime.setImageData(img)

    with qtbot.waitSignal(panel._input.image_pasted, timeout=500):
        panel._input.insertFromMimeData(mime)
    # 첨부 리스트에 누적됨.
    assert len(panel._pending_images) == 1
    # 첨부 라벨 — panel 이 show 안 된 상태라 isVisible 은 False 일 수 있어 setVisible 결과만 확인.
    # text 갱신 + 위젯 자체의 visibility 플래그 검사 (top-level show 와 무관).
    assert "1개 첨부" in panel._attach_label.text()
    assert not panel._attach_row.isHidden(), "row 가 hidden 처리됨 — refresh 실패"


def test_attach_cancel_button_clears_pending(panel, qtbot):
    """첨부 row 의 [✕ 취소] 버튼 → pending 비우고 row 숨김."""
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    mime = QMimeData()
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(0x00ff00)
    mime.setImageData(img)
    panel._input.insertFromMimeData(mime)
    assert len(panel._pending_images) == 1

    # 취소 버튼 클릭 시뮬레이션.
    panel._on_attach_cancel()
    assert panel._pending_images == []
    assert not panel._attach_row.isVisible() or panel._attach_row.isHidden()


def test_ctrl_c_on_bubble_copies_plain_text_only(panel, qtbot):
    """선택된 텍스트가 Ctrl+C 시 클립보드에 *only plain text* — 이미지/HTML 동반 X.

    이전 회귀: markdown QLabel 의 기본 copy 는 multi-format mime data → paste target 이
    image 잡으면 사용자가 "텍스트인데 이미지로 paste" 경험.
    """
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    from screen_recorder.ui.agent.chat_panel import _MessageBubble

    panel.append_message(AgentMessage(role="assistant", text="**굵게** 본문 내용입니다."))
    bubble = None
    for i in range(panel._messages_lay.count()):
        item = panel._messages_lay.itemAt(i)
        w = item.widget() if item else None
        if isinstance(w, _MessageBubble) and w.role() == "assistant":
            bubble = w
            break
    assert bubble is not None

    # QLabel 의 selectedText 시뮬레이션 — 직접 selection 못 잡으므로 mock.
    # 대신 eventFilter 가 호출되면 clipboard 에 plain text 가 들어가는지 확인.
    bubble._label.selectedText = lambda: "굵게 본문 내용"

    # Ctrl+C key event 전달.
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier)
    # eventFilter 가 처리 — 직접 호출.
    handled = bubble.eventFilter(bubble._label, ev)
    assert handled is True, "eventFilter 가 Ctrl+C 를 소비 안 함"

    # 클립보드 검증 — 텍스트만 있어야.
    clip = QApplication.clipboard()
    mime = clip.mimeData()
    assert mime.hasText()
    assert mime.text() == "굵게 본문 내용"
    # 이미지/HTML 형식은 없어야 (우리가 setText 만 호출했으므로).
    assert not mime.hasImage(), "이미지 형식도 함께 — 회귀 발생"


def test_label_keyboard_selection_enabled(panel, qtbot):
    """말풍선 QLabel 이 Qt.TextSelectableByKeyboard 도 포함해야 Ctrl+C 가 도착.

    회귀 (2026-05-13: 사용자 보고 "Ctrl+C 하면 vscode 에 스샷 붙음"). by-keyboard 가 없으면
    Qt 가 QLabel 에 KeyPress 라우팅 자체를 안 함 → eventFilter 발화 안 함 → default copy
    (위젯 image) 가 클립보드로.
    """
    from PySide6.QtCore import Qt
    from screen_recorder.ui.agent.chat_panel import _MessageBubble

    panel.append_message(AgentMessage(role="assistant", text="hello"))
    bubble = next(
        panel._messages_lay.itemAt(i).widget()
        for i in range(panel._messages_lay.count())
        if isinstance(panel._messages_lay.itemAt(i).widget() if panel._messages_lay.itemAt(i) else None, _MessageBubble)
    )
    flags = bubble._label.textInteractionFlags()
    assert flags & Qt.TextSelectableByKeyboard, "TextSelectableByKeyboard 누락 — Ctrl+C 회귀"
    assert flags & Qt.TextSelectableByMouse, "TextSelectableByMouse 누락"


def test_image_label_has_no_focus_policy(panel, qtbot):
    """tool_result 의 inline image_label 은 focusPolicy=NoFocus — focus 받으면 Ctrl+C 가
    image 로 클립보드 박혀 사용자 보고 (2026-05-13: VSCode 붙여넣기 시 스샷) 회귀.
    """
    from PySide6.QtCore import Qt
    from screen_recorder.ui.agent.chat_panel import _MessageBubble

    fake_png = (b"\x89PNG\r\n\x1a\n" +
                b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00"
                b"\x00\x00\x03\x00\x01\x5b\xeb\xa3\xa1\x00\x00\x00\x00IEND\xaeB`\x82")
    bubble = _MessageBubble("tool_result", "frame_at result", image_bytes=fake_png)
    qtbot.addWidget(bubble)
    if bubble._image_label is not None:
        assert bubble._image_label.focusPolicy() == Qt.NoFocus, \
            "image_label 이 focus 받으면 Ctrl+C 가 pixmap 으로 — 회귀"


def test_submit_clears_pending_images(panel, qtbot):
    """이미지 첨부 후 submit 하면 user_submitted 가 (text, [bytes]) 로 emit + pending clear."""
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    mime = QMimeData()
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(0x0000ff)
    mime.setImageData(img)
    panel._input.insertFromMimeData(mime)
    assert len(panel._pending_images) == 1

    panel._input.setPlainText("이미지 분석해줘")
    with qtbot.waitSignal(panel.user_submitted, timeout=500) as blocker:
        panel._on_submit()
    text, images = blocker.args
    assert text == "이미지 분석해줘"
    assert len(images) == 1 and isinstance(images[0], bytes)
    # submit 후 pending 비워짐.
    assert panel._pending_images == []
    assert not panel._attach_row.isVisible()


def test_setPlaceholderText_external_call_remembered(panel):
    """외부에서 placeholder 변경해도 IME 처리에 반영."""
    from PySide6.QtGui import QInputMethodEvent

    panel._input.setPlaceholderText("새 안내문")
    panel._input.inputMethodEvent(QInputMethodEvent("ㄱ", []))
    assert panel._input.placeholderText() == ""
    panel._input.inputMethodEvent(QInputMethodEvent("", []))
    assert panel._input.placeholderText() == "새 안내문", \
        "외부 setPlaceholderText 로 변경된 값이 복원돼야 — 원본 캐시가 갱신됨"
