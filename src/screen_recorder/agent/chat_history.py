"""ChatPanel 대화 기록 영속화.

스키마 v1:
```
{
  "version": 1,
  "messages": [
    {"role": "user", "text": "..."},
    {"role": "assistant", "text": "..."},
    {"role": "tool_use", "text": "🔧 ..."},
    ...
  ]
}
```

저장 제외:
- 이미지 (image_bytes) — 토큰/디스크 비용 큼.
- proposals_preview interactive 카드 — 이미 적용된 상태로만 의미 있음.
- thinking — 노이즈, 다음 세션엔 무관.

저장 위치: `<settings_dir>/chat_history.json` (settings.json 옆).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


HISTORY_SCHEMA_VERSION = 1
# 너무 길어지면 잘라냄 — 끝(최신) 우선 보존.
MAX_MESSAGES = 500

# 영속화 대상 role — 나머지는 skip.
PERSISTABLE_ROLES = ("user", "assistant", "system", "tool_use", "tool_result", "error")


def save_history(path: Path, messages: list[tuple[str, str]]) -> None:
    """messages: [(role, text), ...]. atomic write."""
    path = Path(path)
    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]
    payload = {
        "version": HISTORY_SCHEMA_VERSION,
        "messages": [{"role": r, "text": t} for r, t in messages],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_history(path: Path) -> list[tuple[str, str]]:
    """디스크에서 (role, text) 리스트 복원. 없거나 손상 시 빈 리스트."""
    try:
        if not Path(path).exists():
            return []
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if int(data.get("version", 0)) != HISTORY_SCHEMA_VERSION:
            _log.warning("chat history version mismatch: %s", path)
            return []
        out: list[tuple[str, str]] = []
        for m in data.get("messages", []):
            role = str(m.get("role", ""))
            text = str(m.get("text", ""))
            if role in PERSISTABLE_ROLES:
                out.append((role, text))
        return out
    except Exception:
        _log.exception("load_history failed: %s", path)
        return []


def default_history_path() -> Path:
    """settings.json 과 같은 폴더 — settings_path() 결과의 parent."""
    from ..core.settings import settings_path
    return settings_path().parent / "chat_history.json"
