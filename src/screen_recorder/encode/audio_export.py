"""음성만 내보내기 — 사이드카 cut 적용 + 형식/채널/샘플링 설정.

2026-05-20 신규 (사용자 요청). v1 범위:
- single-source video_track (대부분 케이스 — 한 영상 편집 중)
- cut 효과 적용 (구간 제거 → atrim + concat)
- 형식: MP3 (libmp3lame) / WAV (pcm_s16le)
- 채널: 1 (모노) / 2 (스테레오)
- 샘플링: 22050 / 44100 / 48000 Hz
- MP3 비트레이트: 128 / 192 / 320 kbps

v2 follow-up: speed (atempo) / multi-source video_track / b-roll audio mixing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..effects.sidecar import Sidecar


_VALID_FORMATS = ("mp3", "wav")
_VALID_CHANNELS = (1, 2)
_VALID_SAMPLE_RATES = (22050, 44100, 48000)
_VALID_MP3_BITRATES = (128, 192, 320)


@dataclass
class AudioExportSettings:
    """음성 export 설정. 다이얼로그에서 사용자가 선택한 값들."""
    format: Literal["mp3", "wav"] = "mp3"
    channels: int = 2
    sample_rate: int = 44100
    mp3_bitrate: int = 192   # MP3 일 때만 사용. WAV 면 무시.

    def __post_init__(self) -> None:
        if self.format not in _VALID_FORMATS:
            raise ValueError(
                f"format must be one of {_VALID_FORMATS}, got {self.format!r}"
            )
        if self.channels not in _VALID_CHANNELS:
            raise ValueError(
                f"channels must be 1 (모노) or 2 (스테레오), got {self.channels}"
            )
        if self.sample_rate not in _VALID_SAMPLE_RATES:
            raise ValueError(
                f"sample_rate must be one of {_VALID_SAMPLE_RATES} Hz, got {self.sample_rate}"
            )
        if self.mp3_bitrate not in _VALID_MP3_BITRATES:
            raise ValueError(
                f"mp3_bitrate must be one of {_VALID_MP3_BITRATES} kbps, got {self.mp3_bitrate}"
            )


def compute_audio_keep_intervals(sidecar: Sidecar) -> tuple[str, list[tuple[int, int]]]:
    """사이드카 → (src_path, keep_intervals).

    keep_intervals: src 시간 기준 [(start_ms, end_ms), ...] — cut 효과 제외한 보존 구간.

    v1 가정: video_track 안 모든 segment 의 src 가 동일 (single-source).
    multi-source 면 NotImplementedError — 사용자가 영상 export 결과에서 음성 추출 권장.

    raises:
        ValueError: video_track 비어 있음.
        NotImplementedError: 여러 src 가 섞여 있음.
    """
    segments = sidecar.video_track
    if not segments:
        raise ValueError("video_track 이 비어 있어 음성 추출 불가")

    src = segments[0].src
    if any(s.src != src for s in segments):
        raise NotImplementedError(
            "v1: 여러 영상이 섞인 트랙 (다중 src) 의 음성 export 는 아직 미지원. "
            "먼저 영상 내보내기 후 그 결과 파일에서 음성을 추출하세요."
        )

    # 첫 segment 의 src_in 부터 마지막 segment 의 src_out 까지를 전체 범위로.
    # src_out_ms == 0 은 '끝까지' 약속 — segment.src_duration_ms 로 대체.
    start_ms = int(segments[0].src_in_ms)
    last = segments[-1]
    end_ms = int(last.src_out_ms) if last.src_out_ms > 0 else int(last.src_duration_ms)
    if end_ms <= start_ms:
        raise ValueError(
            f"유효한 음성 구간 없음 (start={start_ms}, end={end_ms})"
        )

    # 사이드카 cut 효과 — combined timeline ms 기준. single-source 면 combined ms ≈ src ms.
    # splice (in==out) 는 0폭이라 무시.
    # 2026-05-20: active_effects() — 전체/개별 토글 OFF 인 cut 은 음성에도 적용 안 함.
    cuts = sorted(
        ((int(e.in_ms), int(e.out_ms)) for e in sidecar.active_effects()
         if e.type == "cut" and e.out_ms > e.in_ms),
        key=lambda x: x[0],
    )

    keep = _subtract_intervals(start_ms, end_ms, cuts)
    return src, keep


def _subtract_intervals(start: int, end: int,
                          cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """[start, end] 에서 cuts 의 각 구간을 빼고 남는 keep 리스트."""
    keep: list[tuple[int, int]] = [(start, end)]
    for c_start, c_end in cuts:
        new_keep: list[tuple[int, int]] = []
        for k_start, k_end in keep:
            # 안 겹치면 그대로.
            if c_end <= k_start or c_start >= k_end:
                new_keep.append((k_start, k_end))
                continue
            # 앞쪽 남는 부분 (cut 시작이 keep 시작보다 뒤면).
            if c_start > k_start:
                new_keep.append((k_start, c_start))
            # 뒤쪽 남는 부분 (cut 끝이 keep 끝보다 앞이면).
            if c_end < k_end:
                new_keep.append((c_end, k_end))
        keep = new_keep
    return keep


def build_audio_export_args(
    *,
    src_path: str,
    keep_intervals: list[tuple[int, int]],
    settings: AudioExportSettings,
    dst_path: str,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """ffmpeg argv 빌더.

    cut 없을 때 (keep_intervals 1개) — `-vn -c:a ... -ac ... -ar ...` 단순 변환.
    cut 있을 때 — filter_complex 안에서 atrim + asetpts + concat.
    """
    if not keep_intervals:
        raise ValueError("keep_intervals 가 비어 있음 — 모든 구간이 cut 처리됨")

    cmd: list[str] = [str(ffmpeg_path), "-y", "-i", str(src_path)]

    if len(keep_intervals) == 1:
        # 단순 변환 — atrim 불필요.
        s, e = keep_intervals[0]
        # 전체 범위가 아니면 atrim 으로 잘라야 함 (예: trim 만 있고 cut 은 없는 경우).
        # 그래도 filter_complex 보다 -ss/-to 가 더 효율.
        if s > 0 or e > 0:
            cmd.extend(["-ss", f"{s / 1000:.3f}", "-to", f"{e / 1000:.3f}"])
        cmd.append("-vn")
    else:
        parts: list[str] = []
        for i, (s, e) in enumerate(keep_intervals):
            parts.append(
                f"[0:a]atrim=start={s / 1000:.3f}:end={e / 1000:.3f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
        labels = "".join(f"[a{i}]" for i in range(len(keep_intervals)))
        parts.append(f"{labels}concat=n={len(keep_intervals)}:v=0:a=1[aout]")
        filt = ";".join(parts)
        cmd.extend(["-filter_complex", filt, "-map", "[aout]"])

    cmd.extend(["-ac", str(settings.channels), "-ar", str(settings.sample_rate)])
    if settings.format == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", f"{settings.mp3_bitrate}k"])
    else:   # wav
        cmd.extend(["-c:a", "pcm_s16le"])

    cmd.append(str(dst_path))
    return cmd
