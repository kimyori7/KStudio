"""HF 캐시 검사 — 모델 다운로드 사전 판정."""
from __future__ import annotations

import logging


_log = logging.getLogger(__name__)


def is_model_cached(repo_id: str) -> bool:
    """HuggingFace 캐시에 모델이 이미 있는지.

    HF Hub 가 scan_cache_dir() 으로 캐시된 repo list 반환. 정확 매칭 — `repo_id` 가
    `repo.repo_id` 와 일치. huggingface_hub 미설치 시 False (다운로드 필요로 판단).
    """
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        for repo in info.repos:
            if repo.repo_id == repo_id:
                return True
    except ImportError:
        _log.debug("is_model_cached: huggingface_hub 미설치 → False")
    except Exception:
        _log.exception("is_model_cached: scan_cache_dir 실패 → False")
    return False
