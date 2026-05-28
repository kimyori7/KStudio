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


def _setup_streamer_mock(transformers_mock, chunks: list[str]):
    """streamer 가 chunks 순서대로 yield 하도록 mock 설정. generate 는 None 반환.

    Task 5 의 streaming 리팩토링 후 — 기존 send_message 테스트들이 batch_decode
    경로 대신 streamer 경로를 가게 됨. 각 send_message 테스트는 이 헬퍼로 streamer
    응답 정의.
    """
    streamer_inst = MagicMock()
    streamer_inst.__iter__ = MagicMock(return_value=iter(chunks))
    streamer_inst.end = MagicMock()
    transformers_mock["transformers"].TextIteratorStreamer = MagicMock(
        return_value=streamer_inst,
    )
    transformers_mock["model_inst"].generate = MagicMock(return_value=None)
    return streamer_inst


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
    # torch.cuda.empty_cache() 도 호출돼야 — caching allocator 의 unused block 반환.
    # gc 만으로는 부족 (PyTorch 가 GPU 메모리 잡고 있어 다음 모델 로드 시 OOM).
    fake_cuda = transformers_mock["torch"].cuda
    if hasattr(fake_cuda, "empty_cache"):
        # MagicMock 이라 call_count 검증 가능 — is_available 가 True 반환하면 호출됨.
        # mock 기본은 truthy 라 호출 경로 진입.
        assert fake_cuda.empty_cache.call_count >= 1, (
            "torch.cuda.empty_cache() 호출 안 됨 — caching allocator 가 VRAM 안 놔줌"
        )


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

    _setup_streamer_mock(transformers_mock, ["안녕하세요, 무엇을 도와드릴까요?"])

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

    _setup_streamer_mock(transformers_mock, ["응답"])

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


@pytest.mark.asyncio
async def test_send_message_with_image_writes_temp_and_cleans_up(
    transformers_mock, tmp_path, monkeypatch,
):
    """image bytes → temp PNG → conversation 에 path → send_message 끝나면 unlink."""
    import tempfile
    from pathlib import Path
    from screen_recorder.agent.backends import ChatInput

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    # process_mm_info 가 conversation 에서 image path 를 받았는지 검증.
    captured_conv = []
    def _capture_mm(conv, use_audio_in_video=False):
        captured_conv.append(conv)
        return [], ["fake_image_pixel_array"], []
    transformers_mock["process_mm_info"].side_effect = _capture_mm

    _setup_streamer_mock(transformers_mock, ["응답"])

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")

    png = b"\x89PNG\r\n\x1a\nfake_image"
    received: list = []
    await be.send_message(
        ChatInput(text="이거 뭐야?", images=[png]),
        received.append,
    )

    # process_mm_info 가 image block 포함된 conversation 받음.
    assert len(captured_conv) == 1
    user_msg = captured_conv[0][1]
    user_content = user_msg["content"]
    img_blocks = [b for b in user_content if b.get("type") == "image"]
    assert len(img_blocks) == 1

    # temp 파일은 send_message finally 에서 unlink — 흔적 없음.
    assert be._temp_files == []
    # 실제로 path 가 사라졌는지.
    img_path = Path(img_blocks[0]["image"])
    assert not img_path.exists()


@pytest.mark.asyncio
async def test_send_message_with_image_cleans_up_on_error(
    transformers_mock, tmp_path, monkeypatch,
):
    """generate 실패해도 temp 파일 정리 — finally 보장."""
    import tempfile
    from screen_recorder.agent.backends import ChatInput

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    transformers_mock["model_inst"].generate = MagicMock(
        side_effect=RuntimeError("boom"),
    )

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    await be.send_message(
        ChatInput(text="x", images=[b"\x89PNG..."]),
        lambda _: None,
    )

    # 정리됨.
    assert be._temp_files == []


@pytest.mark.asyncio
async def test_send_message_streams_chunks_one_by_one(transformers_mock):
    """TextIteratorStreamer 가 yield 하는 chunk 마다 AgentMessage emit.

    회귀 보호: streaming 끊기면 Claude UX 와 일관성 깨짐 — 사용자가 응답 끝까지
    기다려야 첫 글자 보임.
    """
    from screen_recorder.agent.backends import ChatInput, AgentMessage

    chunks = ["안녕", "하세요", ", ", "반갑", "습니다."]

    streamer_inst = MagicMock()
    streamer_inst.__iter__ = MagicMock(return_value=iter(chunks))
    streamer_inst.end = MagicMock()
    transformers_mock["transformers"].TextIteratorStreamer = MagicMock(
        return_value=streamer_inst,
    )
    transformers_mock["model_inst"].generate = MagicMock(return_value=None)

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    received: list = []
    await be.send_message(ChatInput(text="안녕"), received.append)

    text_chunks = [r.text for r in received
                    if isinstance(r, AgentMessage) and r.role == "assistant"]
    assert text_chunks == chunks


@pytest.mark.asyncio
async def test_cancel_sets_stop_flag_mid_generation(transformers_mock):
    """cancel() 호출 → stop_flag.set() → 다음 토큰에서 StoppingCriteria True.

    회귀 보호: cancel 안 되면 사용자가 잘못된 응답 끝까지 봐야 함.
    """
    from screen_recorder.agent.backends import ChatInput

    # streamer 가 두 chunk yield (헬퍼 사용).
    _setup_streamer_mock(transformers_mock, ["chunk1", "chunk2"])

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")

    async def _runner():
        await be.send_message(ChatInput(text="hi"), lambda _: None)

    task = asyncio.create_task(_runner())
    await asyncio.sleep(0.01)   # send_message 가 stop_flag 만들 시간.
    await be.cancel()           # 예외 없이 끝나야 함.
    await task

    # 후처리: finally 에서 None 복원.
    assert be._stop_flag is None


# ─────────────────────────────────────────────────────────────────────────────
# 2026-05-21 사용자 보고 회귀 보호:
# - "Qwen 이 1234567 ms 같은 가짜 데이터 생성" — Claude SYSTEM_PROMPT 가 잘못
#   전달돼 학습 데이터 모방. Qwen 전용 prompt 사용 회귀 보호.
# - "직전 대화도 기억 못함" — history 누적 안 됨. _history + commit 회귀 보호.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_session_ignores_caller_prompt_and_uses_qwen_specific(
    transformers_mock,
):
    """start_session 의 system_prompt 는 무시 — Qwen 전용 prompt 사용."""
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(
        system_prompt="당신은 도구를 호출하는 Claude 입니다. propose_effect 사용...",
        tools={"mcp_server": object(), "allowed_tools": ["propose_effect"]},
        model="qwen25-omni-7b",
    )
    # 호출자 prompt (Claude impersonation + 도구 호출 강요) 가 그대로 들어가면 안 됨.
    assert "당신은 도구를 호출하는 Claude" not in be._system_prompt
    assert "propose_effect 사용" not in be._system_prompt
    # Qwen prompt 핵심: "도구 사용 불가" + "가짜 데이터 금지" 안내 포함.
    assert "도구" in be._system_prompt
    assert ("가상" in be._system_prompt
            or "거짓" in be._system_prompt
            or "추측" in be._system_prompt)


@pytest.mark.asyncio
async def test_history_accumulates_across_send_messages(transformers_mock):
    """매 send_message 가 history 에 user/assistant 누적 — 다음 turn 의 conversation 에 포함."""
    from screen_recorder.agent.backends import ChatInput

    streamer_inst = MagicMock()
    streamer_inst.__iter__ = MagicMock(return_value=iter(["응답1"]))
    streamer_inst.end = MagicMock()
    transformers_mock["transformers"].TextIteratorStreamer = MagicMock(
        return_value=streamer_inst,
    )
    transformers_mock["model_inst"].generate = MagicMock(return_value=None)

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    assert be._history == []

    await be.send_message(ChatInput(text="첫번째"), lambda _: None)
    # user + assistant 누적.
    assert len(be._history) == 2
    assert be._history[0]["role"] == "user"
    assert be._history[0]["content"] == "첫번째"
    assert be._history[1]["role"] == "assistant"
    assert be._history[1]["content"] == "응답1"

    # 두 번째 send — apply_chat_template 가 받은 conversation 에 첫 turn 포함됨.
    streamer2 = MagicMock()
    streamer2.__iter__ = MagicMock(return_value=iter(["응답2"]))
    streamer2.end = MagicMock()
    transformers_mock["transformers"].TextIteratorStreamer = MagicMock(
        return_value=streamer2,
    )

    captured_conv = []
    def _capture_template(conv, **kwargs):
        captured_conv.append(list(conv))
        return "<prompt>"
    transformers_mock["processor_inst"].apply_chat_template = MagicMock(
        side_effect=_capture_template,
    )

    await be.send_message(ChatInput(text="두번째"), lambda _: None)
    conv = captured_conv[0]
    # system + 첫 user + 첫 assistant + 두 번째 user = 4.
    assert len(conv) == 4
    assert conv[0]["role"] == "system"
    assert conv[1]["role"] == "user" and conv[1]["content"] == "첫번째"
    assert conv[2]["role"] == "assistant" and conv[2]["content"] == "응답1"
    assert conv[3]["role"] == "user" and conv[3]["content"] == "두번째"


@pytest.mark.asyncio
async def test_close_and_clear_history_reset_accumulation(transformers_mock):
    """close() / clear_history() 가 history 비움."""
    from screen_recorder.agent.backends import ChatInput

    streamer_inst = MagicMock()
    streamer_inst.__iter__ = MagicMock(return_value=iter(["응답"]))
    streamer_inst.end = MagicMock()
    transformers_mock["transformers"].TextIteratorStreamer = MagicMock(
        return_value=streamer_inst,
    )
    transformers_mock["model_inst"].generate = MagicMock(return_value=None)

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    await be.send_message(ChatInput(text="x"), lambda _: None)
    assert len(be._history) == 2

    be.clear_history()
    assert be._history == []

    # close() 도 reset.
    be._history = [{"role": "user", "content": "y"}]
    await be.close()
    assert be._history == []


def test_stopping_criteria_returns_true_when_flag_set(transformers_mock):
    """_make_stopping_criteria 의 콜백이 flag 상태 반영."""
    import threading
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    flag = threading.Event()
    be._make_stopping_criteria(flag)

    # StoppingCriteriaList 가 (callbacks,) 로 호출됐는지 확인.
    transformers_mock["transformers"].StoppingCriteriaList.assert_called_once()
    args, _ = transformers_mock["transformers"].StoppingCriteriaList.call_args
    callbacks = list(args[0])
    assert len(callbacks) == 1

    cb = callbacks[0]
    # flag set 전: False.
    assert cb(None, None) is False
    # flag set 후: True.
    flag.set()
    assert cb(None, None) is True


# ─────────────────────────────────────────────────────────────────────────────
# Task 15: text-only / Omni 모델 분기 테스트
# Critical fix: Qwen2.5-7B-Instruct(text-only) 로드 시 arch mismatch 방지.
# ─────────────────────────────────────────────────────────────────────────────


def test_ensure_model_loaded_uses_text_only_classes_for_text_only_model(transformers_mock):
    """text-only modalities → AutoModelForCausalLM + AutoTokenizer 호출 (Omni 클래스 X)."""
    backend = TransformersBackend(
        repo_id="Qwen/Qwen2.5-7B-Instruct",
        modalities=frozenset({"text"}),
    )
    asyncio.run(backend._ensure_model_loaded())

    # AutoModelForCausalLM.from_pretrained 가 호출되어야 (Omni 아님).
    assert transformers_mock["transformers"].AutoModelForCausalLM.from_pretrained.called, (
        "text-only 모델인데 AutoModelForCausalLM 안 쓰임"
    )
    assert transformers_mock["transformers"].AutoTokenizer.from_pretrained.called, (
        "text-only 모델인데 AutoTokenizer 안 쓰임"
    )
    # Omni 클래스는 호출 안 됨.
    assert not transformers_mock["transformers"].Qwen2_5OmniForConditionalGeneration.from_pretrained.called, (
        "text-only 모델인데 Omni 클래스 호출됨"
    )
    assert not transformers_mock["transformers"].Qwen2_5OmniProcessor.from_pretrained.called, (
        "text-only 모델인데 Omni Processor 호출됨"
    )


def test_ensure_model_loaded_uses_omni_classes_for_multimodal_model(transformers_mock):
    """multimodal modalities → Qwen2_5OmniForConditionalGeneration 호출 (회귀 보호)."""
    backend = TransformersBackend(
        repo_id="Qwen/Qwen2.5-Omni-7B",
        modalities=frozenset({"text", "image", "audio", "video"}),
    )
    asyncio.run(backend._ensure_model_loaded())

    assert transformers_mock["transformers"].Qwen2_5OmniForConditionalGeneration.from_pretrained.called
    assert transformers_mock["transformers"].Qwen2_5OmniProcessor.from_pretrained.called
    assert not transformers_mock["transformers"].AutoModelForCausalLM.from_pretrained.called


def test_default_modalities_is_omni_for_backward_compatibility(transformers_mock):
    """modalities 인자 안 주면 Omni 가정 (기존 동작 유지)."""
    backend = TransformersBackend(repo_id="Qwen/test")
    asyncio.run(backend._ensure_model_loaded())

    assert transformers_mock["transformers"].Qwen2_5OmniForConditionalGeneration.from_pretrained.called


@pytest.mark.asyncio
async def test_run_one_generate_text_only_does_not_call_process_mm_info(transformers_mock):
    """text-only _run_one_generate → process_mm_info 미호출 + return_audio/use_audio_in_video 인자 없음.

    회귀 보호: Omni 전용 kwargs 가 AutoModelForCausalLM.generate 에 넘어가면 TypeError.

    text-only path 는 AutoModelForCausalLM.from_pretrained 가 반환하는 인스턴스에서
    generate 를 호출 — 그 인스턴스를 직접 참조해서 검증.
    """
    from screen_recorder.agent.backends import ChatInput

    # text-only path 의 model 인스턴스 — AutoModelForCausalLM.from_pretrained 반환값.
    text_model_inst = MagicMock()
    text_model_inst.device = "cpu"
    text_model_inst.dtype = "float32"
    text_model_inst.generate = MagicMock(return_value=None)
    transformers_mock["transformers"].AutoModelForCausalLM.from_pretrained = MagicMock(
        return_value=text_model_inst,
    )

    # text-only tokenizer 인스턴스.
    text_tokenizer_inst = MagicMock()
    text_tokenizer_inst.apply_chat_template = MagicMock(return_value="<prompt>")
    fake_text_inputs = MagicMock()
    fake_text_inputs.to = MagicMock(return_value=fake_text_inputs)
    text_tokenizer_inst.return_value = fake_text_inputs
    transformers_mock["transformers"].AutoTokenizer.from_pretrained = MagicMock(
        return_value=text_tokenizer_inst,
    )

    _setup_streamer_mock(transformers_mock, ["안녕"])
    # streamer 는 processor_inst 기준으로 만들어지므로 text_tokenizer_inst 에도 등록.
    # TextIteratorStreamer 는 이미 mock — streamer 는 transformers_mock 의 TextIteratorStreamer.

    backend = TransformersBackend(
        repo_id="Qwen/Qwen2.5-7B-Instruct",
        modalities=frozenset({"text"}),
    )
    await backend.start_session(system_prompt="sys", tools={}, model="qwen25-7b-instruct")
    await backend.send_message(ChatInput(text="안녕"), lambda _: None)

    # process_mm_info 호출 안 됨.
    assert transformers_mock["process_mm_info"].call_count == 0, (
        "text-only 모델인데 process_mm_info 호출됨"
    )

    # text-only model 의 generate 호출 확인.
    assert text_model_inst.generate.call_count == 1
    _, gen_kwargs = text_model_inst.generate.call_args
    assert "return_audio" not in gen_kwargs, "text-only generate 에 return_audio 가 있음"
    assert "use_audio_in_video" not in gen_kwargs, "text-only generate 에 use_audio_in_video 가 있음"


@pytest.mark.asyncio
async def test_run_one_generate_omni_calls_process_mm_info(transformers_mock):
    """Omni _run_one_generate → process_mm_info 호출 + return_audio/use_audio_in_video 전달 (회귀 보호)."""
    from screen_recorder.agent.backends import ChatInput

    _setup_streamer_mock(transformers_mock, ["응답"])

    backend = TransformersBackend(
        repo_id="Qwen/Qwen2.5-Omni-7B",
        modalities=frozenset({"text", "image", "audio", "video"}),
    )
    await backend.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    await backend.send_message(ChatInput(text="안녕"), lambda _: None)

    assert transformers_mock["process_mm_info"].call_count == 1
    assert transformers_mock["model_inst"].generate.call_count == 1
    _, gen_kwargs = transformers_mock["model_inst"].generate.call_args
    assert gen_kwargs.get("return_audio") is False
    assert gen_kwargs.get("use_audio_in_video") is False


# ============================================================
# 2026-05-22 — bitsandbytes 4-bit (NF4) 양자화 옵션.
# Flash Attention 2 가 sm_120 (Blackwell) 미지원이라 가장 효과 큰 가속 대안.
# ============================================================
@pytest.mark.asyncio
async def test_ensure_model_loaded_with_4bit_passes_quantization_config(transformers_mock):
    """load_in_4bit=True → BitsAndBytesConfig 생성 + from_pretrained 의 quantization_config kwarg 로 전달.

    회귀 보호: 4-bit 가 무음으로 미적용 되면 사용자 PC 메모리 14GB → 7GB 절감 효과 소실.
    """
    be = TransformersBackend(
        repo_id="Qwen/Qwen2.5-Omni-7B",
        load_in_4bit=True,
    )
    await be._ensure_model_loaded()
    _, from_pretrained_kwargs = transformers_mock["model_cls"].from_pretrained.call_args
    assert "quantization_config" in from_pretrained_kwargs, "4-bit 인데 quantization_config 누락"
    # torch_dtype 는 양자화 시 명시 X — BitsAndBytesConfig 의 compute_dtype 이 우선.
    assert "torch_dtype" not in from_pretrained_kwargs
    # BitsAndBytesConfig 가 NF4 + double quant + CPU offload 옵션으로 호출되었는지.
    bnb_call = transformers_mock["transformers"].BitsAndBytesConfig.call_args
    assert bnb_call.kwargs.get("load_in_4bit") is True
    assert bnb_call.kwargs.get("bnb_4bit_quant_type") == "nf4"
    assert bnb_call.kwargs.get("bnb_4bit_use_double_quant") is True
    # CPU offload — Qwen2.5-Omni 같이 ~10B 합산 모델이 16GB GPU 에 빠듯할 때 accelerate
    # 가 talker 등 안 쓰는 모듈을 CPU 로 보낼 수 있게. 없으면 'Some modules dispatched on
    # CPU or the disk' 에러로 로드 실패.
    assert bnb_call.kwargs.get("llm_int8_enable_fp32_cpu_offload") is True


@pytest.mark.asyncio
async def test_ensure_model_loaded_without_4bit_uses_torch_dtype(transformers_mock):
    """load_in_4bit=False (기본) → 기존 torch_dtype='auto' 경로 유지 (회귀 보호)."""
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be._ensure_model_loaded()
    _, kwargs = transformers_mock["model_cls"].from_pretrained.call_args
    assert kwargs.get("torch_dtype") == "auto"
    assert "quantization_config" not in kwargs


@pytest.mark.asyncio
async def test_ensure_model_loaded_text_only_with_4bit(transformers_mock):
    """text-only (Qwen2.5-7B-Instruct) + load_in_4bit=True 도 동일하게 quantization_config 전달.

    AutoModelForCausalLM 경로도 4-bit 옵션 누리도록.
    """
    fake_auto_model = MagicMock()
    fake_auto_model.from_pretrained = MagicMock(return_value=transformers_mock["model_inst"])
    fake_auto_tokenizer = MagicMock()
    fake_auto_tokenizer.from_pretrained = MagicMock(return_value=transformers_mock["processor_inst"])
    transformers_mock["transformers"].AutoModelForCausalLM = fake_auto_model
    transformers_mock["transformers"].AutoTokenizer = fake_auto_tokenizer

    be = TransformersBackend(
        repo_id="Qwen/Qwen2.5-7B-Instruct",
        modalities=frozenset({"text"}),
        load_in_4bit=True,
    )
    await be._ensure_model_loaded()
    _, kwargs = fake_auto_model.from_pretrained.call_args
    assert "quantization_config" in kwargs
    assert "torch_dtype" not in kwargs


# ─────────────────────────────────────────────────────────────────────────
# VL family (Qwen3-VL, Qwen2.5-VL) — Omni 와 다른 클래스/processor.
# ─────────────────────────────────────────────────────────────────────────


def _setup_vl_mocks(transformers_mock):
    """transformers_mock 에 VL 경로용 AutoModelForImageTextToText + AutoProcessor 추가.

    apply_chat_template(return_dict=True) 가 dict-like inputs 를 반환하도록 설정.
    """
    fake_inputs = MagicMock()
    fake_inputs.to = MagicMock(return_value=fake_inputs)
    # **inputs 언패킹용 — generate(**inputs, ...) 가 동작하도록 keys/values mocking.
    fake_inputs.keys = MagicMock(return_value=["input_ids"])
    fake_inputs.__getitem__ = MagicMock(return_value="fake_tensor")
    # apply_chat_template 가 호출 인자에 따라 다른 값 반환:
    #   tokenize=False → 문자열 (Omni 경로)
    #   tokenize=True + return_dict=True → dict-like (VL 경로)
    def _apply(conv, **kw):
        if kw.get("tokenize") and kw.get("return_dict"):
            return fake_inputs
        return "<prompt>"
    transformers_mock["processor_inst"].apply_chat_template = MagicMock(side_effect=_apply)

    fake_auto_im2txt = MagicMock()
    fake_auto_im2txt.from_pretrained = MagicMock(return_value=transformers_mock["model_inst"])
    fake_auto_processor = MagicMock()
    fake_auto_processor.from_pretrained = MagicMock(return_value=transformers_mock["processor_inst"])
    transformers_mock["transformers"].AutoModelForImageTextToText = fake_auto_im2txt
    transformers_mock["transformers"].AutoProcessor = fake_auto_processor
    return fake_auto_im2txt, fake_auto_processor, fake_inputs


def test_is_vl_detects_qwen3_vl_repo_ids():
    """`_is_vl()` — repo_id 의 '-VL-' 패턴 (Omni 제외) 인식.

    Why: 모델 시리즈에 따라 다른 transformers 클래스/processor 사용. Omni 와 VL
    분기 잘못되면 load_in_4bit 옵션 / process_mm_info 호출 같은 omni 전용 동작이
    VL 에 새어 들어가 generate 망가짐.
    """
    vl3 = TransformersBackend(repo_id="Qwen/Qwen3-VL-4B-Instruct",
                              modalities=frozenset({"text", "image", "video"}))
    vl25 = TransformersBackend(repo_id="Qwen/Qwen2.5-VL-3B-Instruct",
                               modalities=frozenset({"text", "image", "video"}))
    omni = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    text_only = TransformersBackend(repo_id="Qwen/Qwen2.5-7B-Instruct",
                                    modalities=frozenset({"text"}))

    assert vl3._is_vl() is True
    assert vl25._is_vl() is True
    assert omni._is_vl() is False
    assert text_only._is_vl() is False


@pytest.mark.asyncio
async def test_vl_load_uses_auto_image_text_to_text_class(transformers_mock):
    """VL repo_id 면 AutoModelForImageTextToText + AutoProcessor 호출 — Omni 클래스 X.

    회귀 보호: Qwen3-VL 은 Omni 클래스로 로드하면 architecture mismatch — VL 전용
    AutoClass 가 HF config 보고 실제 클래스 (Qwen3VLForConditionalGeneration) 자동 선택.
    """
    fake_auto_im2txt, fake_auto_proc, _ = _setup_vl_mocks(transformers_mock)

    be = TransformersBackend(
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        modalities=frozenset({"text", "image", "video"}),
    )
    await be._ensure_model_loaded()

    assert fake_auto_im2txt.from_pretrained.call_count == 1
    assert fake_auto_proc.from_pretrained.call_count == 1
    # Omni 클래스는 호출 안 됨.
    assert transformers_mock["model_cls"].from_pretrained.call_count == 0


@pytest.mark.asyncio
async def test_vl_send_message_uses_apply_chat_template_with_return_dict(transformers_mock):
    """VL send_message — apply_chat_template(return_dict=True, tokenize=True) 로 한 번에
    비전 입력 처리 + process_mm_info 호출 안 함.

    회귀 보호: VL family 는 qwen_omni_utils 의존 없음. apply_chat_template 자체가
    image path 받아서 pixel_values 까지 만들어줌. Omni 경로의 process_mm_info 가
    VL 에 새면 의존성 에러 (없는 import) 발생.
    """
    from screen_recorder.agent.backends import ChatInput

    _setup_vl_mocks(transformers_mock)
    _setup_streamer_mock(transformers_mock, ["VL 응답"])

    be = TransformersBackend(
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        modalities=frozenset({"text", "image", "video"}),
    )
    await be.start_session(system_prompt="sys", tools={}, model="qwen3-vl-4b-instruct")
    await be.send_message(ChatInput(text="이거 봐"), lambda _: None)

    # apply_chat_template 한 번은 tokenize=True + return_dict=True (VL 경로 시그니처).
    p = transformers_mock["processor_inst"]
    vl_calls = [
        c for c in p.apply_chat_template.call_args_list
        if c.kwargs.get("tokenize") is True and c.kwargs.get("return_dict") is True
    ]
    assert len(vl_calls) >= 1, "VL 경로는 apply_chat_template(tokenize=True, return_dict=True) 호출해야 함"

    # process_mm_info 호출 X — VL 은 qwen_omni_utils 안 씀.
    assert transformers_mock["process_mm_info"].call_count == 0


@pytest.mark.asyncio
async def test_vl_generate_does_not_pass_omni_kwargs(transformers_mock):
    """VL generate kwargs 에 return_audio / use_audio_in_video 없음 — Omni 전용 인자.

    회귀 보호: Qwen3VLForConditionalGeneration.generate 는 이 인자 모르므로 TypeError.
    """
    from screen_recorder.agent.backends import ChatInput

    _setup_vl_mocks(transformers_mock)
    _setup_streamer_mock(transformers_mock, ["응답"])

    be = TransformersBackend(
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        modalities=frozenset({"text", "image", "video"}),
    )
    await be.start_session(system_prompt="sys", tools={}, model="qwen3-vl-4b-instruct")
    await be.send_message(ChatInput(text="hi"), lambda _: None)

    m = transformers_mock["model_inst"]
    assert m.generate.call_count == 1
    _, gen_kwargs = m.generate.call_args
    assert "return_audio" not in gen_kwargs
    assert "use_audio_in_video" not in gen_kwargs


def test_history_char_limit_scales_with_model_size():
    """모델 크기 별 다른 history 한도 — 작을수록 KV cache 여유 많아 길게.

    회귀 보호 (2026-05-26): 4B 가 16K char 면 5060 Ti 한계에 거의 fit, 2B 면 100K
    까지 가능. Claude 200K 컨텍스트는 cloud 라 비교 불가 — 로컬은 GPU VRAM 천장.
    """
    vl2b = TransformersBackend(repo_id="Qwen/Qwen3-VL-2B-Instruct",
                                modalities=frozenset({"text", "image", "video"}))
    vl4b = TransformersBackend(repo_id="Qwen/Qwen3-VL-4B-Instruct",
                                modalities=frozenset({"text", "image", "video"}))
    omni = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    # 작을수록 더 넉넉.
    assert vl2b._history_char_limit() > vl4b._history_char_limit()
    assert vl4b._history_char_limit() >= omni._history_char_limit()
    # VL-2B 는 적어도 50K (Sonnet 의 4분의 1 정도) 는 보장.
    assert vl2b._history_char_limit() >= 50_000


def test_trim_history_below_limit_keeps_all():
    """누적 char 가 한도 이하면 trim 안 함."""
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    be._history = [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "네 안녕하세요"},
    ]
    be._trim_history()
    assert len(be._history) == 2


def test_trim_history_above_limit_removes_oldest_pairs():
    """누적 char 가 MAX_HISTORY_CHARS 넘으면 가장 오래된 user-assistant pair 부터 제거.

    회귀 보호 (2026-05-26): 무한 누적 시 KV cache 폭증으로 VRAM spillover → 응답 느려짐.
    """
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    # Omni-7B 한도 = 16000. 각 3500 char 메시지 6개 → 21000 char (한도 초과).
    big = "X" * 3500
    be._history = [
        {"role": "user", "content": big + "_u1"},
        {"role": "assistant", "content": big + "_a1"},
        {"role": "user", "content": big + "_u2"},
        {"role": "assistant", "content": big + "_a2"},
        {"role": "user", "content": big + "_u3"},
        {"role": "assistant", "content": big + "_a3"},
    ]
    be._trim_history()

    # 한도 내로 줄어들었어야.
    limit = be._history_char_limit()
    total = sum(be._estimate_msg_chars(m) for m in be._history)
    assert total <= limit, f"trim 후에도 {total} char (한도 {limit})"
    # 첫 메시지는 user 로 유지.
    assert be._history[0]["role"] == "user"
    # 가장 최근 turn (_u3 / _a3) 은 보존됐어야.
    assistant_texts = [m["content"] for m in be._history if m["role"] == "assistant"]
    assert any("_a3" in t for t in assistant_texts), "최근 assistant turn 누락"


def test_trim_history_pops_tool_result_at_head():
    """trim 으로 head 가 tool_result (앞 assistant.tool_use 잘림) 되면 추가 pop.

    chat_template strict alternation 보장.
    """
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    # Omni-7B 한도 16K, 각 3000 char × 6 = 18000 → trim 유발.
    big = "X" * 3000
    # tool_result 시퀀스 시뮬레이션 — 5쌍 만들어서 trim 유발.
    be._history = [
        {"role": "user", "content": big},
        {"role": "assistant", "content": big + "tool_use_xml"},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "output": big}]},
        {"role": "assistant", "content": big},
        {"role": "user", "content": big},
        {"role": "assistant", "content": big},
    ]
    be._trim_history()
    # head 가 user 여야.
    assert be._history[0]["role"] == "user"
    # 그 head 가 tool_result 가 아니어야 (일반 user message).
    head_content = be._history[0]["content"]
    if isinstance(head_content, list):
        tool_results = [b for b in head_content if isinstance(b, dict) and b.get("type") == "tool_result"]
        assert not tool_results, f"head 가 여전히 tool_result: {be._history[0]}"


@pytest.mark.asyncio
async def test_send_message_calls_empty_cache_in_finally(transformers_mock):
    """매 send_message finally 에서 torch.cuda.empty_cache 호출 — KV cache 누적 회수.

    회귀 보호 (2026-05-26): 매 메시지마다 점점 느려지는 spillover.
    """
    from screen_recorder.agent.backends import ChatInput

    _setup_streamer_mock(transformers_mock, ["응답"])

    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    await be.start_session(system_prompt="sys", tools={}, model="qwen25-omni-7b")
    await be.send_message(ChatInput(text="안녕"), lambda _: None)

    # send_message 의 finally 안에서 empty_cache 한 번 호출됐어야.
    fake_cuda = transformers_mock["torch"].cuda
    if hasattr(fake_cuda, "empty_cache"):
        assert fake_cuda.empty_cache.call_count >= 1, (
            "send_message finally 에서 empty_cache 미호출 — KV cache 누적 위험"
        )


def test_estimate_msg_chars_handles_text_image_video_blocks():
    """_estimate_msg_chars — str / list-of-blocks 안전 처리."""
    be = TransformersBackend(repo_id="Qwen/Qwen2.5-Omni-7B")
    # str.
    assert be._estimate_msg_chars({"content": "안녕"}) == 2
    # list of text.
    msg = {"content": [{"type": "text", "text": "hello"}]}
    assert be._estimate_msg_chars(msg) == 5
    # image block — 어림 1024.
    msg = {"content": [{"type": "image", "image": "/path/x.png"}]}
    assert be._estimate_msg_chars(msg) == 1024
    # video block — 어림 4096.
    msg = {"content": [{"type": "video", "video": "/path/x.mp4"}]}
    assert be._estimate_msg_chars(msg) == 4096
    # tool_result with text output.
    msg = {"content": [{"type": "tool_result", "tool_use_id": "1", "output": "ABCDE"}]}
    assert be._estimate_msg_chars(msg) == 5
    # 빈/이상한 content.
    assert be._estimate_msg_chars({"content": ""}) == 0
    assert be._estimate_msg_chars({"content": None}) == 0
    assert be._estimate_msg_chars({}) == 0


def test_registry_has_qwen3_vl_4b_entry():
    """ModelRegistry 에 qwen3-vl-4b-instruct 항목 존재 — UI 모델 콤보에 노출되도록."""
    from screen_recorder.agent.models.registry import ModelRegistry
    reg = ModelRegistry()
    meta = reg.get("qwen3-vl-4b-instruct")
    assert meta is not None
    assert meta.runtime == "transformers"
    assert meta.repo_id == "Qwen/Qwen3-VL-4B-Instruct"
    # 비전·영상 OK, audio 는 명시적으로 빠져야 함 (Whisper 로 우회 설계).
    assert "image" in meta.modalities
    assert "video" in meta.modalities
    assert "audio" not in meta.modalities
    # 도구 호출은 prompted — VL 모델은 official 만으론 형식 안 따라옴 (2026-05-26).
    assert meta.tool_strategy == "prompted"


def test_registry_has_qwen3_vl_2b_entry():
    """ModelRegistry 에 qwen3-vl-2b-instruct (최경량) 항목 존재.

    회귀 보호 (2026-05-26): 5060 Ti + 다른 process 점유 환경에서 4B 가 spillover →
    안전 옵션으로 2B 도입. 4B 와 동일 shape 의 메타.
    """
    from screen_recorder.agent.models.registry import ModelRegistry
    reg = ModelRegistry()
    meta = reg.get("qwen3-vl-2b-instruct")
    assert meta is not None
    assert meta.runtime == "transformers"
    assert meta.repo_id == "Qwen/Qwen3-VL-2B-Instruct"
    assert "image" in meta.modalities
    assert "video" in meta.modalities
    assert "audio" not in meta.modalities
    assert meta.tool_strategy == "prompted"
    # VRAM 추정 — 4B (11GB) 보다 작아야.
    assert meta.estimated_vram_gb < 8.0, "2B 는 4B 보다 작은 VRAM 추정값이어야"
