"""TransformersBackend 단위 테스트 — transformers + qwen_omni_utils mock.

ClaudeBackend 의 sdk_mock 패턴과 동일 — sys.modules 에 가짜 모듈 inject 후 lazy
import 가 그걸 받도록. transformers / torch / qwen_omni_utils 미설치 환경에서도
테스트 동작.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from screen_recorder.agent.backends.transformers_backend import TransformersBackend


@pytest.fixture
def transformers_mock(monkeypatch):
    """transformers + qwen_omni_utils + torch 를 mock 으로 교체.

    반환: dict — keys: 'model_cls', 'processor_cls', 'model_inst', 'processor_inst',
    'process_mm_info', 'torch'. 테스트가 generate/batch_decode 동작 재정의.
    """
    import sys

    model_inst = MagicMock()
    model_inst.device = "cpu"
    model_inst.dtype = "float32"
    model_inst.generate = MagicMock(return_value=[[1, 2, 3]])

    processor_inst = MagicMock()
    processor_inst.apply_chat_template = MagicMock(return_value="<prompt>")
    processor_inst.batch_decode = MagicMock(return_value=["기본 응답"])
    fake_inputs = MagicMock()
    fake_inputs.to = MagicMock(return_value=fake_inputs)
    processor_inst.return_value = fake_inputs

    model_cls = MagicMock()
    model_cls.from_pretrained = MagicMock(return_value=model_inst)
    processor_cls = MagicMock()
    processor_cls.from_pretrained = MagicMock(return_value=processor_inst)

    fake_transformers = MagicMock()
    fake_transformers.Qwen2_5OmniForConditionalGeneration = model_cls
    fake_transformers.Qwen2_5OmniProcessor = processor_cls
    fake_transformers.TextIteratorStreamer = MagicMock()
    fake_transformers.StoppingCriteria = type("StoppingCriteria", (), {})
    fake_transformers.StoppingCriteriaList = MagicMock()

    fake_qou = MagicMock()
    fake_qou.process_mm_info = MagicMock(return_value=([], [], []))

    fake_torch = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=None)
    cm.__exit__ = MagicMock(return_value=False)
    fake_torch.no_grad = MagicMock(return_value=cm)
    fake_torch.inference_mode = MagicMock(return_value=cm)

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "qwen_omni_utils", fake_qou)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    yield {
        "model_cls": model_cls,
        "processor_cls": processor_cls,
        "model_inst": model_inst,
        "processor_inst": processor_inst,
        "process_mm_info": fake_qou.process_mm_info,
        "torch": fake_torch,
        "transformers": fake_transformers,
    }


@pytest.mark.asyncio
async def test_start_session_does_not_load_model(transformers_mock):
    """start_session 만 호출하면 모델 로드 X — lazy 보장.

    회귀 보호: from_pretrained 호출 = ~8GB 다운로드 + 수십 초. 사용자가 콤보에서
    모델 선택해서 backend 활성화만 했지 메시지 안 보냈을 때는 로드 안 하기로 결정.
    """
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    assert transformers_mock["model_cls"].from_pretrained.call_count == 0
    assert transformers_mock["processor_cls"].from_pretrained.call_count == 0


@pytest.mark.asyncio
async def test_close_unloads_model_and_runs_gc(transformers_mock, monkeypatch):
    """close() 후 _model = None + gc.collect() 호출 — VRAM 회수 보장.

    회귀 보호: 7B 모델 ≈ 8GB VRAM. unload 안 되면 사용자가 다른 GPU 앱 못 씀.
    """
    import gc as gc_module
    gc_called = []
    monkeypatch.setattr(gc_module, "collect", lambda: gc_called.append(1))

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be._ensure_model_loaded()
    assert be._model is not None

    await be.close()
    assert be._model is None
    assert be._processor is None
    assert gc_called, "gc.collect() 호출 안 됨 — VRAM 회수 위험"


@pytest.mark.asyncio
async def test_cancel_noop_when_no_generation(transformers_mock):
    """진행 중 generate 가 없으면 cancel() 은 예외 없이 끝남."""
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    assert be._stop_flag is None
    await be.cancel()


def test_supports_modality_text_image_only_in_poc():
    """sub-plan 2 단계: text + image 만. audio/video 는 sub-plan 7."""
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    assert be.supports_modality("image") is True
    assert be.supports_modality("audio") is False
    assert be.supports_modality("video") is False
    assert be.supports_modality("text") is False


def test_build_conversation_text_only():
    """ChatInput(text='안녕') → [system, user(text)] — HF 모델카드 예시 형식 정확히."""
    from screen_recorder.agent.backends import ChatInput
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    be._system_prompt = "너는 친절한 AI."
    conv = be._build_conversation(ChatInput(text="안녕"))
    assert len(conv) == 2
    assert conv[0]["role"] == "system"
    # HF 카드: system content 는 list of blocks
    assert conv[0]["content"] == [{"type": "text", "text": "너는 친절한 AI."}]
    assert conv[1]["role"] == "user"
    # text-only user content 는 string (모델카드 예시)
    assert conv[1]["content"] == "안녕"


def test_build_conversation_with_images_writes_temp_files(tmp_path, monkeypatch):
    """images 가 있으면 bytes → 임시 PNG 파일 → conversation 에 path 사용.

    Qwen processor 의 image block 은 path 받음 — bytes 직접 안 됨 (HF 카드 확인).
    임시 파일 정리는 Task 5 의 send_message finally 에서.
    """
    import tempfile
    from pathlib import Path
    from screen_recorder.agent.backends import ChatInput
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    be._system_prompt = "sys"
    png = b"\x89PNG\r\n\x1a\nfake"
    conv = be._build_conversation(ChatInput(text="이거 봐", images=[png]))

    user_content = conv[1]["content"]
    assert isinstance(user_content, list)
    img_blocks = [b for b in user_content if b.get("type") == "image"]
    text_blocks = [b for b in user_content if b.get("type") == "text"]
    assert len(img_blocks) == 1
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "이거 봐"
    p = Path(img_blocks[0]["image"])
    assert p.exists()
    assert p.read_bytes() == png
    assert p in be._temp_files


def test_build_conversation_empty_text_with_images_uses_placeholder(tmp_path, monkeypatch):
    """text='' + images=[...] → '(첨부 이미지)' 같은 placeholder."""
    import tempfile
    from screen_recorder.agent.backends import ChatInput
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    be._system_prompt = "sys"
    conv = be._build_conversation(ChatInput(text="", images=[b"\x89PNG..."]))
    text_blocks = [b for b in conv[1]["content"] if b.get("type") == "text"]
    assert text_blocks[0]["text"] == "(첨부 이미지)"


@pytest.mark.asyncio
async def test_send_message_text_only_emits_started_text_done(transformers_mock):
    """텍스트 send → started 이벤트 → AgentMessage(role='assistant') → done 이벤트.

    generate 결과는 batch_decode 의 mock 반환값 ('기본 응답').
    """
    from screen_recorder.agent.backends import ChatInput, AgentEvent, AgentMessage

    transformers_mock["processor_inst"].batch_decode = MagicMock(
        return_value=["안녕하세요, 무엇을 도와드릴까요?"],
    )

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    received: list = []
    await be.send_message(ChatInput(text="안녕"), received.append)

    started = [r for r in received if isinstance(r, AgentEvent) and r.kind == "started"]
    assert len(started) == 1

    texts = [r for r in received if isinstance(r, AgentMessage) and r.role == "assistant"]
    assert len(texts) == 1
    assert texts[0].text == "안녕하세요, 무엇을 도와드릴까요?"

    done = [r for r in received if isinstance(r, AgentEvent) and r.kind == "done"]
    assert len(done) == 1


@pytest.mark.asyncio
async def test_send_message_calls_apply_chat_template_and_processor(transformers_mock):
    """send_message 가 HF API 시퀀스를 정확히 호출 — apply_chat_template +
    process_mm_info + processor(...) + generate + batch_decode."""
    from screen_recorder.agent.backends import ChatInput

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="너는 한국어 AI.", tools={}, model="qwen25-omni-7b")
    await be.send_message(ChatInput(text="안녕"), lambda _: None)

    p = transformers_mock["processor_inst"]
    m = transformers_mock["model_inst"]

    # apply_chat_template 호출 — add_generation_prompt=True, tokenize=False.
    assert p.apply_chat_template.call_count == 1
    args, kwargs = p.apply_chat_template.call_args
    assert kwargs.get("add_generation_prompt") is True
    assert kwargs.get("tokenize") is False

    # process_mm_info — use_audio_in_video=False (sub-plan 2 는 audio/video skip).
    assert transformers_mock["process_mm_info"].call_count == 1
    _, kwargs_mm = transformers_mock["process_mm_info"].call_args
    assert kwargs_mm.get("use_audio_in_video") is False

    # generate — return_audio=False (텍스트만), use_audio_in_video=False.
    assert m.generate.call_count == 1
    _, gen_kwargs = m.generate.call_args
    assert gen_kwargs.get("return_audio") is False
    assert gen_kwargs.get("use_audio_in_video") is False

    # batch_decode 호출.
    assert p.batch_decode.call_count == 1


@pytest.mark.asyncio
async def test_send_message_error_emits_error_event(transformers_mock):
    """generate 가 raise → emit error 이벤트 (raise 전파 안 함)."""
    from screen_recorder.agent.backends import ChatInput, AgentEvent

    transformers_mock["model_inst"].generate = MagicMock(
        side_effect=RuntimeError("CUDA OOM"),
    )

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    errs = [r for r in received if isinstance(r, AgentEvent) and r.kind == "error"]
    assert len(errs) == 1
    assert "CUDA OOM" in errs[0].detail
