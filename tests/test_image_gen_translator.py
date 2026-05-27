"""image_gen.translator — 한국어 감지 + Claude SDK 자동 번역.

Claude SDK 실제 호출은 비용/속도 때문에 mock — 동작 흐름만 검증.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear_translation_cache():
    """각 테스트가 깨끗한 캐시로 시작."""
    from screen_recorder.image_gen import translator
    translator.clear_translation_cache()
    yield
    translator.clear_translation_cache()


def test_has_korean_detects_hangul():
    from screen_recorder.image_gen.translator import has_korean

    assert has_korean("고양이") is True
    assert has_korean("a cat 고양이 sitting") is True
    assert has_korean("ㄱㄴㄷ") is False   # 자모만으론 False (음절 가~힣 만)
    assert has_korean("") is False
    assert has_korean("a calico cat") is False
    assert has_korean("123 ABC !@#") is False


def test_translate_sync_returns_none_for_english_input():
    from screen_recorder.image_gen.translator import translate_to_english_sync

    # 영어 입력 — Claude 호출 없이 즉시 None.
    assert translate_to_english_sync("a calico cat") is None
    assert translate_to_english_sync("") is None


def test_translate_sync_returns_none_on_sdk_failure(monkeypatch):
    """기본 (Qwen3-VL) 로드 실패 시 None — 호출자가 원본 fallback."""
    from screen_recorder.image_gen import translator as mod

    def _boom(prompt):
        raise RuntimeError("qwen not available")

    monkeypatch.setattr(mod, "_translate_via_qwen", _boom)
    result = mod.translate_to_english_sync("고양이")
    assert result is None


def test_translate_sync_nllb_backend_returns_none_on_failure(monkeypatch):
    """backend='nllb' 명시 시 fail → None fallback."""
    from screen_recorder.image_gen import translator as mod

    def _boom(prompt):
        raise RuntimeError("nllb not available")

    monkeypatch.setattr(mod, "_translate_via_nllb", _boom)
    result = mod.translate_to_english_sync("고양이", backend="nllb")
    assert result is None


def test_translate_sync_claude_backend_returns_none_on_sdk_failure(monkeypatch):
    """backend='claude' 명시 시 SDK 실패도 None fallback."""
    from screen_recorder.image_gen import translator as mod

    async def _boom(prompt, model):
        raise RuntimeError("claude sdk not configured")

    monkeypatch.setattr(mod, "_translate_via_claude", _boom)
    result = mod.translate_to_english_sync("고양이", backend="claude")
    assert result is None


def test_translate_sync_returns_english_on_success_qwen(monkeypatch):
    """기본 Qwen3-VL 백엔드 성공 path."""
    from screen_recorder.image_gen import translator as mod

    def _fake(prompt):
        assert "고양이" in prompt
        return "A calico cat by a sunset-lit window"

    monkeypatch.setattr(mod, "_translate_via_qwen", _fake)
    result = mod.translate_to_english_sync("노을이 비치는 창가의 고양이")
    assert result == "A calico cat by a sunset-lit window"


def test_translate_sync_nllb_backend_success(monkeypatch):
    """backend='nllb' 명시 시 NLLB path (fallback 모드)."""
    from screen_recorder.image_gen import translator as mod

    def _fake(prompt):
        return "a calico cat"

    monkeypatch.setattr(mod, "_translate_via_nllb", _fake)
    result = mod.translate_to_english_sync("고양이", backend="nllb")
    assert result == "a calico cat"


def test_translate_sync_claude_backend_success(monkeypatch):
    """backend='claude' 명시 시 SDK path."""
    from screen_recorder.image_gen import translator as mod

    async def _fake(prompt, model):
        return "a calico cat"

    monkeypatch.setattr(mod, "_translate_via_claude", _fake)
    result = mod.translate_to_english_sync("고양이", backend="claude")
    assert result == "a calico cat"


def test_translate_sync_caches_result(monkeypatch):
    """두 번째 같은 prompt 호출 시 백엔드 안 거치고 캐시 반환."""
    from screen_recorder.image_gen import translator as mod

    mod.clear_translation_cache()
    call_count = {"n": 0}

    def _fake(prompt):
        call_count["n"] += 1
        return f"english v{call_count['n']}"

    monkeypatch.setattr(mod, "_translate_via_qwen", _fake)

    first = mod.translate_to_english_sync("고양이")
    assert first == "english v1"
    assert call_count["n"] == 1

    second = mod.translate_to_english_sync("고양이")
    assert second == "english v1"   # 캐시 — 같은 결과
    assert call_count["n"] == 1     # 백엔드 다시 호출 안 함

    # 다른 prompt 는 새 호출.
    third = mod.translate_to_english_sync("강아지")
    assert third == "english v2"
    assert call_count["n"] == 2


def test_clear_translation_cache_resets(monkeypatch):
    from screen_recorder.image_gen import translator as mod

    mod.clear_translation_cache()
    call_count = {"n": 0}

    def _fake(prompt):
        call_count["n"] += 1
        return f"v{call_count['n']}"

    monkeypatch.setattr(mod, "_translate_via_qwen", _fake)

    mod.translate_to_english_sync("고양이")
    assert call_count["n"] == 1
    mod.clear_translation_cache()
    mod.translate_to_english_sync("고양이")
    assert call_count["n"] == 2   # 캐시 비웠으니 다시 호출


def test_unload_nllb_safe_when_not_loaded():
    """NLLB 미로드 상태에서 unload 호출해도 에러 없음."""
    from screen_recorder.image_gen import translator as mod

    mod._nllb_pipeline = None
    mod.unload_nllb()   # no-op, 예외 없음


def test_unload_qwen_safe_when_not_loaded():
    """Qwen 미로드 상태에서 unload 호출해도 에러 없음."""
    from screen_recorder.image_gen import translator as mod

    mod._qwen_pipeline = None
    mod.unload_qwen()   # no-op, 예외 없음
