"""ImageGenRuntime + PixArtSigmaBackend 유닛 테스트.

heavy diffusers 의존성 (torch, PixArtSigmaPipeline) 은 mock — runtime / 시그널 흐름만 검증.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

import pytest
from PySide6.QtCore import QCoreApplication, QObject

# pytest-qt 의 qapp fixture 가 QApplication 을 보장. 모듈 레벨에서 QCoreApplication 을
# 만들면 dock 테스트 (QWidget 사용) 와 합쳤을 때 segfault 가 난다 (QCoreApplication
# vs QApplication 충돌). 따라서 fixture 로만 진입.
@pytest.fixture(autouse=True)
def _ensure_qapp(qapp):
    """qtbot/pytest-qt 의 qapp fixture 진입을 강제 — QApplication 보장."""
    yield qapp


def _process_events_until(predicate, timeout_s: float = 2.0) -> bool:
    """Qt 이벤트 펌프 — predicate 가 True 가 될 때까지 또는 timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


class _FakeBackend:
    """ImageGenBackend Protocol 구현 — diffusers 없이 동작."""

    def __init__(self, *, fail_msg: Optional[str] = None,
                 cancel_at_step: Optional[int] = None,
                 step_delay_s: float = 0.0) -> None:
        self.loaded = False
        self.load_calls = 0
        self.close_calls = 0
        self.cancel_calls = 0
        self.generate_calls = 0
        self._cancel_requested = False
        self._fail_msg = fail_msg
        self._cancel_at_step = cancel_at_step
        self._step_delay_s = step_delay_s
        self.last_params: dict[str, Any] = {}

    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.load_calls += 1
        self.loaded = True

    def generate(self, prompt, *, width=1024, height=1024,
                 num_inference_steps=20, guidance_scale=4.5,
                 seed=None, step_cb=None, out_path=None) -> Path:
        self.generate_calls += 1
        self.last_params = dict(
            prompt=prompt, width=width, height=height,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale, seed=seed,
        )
        if self._fail_msg:
            raise RuntimeError(self._fail_msg)
        for i in range(num_inference_steps):
            if self._step_delay_s > 0:
                time.sleep(self._step_delay_s)
            if step_cb is not None:
                step_cb(i + 1, num_inference_steps)
            if self._cancel_at_step is not None and i + 1 == self._cancel_at_step:
                self._cancel_requested = True
            if self._cancel_requested:
                raise InterruptedError("cancelled")
        # 가짜 png 경로 — 실제 파일은 안 만듦. 호출자가 image_ready 시그널만 받음.
        if out_path is None:
            out_path = Path(os.path.expanduser("~")) / ".fake_test_image.png"
        return out_path

    def request_cancel(self) -> None:
        self.cancel_calls += 1
        self._cancel_requested = True

    def close(self) -> None:
        self.close_calls += 1
        self.loaded = False


class _Catcher(QObject):
    """Signal 수신값 수집용."""

    def __init__(self) -> None:
        super().__init__()
        self.steps: list[tuple[int, int]] = []
        self.images: list[str] = []
        self.failed: list[str] = []
        self.cancelled = 0
        self.started = 0
        self.load_started = 0
        self.load_finished = 0


def _attach(rt, c: _Catcher) -> None:
    rt.step_progress.connect(lambda cur, tot: c.steps.append((cur, tot)))
    rt.image_ready.connect(lambda p: c.images.append(p))
    rt.generation_failed.connect(lambda m: c.failed.append(m))
    rt.generation_cancelled.connect(lambda: setattr(c, "cancelled", c.cancelled + 1))
    rt.generation_started.connect(lambda: setattr(c, "started", c.started + 1))
    rt.load_started.connect(lambda: setattr(c, "load_started", c.load_started + 1))
    rt.load_finished.connect(lambda: setattr(c, "load_finished", c.load_finished + 1))


def test_generate_happy_path_emits_steps_then_image():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend()
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    started = rt.generate("a cat", num_inference_steps=4)
    assert started is True

    ok = _process_events_until(lambda: c.images)
    assert ok, f"image_ready not emitted. failed={c.failed} cancelled={c.cancelled}"

    assert c.load_started == 1
    assert c.load_finished == 1
    assert c.started == 1
    assert c.steps == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert len(c.images) == 1
    assert c.failed == []
    assert c.cancelled == 0
    assert backend.generate_calls == 1


def test_generate_skips_load_if_already_loaded():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend()
    backend.loaded = True
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    rt.generate("a cat", num_inference_steps=2)
    ok = _process_events_until(lambda: c.images)
    assert ok

    assert backend.load_calls == 0   # 이미 loaded → load 호출 안 함
    assert c.load_started == 0
    assert c.load_finished == 0


def test_generate_failure_emits_failed_signal():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend(fail_msg="boom")
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    rt.generate("a cat", num_inference_steps=2)
    ok = _process_events_until(lambda: c.failed)
    assert ok
    assert c.failed == ["boom"]
    assert c.images == []
    assert c.cancelled == 0


def test_cancel_emits_cancelled_signal():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend(cancel_at_step=2, step_delay_s=0.01)
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    rt.generate("a cat", num_inference_steps=10)
    # 첫 step 까지 진행되게 잠시 펌프
    _process_events_until(lambda: len(c.steps) >= 1, timeout_s=1.0)
    # 외부에서 cancel — 그러면 다음 step 에서 InterruptedError
    rt.cancel()
    ok = _process_events_until(lambda: c.cancelled > 0, timeout_s=2.0)
    assert ok
    assert backend.cancel_calls >= 1
    assert c.images == []
    assert c.failed == []


def test_busy_blocks_second_generate():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend(step_delay_s=0.02)
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    ok1 = rt.generate("a", num_inference_steps=5)
    ok2 = rt.generate("b", num_inference_steps=5)
    assert ok1 is True
    assert ok2 is False
    # 끝나길 기다리고 마지막 확인.
    _process_events_until(lambda: c.images, timeout_s=3.0)
    assert backend.generate_calls == 1


def test_empty_prompt_emits_failed():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend()
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    started = rt.generate("   ", num_inference_steps=2)
    assert started is False
    _process_events_until(lambda: c.failed, timeout_s=0.5)
    assert c.failed and "비어" in c.failed[0]
    assert backend.generate_calls == 0


def test_close_calls_backend_close():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend()
    backend.loaded = True
    rt = ImageGenRuntime(backend=backend)
    rt.close()
    assert backend.close_calls == 1


def test_close_cancels_and_closes_when_busy():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend(step_delay_s=0.05)
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    rt.generate("a", num_inference_steps=20)
    _process_events_until(lambda: len(c.steps) >= 1, timeout_s=1.0)
    rt.close()
    # cancel 요청은 들어갔어야
    assert backend.cancel_calls >= 1
    # close 도 한 번
    assert backend.close_calls == 1


def test_params_pass_through_to_backend():
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend()
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    rt.generate(
        "test prompt",
        width=512, height=768,
        num_inference_steps=8,
        guidance_scale=3.0,
        seed=123,
    )
    _process_events_until(lambda: c.images, timeout_s=2.0)

    p = backend.last_params
    assert p["prompt"] == "test prompt"
    assert p["width"] == 512
    assert p["height"] == 768
    assert p["num_inference_steps"] == 8
    assert p["guidance_scale"] == 3.0
    assert p["seed"] == 123


def test_auto_translate_off_skips_translator(monkeypatch):
    """auto_translate=False 면 한국어 prompt 도 backend 에 그대로 전달."""
    from screen_recorder.image_gen.runtime import ImageGenRuntime
    from screen_recorder.image_gen import translator as t_mod

    backend = _FakeBackend()
    rt = ImageGenRuntime(backend=backend)
    rt.set_auto_translate(False)
    c = _Catcher()
    _attach(rt, c)

    # translator 가 호출되면 fail 시키는 sentinel — set_auto_translate(False) 면 안 불려야.
    monkeypatch.setattr(
        t_mod, "translate_to_english_sync",
        lambda *_a, **_kw: pytest.fail("translator should not be called when auto_translate=False"),
    )

    rt.generate("고양이", num_inference_steps=2)
    _process_events_until(lambda: c.images, timeout_s=2.0)

    assert backend.last_params["prompt"] == "고양이"


def test_auto_translate_replaces_prompt(monkeypatch):
    """auto_translate=True + 한국어 prompt → backend 는 영어 받음."""
    from screen_recorder.image_gen.runtime import ImageGenRuntime
    from screen_recorder.image_gen import translator as t_mod

    backend = _FakeBackend()
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    translated_emits: list[tuple[str, str]] = []
    rt.translated.connect(lambda src, dst: translated_emits.append((src, dst)))

    monkeypatch.setattr(
        t_mod, "translate_to_english_sync",
        lambda prompt, model="claude-haiku-4-5-20251001": "a calico cat",
    )

    rt.generate("고양이", num_inference_steps=2)
    _process_events_until(lambda: c.images, timeout_s=2.0)

    assert backend.last_params["prompt"] == "a calico cat"
    assert translated_emits == [("고양이", "a calico cat")]


def test_auto_translate_falls_back_on_failure(monkeypatch):
    """번역 실패 (None 반환) 시 원본 한국어 그대로 backend 에 전달."""
    from screen_recorder.image_gen.runtime import ImageGenRuntime
    from screen_recorder.image_gen import translator as t_mod

    backend = _FakeBackend()
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    monkeypatch.setattr(
        t_mod, "translate_to_english_sync",
        lambda *_a, **_kw: None,
    )

    rt.generate("고양이", num_inference_steps=2)
    _process_events_until(lambda: c.images, timeout_s=2.0)

    # backend 에는 원본 한국어 — translator 가 None 반환 → fallback.
    assert backend.last_params["prompt"] == "고양이"


def test_seed_negative_becomes_none():
    """seed=-1 (UI 의 '랜덤' 의미) 은 backend 에 None 으로 전달."""
    from screen_recorder.image_gen.runtime import ImageGenRuntime

    backend = _FakeBackend()
    rt = ImageGenRuntime(backend=backend)
    c = _Catcher()
    _attach(rt, c)

    rt.generate("x", num_inference_steps=2, seed=-1)
    _process_events_until(lambda: c.images, timeout_s=2.0)

    assert backend.last_params["seed"] is None
