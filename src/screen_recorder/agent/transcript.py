"""faster-whisper 자막 추출 + 캐시.

설계 결정 (2026-05-13):
- **모델 캐시**: faster-whisper 기본 (`~/.cache/huggingface/hub/`) — 첫 사용 시 자동
  다운로드. 별도 download_whisper_model 도구로 명시적 사전 다운로드 가능.
- **전사 캐시**: 사이드카 옆에 `<basename>_<hash>.transcript.json`. 같은 영상 두 번
  전사 안 함. 사이드카 폴더와 동일 위치 (`SidecarStore.root`).
- **모델 크기**: AgentSettings.whisper_model_size 로 영속화 — tiny/base/small/medium.
  사용자가 환경설정에서 변경.
- **동기 전사**: 1시간 영상 base 모델 기준 ~1~2분. worker(asyncio) 스레드 차단 OK
  — UI 는 별도 thread 라 응답. 백그라운드 잡 패턴은 후속.

스키마 v1:
```
{
  "version": 1,
  "source_hash": "...",
  "model_size": "base",
  "language": "ko",
  "duration_ms": 60000,
  "segments": [
    {"start_ms": 0, "end_ms": 3500, "text": "안녕하세요 ..."},
    ...
  ]
}
```
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..effects.sidecar_store import _safe_filename, compute_video_hash

_log = logging.getLogger(__name__)


TRANSCRIPT_EXT = ".transcript.json"
TRANSCRIPT_SCHEMA_VERSION = 1
VALID_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")

# 사용자에게 안내용 — 대략 모델 크기. 정확한 값은 첫 다운로드 후 HF 캐시에 따라 변동.
WHISPER_SIZE_MB = {
    "tiny": 39,
    "base": 74,
    "small": 244,
    "medium": 769,
    "large-v3": 1550,
}


@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start_ms": self.start_ms, "end_ms": self.end_ms, "text": self.text}

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptSegment":
        return cls(
            start_ms=int(d.get("start_ms", 0)),
            end_ms=int(d.get("end_ms", 0)),
            text=str(d.get("text", "")),
        )


@dataclass
class Transcript:
    """전사 결과 — 디스크 영속화 대상."""
    source_hash: str
    model_size: str
    language: str
    duration_ms: int
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TRANSCRIPT_SCHEMA_VERSION,
            "source_hash": self.source_hash,
            "model_size": self.model_size,
            "language": self.language,
            "duration_ms": self.duration_ms,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(
            source_hash=str(d.get("source_hash", "")),
            model_size=str(d.get("model_size", "base")),
            language=str(d.get("language", "ko")),
            duration_ms=int(d.get("duration_ms", 0)),
            segments=[TranscriptSegment.from_dict(s) for s in d.get("segments", [])],
        )

    def segments_in_range(self, start_ms: int, end_ms: int) -> list[TranscriptSegment]:
        return [s for s in self.segments if not (s.end_ms < start_ms or s.start_ms > end_ms)]


def transcript_path_for(
    sidecar_dir: Path, video_path: Path, source_hash: str
) -> Path:
    """전사 캐시 경로 — `<basename>_<hash>.transcript.json` (사이드카와 같은 폴더)."""
    basename = _safe_filename(Path(video_path).stem)
    return Path(sidecar_dir) / f"{basename}_{source_hash}{TRANSCRIPT_EXT}"


def load_transcript(path: Path) -> Optional[Transcript]:
    """캐시 파일 로드. 없거나 손상 시 None."""
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("version", 0)) != TRANSCRIPT_SCHEMA_VERSION:
            _log.warning("transcript version mismatch: %s", path)
            return None
        return Transcript.from_dict(data)
    except Exception:
        _log.exception("load_transcript failed: %s", path)
        return None


def save_transcript(path: Path, t: Transcript) -> None:
    """atomic write — tmp 후 rename. 중간 종료에도 기존 파일 보존."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(t.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Transcriber:
    """faster-whisper 래퍼 — 모델 lazy load + 캐시.

    여러 transcribe 호출이 모델을 재사용 (singleton). 모델 크기 변경 시 새로 로드.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._model_size: Optional[str] = None
        self._device: str = "cpu"             # GPU 지원은 별도 결정 거리.
        self._compute_type: str = "int8"      # CPU int8 양자화 — 빠르고 정확도 양호.

    def _ensure_model(self, model_size: str) -> Any:
        if model_size not in VALID_MODEL_SIZES:
            raise ValueError(f"invalid whisper model size: {model_size}. "
                              f"valid: {', '.join(VALID_MODEL_SIZES)}")
        if self._model is None or self._model_size != model_size:
            from faster_whisper import WhisperModel
            _log.info("Transcriber: loading whisper model %r (first call may download)", model_size)
            self._model = WhisperModel(
                model_size, device=self._device, compute_type=self._compute_type,
            )
            self._model_size = model_size
        return self._model

    def transcribe(
        self,
        video_path: str,
        model_size: str = "base",
        language: Optional[str] = "ko",
    ) -> Transcript:
        """전사 실행. 동기 차단 — 1시간 영상 base 기준 ~1~2분.

        language=None 이면 자동 감지. default 'ko' 는 사용자 영상이 한국어 위주일
        가능성이 높아 정확도를 위해 명시.
        """
        model = self._ensure_model(model_size)
        segments_iter, info = model.transcribe(
            video_path,
            language=language,
            vad_filter=True,          # 침묵 구간 자동 스킵 — 토큰 절약.
            beam_size=5,              # 정확도/속도 trade-off — 5 가 기본 권장.
        )
        segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            segments.append(TranscriptSegment(
                start_ms=int(round(seg.start * 1000)),
                end_ms=int(round(seg.end * 1000)),
                text=seg.text.strip(),
            ))
        duration_ms = int(round(info.duration * 1000)) if info.duration else 0
        detected_lang = info.language or language or "unknown"
        return Transcript(
            source_hash="",       # 호출자가 채움.
            model_size=model_size,
            language=detected_lang,
            duration_ms=duration_ms,
            segments=segments,
        )


# 프로세스 단일 Transcriber — 모델 한 번만 로드.
_singleton: Optional[Transcriber] = None


def get_transcriber() -> Transcriber:
    global _singleton
    if _singleton is None:
        _singleton = Transcriber()
    return _singleton


def is_model_cached(model_size: str) -> bool:
    """HuggingFace 캐시에 모델이 이미 있는지. 다운로드 필요 사전 판정용.

    경로: `<HF_HUB_CACHE>/models--Systran--faster-whisper-<size>/`. 정확한 매칭 어렵
    지만 fuzzy 검사로 충분 — faster-whisper 가 어차피 가용성 자체 검증.
    """
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        target = f"faster-whisper-{model_size}"
        for repo in info.repos:
            if target in repo.repo_id.lower():
                return True
    except Exception:
        pass
    return False
