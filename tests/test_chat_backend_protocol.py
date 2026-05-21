"""ChatBackend Protocol + ChatInput dataclass 단위 테스트.

Protocol 자체는 런타임 검사가 약해서 shape 만 확인. ChatInput 은 dataclass 라
field/default 검증 가능.
"""
from __future__ import annotations

from screen_recorder.agent.backends.base import ChatBackend, ChatInput


def test_chat_input_text_only_defaults():
    msg = ChatInput(text="안녕")
    assert msg.text == "안녕"
    assert msg.images is None
    assert msg.audio_path is None
    assert msg.video_path is None


def test_chat_input_with_images():
    msg = ChatInput(text="이 사진 봐", images=[b"png_bytes_1", b"png_bytes_2"])
    assert msg.text == "이 사진 봐"
    assert len(msg.images) == 2
    assert msg.images[0] == b"png_bytes_1"


def test_chat_input_multimodal_paths():
    msg = ChatInput(text="이 영상", video_path="C:/a.mp4", audio_path="C:/a.wav")
    assert msg.video_path == "C:/a.mp4"
    assert msg.audio_path == "C:/a.wav"


def test_chat_backend_protocol_has_required_methods():
    """Protocol 구조 검증 — 구현체가 이 메서드들을 가져야 한다는 계약."""
    required = {"start_session", "send_message", "send_tool_result",
                "cancel", "close", "supports_modality"}
    for name in required:
        assert hasattr(ChatBackend, name), f"ChatBackend missing {name}"
