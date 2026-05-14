"""자동편집 분석 결과 디스크 캐시.

키: {source_hash}_{schema_v}_{whisper_model}_{analyzer_v_concat}
파일: <sidecar_dir>/<key>.autoedit.json
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

from .result import AutoEditResult

CACHE_SCHEMA_VERSION = "v1"


def build_key(
    *,
    source_hash: str,
    whisper_model: str,
    analyzer_versions: dict[str, str],
) -> str:
    av = "_".join(f"{k}{v}" for k, v in sorted(analyzer_versions.items()))
    return f"{source_hash}_{CACHE_SCHEMA_VERSION}_{whisper_model}_{av}"


def _path_for(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.autoedit.json"


def save(cache_dir: Path, key: str, result: AutoEditResult) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = _path_for(cache_dir, key)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def load(cache_dir: Path, key: str) -> AutoEditResult | None:
    p = _path_for(cache_dir, key)
    if not p.exists():
        return None
    try:
        return AutoEditResult.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logging.warning("autoedit cache 손상 — 삭제 후 재분석: %s (%s)", p, e)
        try:
            p.unlink()
        except OSError:
            pass
        return None
