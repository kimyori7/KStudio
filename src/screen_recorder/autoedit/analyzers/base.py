"""Analyzer 추상 — 모든 analyzer 가 따라야 할 인터페이스.

메인테이너 가이드: 새 알고리즘 추가하려면 이 클래스를 상속해
- name (라벨)
- version (수정 시 +1 → 캐시 자동 무효)
- analyze(media_path) → raw 결과 dict (AutoEditResult 필드 일부)
세 가지만 구현하면 된다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable


class Analyzer(ABC):
    """결정론 분석기 추상."""

    name: str = ""
    version: str = "v1"

    @abstractmethod
    def analyze(
        self,
        media_path: Path,
        *,
        progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """media 분석 → AutoEditResult 의 필드 값(들) 을 dict 로 반환."""
        ...


class AnalyzerCancelled(Exception):
    """사용자가 취소한 경우 raise — Worker 가 catch 해 partial 폐기."""
