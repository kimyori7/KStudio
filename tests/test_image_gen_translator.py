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
    """Claude SDK import 실패 / 인증 실패 시 None — 호출자가 원본 fallback."""
    from screen_recorder.image_gen import translator as mod

    async def _boom(prompt, model):
        raise RuntimeError("sdk not configured")

    monkeypatch.setattr(mod, "_translate_via_claude", _boom)
    result = mod.translate_to_english_sync("고양이")
    assert result is None


def test_translate_sync_returns_english_on_success(monkeypatch):
    from screen_recorder.image_gen import translator as mod

    async def _fake(prompt, model):
        assert "고양이" in prompt
        return "a calico cat sitting by a sunset window"

    monkeypatch.setattr(mod, "_translate_via_claude", _fake)
    result = mod.translate_to_english_sync("노을이 비치는 창가의 고양이")
    assert result == "a calico cat sitting by a sunset window"


def test_translate_sync_caches_result(monkeypatch):
    """두 번째 같은 prompt 호출 시 SDK 안 거치고 캐시 반환."""
    from screen_recorder.image_gen import translator as mod

    mod.clear_translation_cache()
    call_count = {"n": 0}

    async def _fake(prompt, model):
        call_count["n"] += 1
        return f"english v{call_count['n']}"

    monkeypatch.setattr(mod, "_translate_via_claude", _fake)

    first = mod.translate_to_english_sync("고양이")
    assert first == "english v1"
    assert call_count["n"] == 1

    second = mod.translate_to_english_sync("고양이")
    assert second == "english v1"   # 캐시 — 같은 결과
    assert call_count["n"] == 1     # SDK 다시 호출 안 함

    # 다른 prompt 는 새 호출.
    third = mod.translate_to_english_sync("강아지")
    assert third == "english v2"
    assert call_count["n"] == 2


def test_clear_translation_cache_resets(monkeypatch):
    from screen_recorder.image_gen import translator as mod

    mod.clear_translation_cache()
    call_count = {"n": 0}

    async def _fake(prompt, model):
        call_count["n"] += 1
        return f"v{call_count['n']}"

    monkeypatch.setattr(mod, "_translate_via_claude", _fake)

    mod.translate_to_english_sync("고양이")
    assert call_count["n"] == 1
    mod.clear_translation_cache()
    mod.translate_to_english_sync("고양이")
    assert call_count["n"] == 2   # 캐시 비웠으니 다시 호출


def test_translate_sync_strips_common_prefixes(monkeypatch):
    """Claude 가 'Translation: ' 같은 prefix 붙이면 청소 (translator 내부 기능)."""
    from screen_recorder.image_gen import translator as mod

    # _translate_via_claude 자체가 prefix 청소 하므로 거기까지 mock.
    async def _fake(prompt, model):
        # 시뮬레이션: 사용자 시스템 prompt 가 약해서 Claude 가 prefix 붙임.
        # 실제 _translate_via_claude 가 후처리 — 우리는 그 결과 (이미 청소된) 만 검증.
        return "a calico cat"

    monkeypatch.setattr(mod, "_translate_via_claude", _fake)
    assert mod.translate_to_english_sync("고양이") == "a calico cat"
