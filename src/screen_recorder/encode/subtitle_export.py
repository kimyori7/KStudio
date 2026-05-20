"""자막 내보내기 — Whisper Transcript → TXT / SRT 직렬화.

2026-05-20 신규 (사용자 요청). 사용자 명시: "Whisper 로 새로 생성. txt 디폴트,
srt 도 고를 수 있게."

데이터 흐름:
1. AgentSettings / autoedit 와 동일한 `agent.transcript.Transcriber` 로 전사
2. 결과 `Transcript.segments` (start_ms/end_ms/text)
3. format 에 따라 segments_to_txt / segments_to_srt 직렬화
4. 사용자 지정 경로에 텍스트 파일 쓰기

cache: Transcriber 가 사이드카 옆 `_<hash>.transcript.json` 으로 자동 캐시 — 같은
영상 + 같은 모델 두 번 전사 안 함.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

from PySide6.QtCore import QObject, Signal

from ..agent.transcript import TranscriptSegment, VALID_MODEL_SIZES
from ..effects.sidecar import Sidecar

_log = logging.getLogger(__name__)


_VALID_FORMATS = ("txt", "srt")


@dataclass
class SubtitleExportSettings:
    """자막 export 설정 — 다이얼로그에서 사용자 선택값."""
    format: Literal["txt", "srt"] = "txt"   # 사용자 명시 — txt 디폴트
    model_size: str = "base"                # Whisper 모델

    def __post_init__(self) -> None:
        if self.format not in _VALID_FORMATS:
            raise ValueError(
                f"format must be one of {_VALID_FORMATS}, got {self.format!r}"
            )
        if self.model_size not in VALID_MODEL_SIZES:
            raise ValueError(
                f"model_size must be one of {VALID_MODEL_SIZES}, got {self.model_size!r}"
            )


def remap_segments_for_cuts(
    segments: Iterable[TranscriptSegment],
    keep_intervals: list[tuple[int, int]],
) -> list[TranscriptSegment]:
    """원본 시간축 segments → 편집본 시간축 segments (cut 적용).

    keep_intervals: 원본 영상에서 보존되는 [(start_ms, end_ms), ...].
    audio_export.compute_audio_keep_intervals 결과를 그대로 받음.

    알고리즘 (중심 기반):
    - 각 segment 의 중심점 (start_ms+end_ms)//2 이 어느 keep interval 에 속하는지 검색.
    - 속하면 그 keep 의 누적 offset 으로 start/end remap, segment 전체 보존.
    - 어떤 keep 에도 안 속하면 (cut 안 중심) 제거.
    - 출력 segment 의 end 는 해당 keep 의 끝점까지 clamp — 경계 걸치는 경우 cut 직전에 멈춤.

    2026-05-20 사용자 결정: SRT timecode 는 편집본 영상 기준. audio_export 와 일관.
    """
    keep_list = list(keep_intervals)
    if not keep_list:
        return []
    # 각 keep interval 이 편집본 시간축에서 시작하는 ms.
    edited_starts = [0]
    for s, e in keep_list[:-1]:
        edited_starts.append(edited_starts[-1] + (e - s))

    out: list[TranscriptSegment] = []
    for seg in segments:
        mid = (int(seg.start_ms) + int(seg.end_ms)) // 2
        for i, (k_start, k_end) in enumerate(keep_list):
            if k_start <= mid < k_end:
                offset = edited_starts[i] - k_start
                # 시작/끝 모두 keep 안으로 clamp 후 offset 적용.
                clamped_start = max(int(seg.start_ms), k_start)
                clamped_end = min(int(seg.end_ms), k_end)
                new_start = clamped_start + offset
                new_end = clamped_end + offset
                if new_end > new_start:
                    out.append(TranscriptSegment(
                        start_ms=new_start, end_ms=new_end, text=seg.text,
                    ))
                break
    return out


def segments_to_txt(segments: Iterable[TranscriptSegment]) -> str:
    """단순 텍스트 — 한 줄 한 자막. 타임코드 없음.

    Whisper 가 segment.text 앞에 종종 공백 붙임 → strip 후 합침.
    빈 텍스트는 출력 안 함.
    """
    lines = []
    for s in segments:
        t = s.text.strip()
        if t:
            lines.append(t)
    return "\n".join(lines)


def _ms_to_srt_timecode(ms: int) -> str:
    """ms → 'HH:MM:SS,mmm' (SRT 표준 — ms 구분자가 콤마)."""
    ms = max(0, int(ms))
    total_s, mil = divmod(ms, 1000)
    total_m, sec = divmod(total_s, 60)
    hour, minute = divmod(total_m, 60)
    return f"{hour:02d}:{minute:02d}:{sec:02d},{mil:03d}"


def segments_to_srt(segments: Iterable[TranscriptSegment]) -> str:
    """SubRip (.srt) 표준 — index + timecode + 본문 + 빈 줄.

    형식:
        1
        00:00:00,000 --> 00:00:02,500
        안녕하세요

        2
        00:00:02,500 --> 00:00:05,000
        반갑습니다

    인덱스는 1부터, 자막 블록 사이 빈 줄 1개.
    """
    out: list[str] = []
    for i, s in enumerate(segments, start=1):
        text = s.text.strip()
        if not text:
            continue
        out.append(str(i))
        out.append(f"{_ms_to_srt_timecode(s.start_ms)} --> {_ms_to_srt_timecode(s.end_ms)}")
        out.append(text)
        out.append("")   # 블록 구분 빈 줄
    if not out:
        return ""
    # join 은 마지막 element 뒤에 sep 안 붙임 → '오늘은\n' 으로 끝남.
    # SRT 표준은 파일 끝에 빈 줄 1개 권장. trailing \n 하나 더 붙여 '\n\n' 보장.
    return "\n".join(out) + "\n"


class SubtitleExportJob(QObject):
    """백그라운드 Whisper 전사 + 파일 쓰기.

    audio_export 의 ExportJob 과 같은 패턴 — QObject + daemon thread + Signal.
    Whisper 는 in-process Python 호출이라 ffmpeg subprocess 가 아니고, progress
    중간 보고 어려움 → indeterminate. finished/error 만 emit.
    """
    finished = Signal(object)   # dst Path
    error = Signal(str)

    def __init__(
        self,
        *,
        media_path: Path,
        settings: "SubtitleExportSettings",
        dst_path: Path,
        sidecar: Optional["Sidecar"] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._media = Path(media_path)
        self._settings = settings
        self._dst = Path(dst_path)
        self._sidecar = sidecar   # None 이면 cut 미적용 (raw 전사 — 단위 테스트용)
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="SubtitleExportJob",
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            from ..agent.transcript import get_transcriber
            t = get_transcriber()
            result = t.transcribe(
                str(self._media), model_size=self._settings.model_size,
            )
            # 사이드카가 있으면 cut 적용해 편집본 시간축으로 remap.
            # 2026-05-20 사용자 결정: SRT timecode 는 편집 결과 영상 기준 (audio_export 와 일관).
            segments = result.segments
            if self._sidecar is not None:
                from .audio_export import compute_audio_keep_intervals
                try:
                    _src, keep = compute_audio_keep_intervals(self._sidecar)
                    segments = remap_segments_for_cuts(segments, keep)
                except (ValueError, NotImplementedError) as e:
                    _log.warning("cut 적용 실패 — raw segments 사용: %s", e)
                    # multi-source 등은 raw timeline 으로 fallback (사용자에게 안내).
            if self._settings.format == "txt":
                content = segments_to_txt(segments)
            else:
                content = segments_to_srt(segments)
            # 빈 결과 — 음성 없음 / Whisper 실패.
            if not content:
                self.error.emit(
                    "전사 결과가 비어 있습니다. 영상에 음성이 없거나 모델이 텍스트를 "
                    "찾지 못했습니다."
                )
                return
            self._dst.parent.mkdir(parents=True, exist_ok=True)
            self._dst.write_text(content, encoding="utf-8")
            self.finished.emit(self._dst)
        except Exception as exc:
            _log.exception("SubtitleExportJob: transcribe/write failed")
            self.error.emit(f"자막 생성 실패: {exc}")
