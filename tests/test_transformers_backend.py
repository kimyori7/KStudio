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
