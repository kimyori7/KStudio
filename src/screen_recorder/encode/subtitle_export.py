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

    2026-05-20: progress 시그널 확장 (사용자 요청).
    Phase 흐름: "downloading" (필요 시) → "loading" → "transcribing" → finished.
    """
    # 다운로드 phase — received_bytes, total_bytes. total=0 이면 알 수 없음.
    download_progress = Signal(int, int)
    # 전사 phase — 0~100 % (영상 길이 대비 처리된 segment 끝점).
    transcribe_progress = Signal(int)
    # 새 segment 도착 — start_ms, end_ms, text. UI 가 실시간으로 자막 누적 표시.
    segment_ready = Signal(int, int, str)
    # 현재 phase 라벨 — "downloading" / "loading" / "transcribing" / "writing".
    phase_changed = Signal(str)
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
        self._watcher_stop: Optional[threading.Event] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="SubtitleExportJob",
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            from ..agent.transcript import get_transcriber, WHISPER_SIZE_MB
            t = get_transcriber()

            # ---- Phase 1: 다운로드 (이미 캐시되어 있으면 빠르게 통과) ----
            cache_dir = t.cache_dir_for(self._settings.model_size)
            already_cached = bool(cache_dir and cache_dir.exists())
            expected_mb = WHISPER_SIZE_MB.get(self._settings.model_size, 0)
            expected_bytes = expected_mb * 1024 * 1024

            if not already_cached and cache_dir is not None and expected_bytes > 0:
                self.phase_changed.emit("downloading")
                self._start_download_watcher(cache_dir, expected_bytes)

            # ---- Phase 2: 모델 로딩 (메모리 적재) — indeterminate ----
            # _ensure_model 안에서 다운로드도 발생할 수 있어 watcher 가 그동안 emit.
            self.phase_changed.emit("loading")
            # _ensure_model 직접 노출 안 되니 transcribe 안에서 일어남. 명시 트리거 안 함.

            # ---- Phase 3: 전사 ----
            # transcribe 호출 시점에 _ensure_model + 다운로드까지 일어남 (lazy).
            # 따라서 watcher 는 transcribe 직전에 켜고, on_segment 첫 호출 시점에 끄기.
            self.phase_changed.emit("transcribing")
            transcribe_started = threading.Event()

            def _on_segment(seg, duration_s: float) -> None:
                # 첫 segment 도착 = 다운로드 + 모델 로딩 끝 → watcher 정리.
                if not transcribe_started.is_set():
                    transcribe_started.set()
                    self._stop_download_watcher()
                self.segment_ready.emit(int(seg.start_ms), int(seg.end_ms), seg.text)
                if duration_s > 0:
                    pct = int(min(100.0, (seg.end_ms / 1000.0) / duration_s * 100.0))
                    self.transcribe_progress.emit(pct)

            try:
                result = t.transcribe(
                    str(self._media), model_size=self._settings.model_size,
                    on_segment=_on_segment,
                )
            finally:
                self._stop_download_watcher()

            # ---- Phase 4: cut remap + 파일 쓰기 ----
            self.phase_changed.emit("writing")
            segments = result.segments
            if self._sidecar is not None:
                from .audio_export import compute_audio_keep_intervals
                try:
                    _src, keep = compute_audio_keep_intervals(self._sidecar)
                    segments = remap_segments_for_cuts(segments, keep)
                except (ValueError, NotImplementedError) as e:
                    _log.warning("cut 적용 실패 — raw segments 사용: %s", e)
            if self._settings.format == "txt":
                content = segments_to_txt(segments)
            else:
                content = segments_to_srt(segments)
            if not content:
                self.error.emit(
                    "전사 결과가 비어 있습니다. 영상에 음성이 없거나 모델이 텍스트를 "
                    "찾지 못했습니다."
                )
                return
            self._dst.parent.mkdir(parents=True, exist_ok=True)
            self._dst.write_text(content, encoding="utf-8")
            self.transcribe_progress.emit(100)
            self.finished.emit(self._dst)
        except Exception as exc:
            _log.exception("SubtitleExportJob: transcribe/write failed")
            self.error.emit(f"자막 생성 실패: {exc}")
        finally:
            self._stop_download_watcher()

    # ---- 다운로드 progress watcher (HF 캐시 디렉토리 polling) ----
    def _start_download_watcher(self, cache_dir: Path, expected_bytes: int) -> None:
        """별도 thread — 0.5초마다 cache_dir 크기 polling → download_progress emit.

        HF Hub 가 tqdm 으로 직접 콜백 줄 방법이 라이브러리 버전마다 불안정. 디스크
        polling 은 정확도 약간 떨어지나 안정적 — 사용자 만족 OK.
        """
        stop = threading.Event()
        self._watcher_stop = stop

        def _watch():
            size_before = _dir_size(cache_dir)
            while not stop.wait(0.5):
                current = _dir_size(cache_dir) - size_before
                if current < 0:
                    current = 0
                self.download_progress.emit(int(current), int(expected_bytes))

        threading.Thread(
            target=_watch, daemon=True, name="WhisperDownloadWatcher",
        ).start()

    def _stop_download_watcher(self) -> None:
        if self._watcher_stop is not None:
            self._watcher_stop.set()
            self._watcher_stop = None


def _dir_size(d: Path) -> int:
    """디렉토리 안 모든 파일 크기 합 — 다운로드 progress 추정용."""
    total = 0
    if not d.exists():
        return 0
    try:
        for f in d.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total
