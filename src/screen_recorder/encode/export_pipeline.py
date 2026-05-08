"""export_pipeline — Sidecar + main_duration → ffmpeg argv.

Stage 4c 의 build_combined_timeline 으로 segment 리스트를 받고, 각 segment 별
trim/setpts/scale → concat → 캡션 PNG overlay 의 filter_complex 빌드.

지원 효과: trim(사이드카 .trim), cut (insert 포함), caption.
미지원: speed/zoom/broll → NotImplementedError.
"""
from __future__ import annotations
import tempfile
from pathlib import Path
from typing import Optional

from ..effects import Sidecar
from ..effects.timeline import build_combined_timeline
from ..effects.types.caption import CaptionEffect
from ..effects.types.cut import CutEffect
from .caption_png import render_caption_png


_SUPPORTED_TYPES = {"caption", "cut"}


def default_output_path(src: Path) -> Path:
    """원본 폴더에 <src_stem>_edited.mp4. 충돌 시 _edited_2.mp4, _edited_3.mp4 ..."""
    src = Path(src)
    base = src.with_name(f"{src.stem}_edited.mp4")
    if not base.exists():
        return base
    i = 2
    while True:
        cand = src.with_name(f"{src.stem}_edited_{i}.mp4")
        if not cand.exists():
            return cand
        i += 1


def _scale_filter(scale_mode: str, w: int, h: int) -> str:
    """B 영상 scale_mode 별 ffmpeg 필터 표현식."""
    if scale_mode == "fit":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")
    if scale_mode == "fill":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    return f"scale={w}:{h}"   # stretch


def build_export_args(
    *,
    sidecar: Sidecar,
    src_path: Path | str,
    dst_path: Path | str,
    main_duration_ms: int,
    surface_w: int,
    surface_h: int,
    ffmpeg_path: Path | str,
    png_dir: Path | str | None = None,
) -> tuple[list[str], list[Path]]:
    """Sidecar → (ffmpeg argv, 임시 PNG 경로 리스트). 호출 측이 PNG 정리 책임.

    png_dir 가 None 이면 tempfile.mkdtemp().
    """
    # 0) 미지원 효과 검증
    for e in sidecar.effects:
        if e.type not in _SUPPORTED_TYPES:
            raise NotImplementedError(f"{e.type!r} effect export not implemented yet")

    cuts = [e for e in sidecar.effects if isinstance(e, CutEffect)]
    captions = [e for e in sidecar.effects if isinstance(e, CaptionEffect)]

    # 1) 결합 시간축 segment 리스트
    segments = build_combined_timeline(int(main_duration_ms), cuts)

    # 1.5) sidecar.trim 적용 — main segment 만 clip, insert 는 그대로.
    trim_in = max(0, int(sidecar.trim.in_ms))
    trim_out = int(sidecar.trim.out_ms) if sidecar.trim.out_ms > 0 else int(main_duration_ms)
    if trim_in > 0 or trim_out < main_duration_ms:
        segments = _apply_trim_to_main_segments(segments, trim_in, trim_out)

    # 2) 캡션 PNG 생성
    png_dir_path = Path(png_dir) if png_dir is not None else Path(tempfile.mkdtemp(prefix="kstudio_export_"))
    png_paths: list[Path] = []
    for cap in captions:
        png = png_dir_path / f"caption_{cap.id}.png"
        render_caption_png(cap, surface_w=surface_w, surface_h=surface_h, dst=png)
        png_paths.append(png)

    # 3) ffmpeg 입력 — A + B (cut 의 src 들, 중복 제거) + caption PNG 들
    argv: list[str] = [str(ffmpeg_path), "-y", "-loglevel", "info"]
    argv.extend(["-i", str(src_path)])

    cut_src_index: dict[str, int] = {}    # cut.id → ffmpeg input index
    next_input = 1
    for cut in cuts:
        if cut.has_insert:
            argv.extend(["-i", cut.src])
            cut_src_index[cut.id] = next_input
            next_input += 1

    png_input_index: dict[int, int] = {}   # png_paths idx → ffmpeg input index
    for i, png in enumerate(png_paths):
        argv.extend(["-i", str(png)])
        png_input_index[i] = next_input
        next_input += 1

    # 4) filter_complex 빌드
    fc_parts: list[str] = []
    seg_labels: list[tuple[str, str]] = []   # (video_label, audio_label)
    for i, seg in enumerate(segments):
        v_label = f"s{i}v"
        a_label = f"s{i}a"
        if seg.source == "main":
            in_s = seg.source_start_ms / 1000.0
            out_s = seg.source_end_ms / 1000.0
            fc_parts.append(
                f"[0:v]trim={in_s}:{out_s},setpts=PTS-STARTPTS,"
                f"{_scale_filter('stretch', surface_w, surface_h)}[{v_label}]"
            )
            fc_parts.append(
                f"[0:a]atrim={in_s}:{out_s},asetpts=PTS-STARTPTS[{a_label}]"
            )
        else:
            cut = next(c for c in cuts if c.id == seg.source_id)
            idx = cut_src_index[cut.id]
            in_s = seg.source_start_ms / 1000.0
            out_s = seg.source_end_ms / 1000.0
            fc_parts.append(
                f"[{idx}:v]trim={in_s}:{out_s},setpts=PTS-STARTPTS,"
                f"{_scale_filter(cut.scale_mode, surface_w, surface_h)}[{v_label}]"
            )
            fc_parts.append(
                f"[{idx}:a]atrim={in_s}:{out_s},asetpts=PTS-STARTPTS[{a_label}]"
            )
        seg_labels.append((v_label, a_label))

    # concat
    n = len(seg_labels)
    if n == 0:
        # cut 0 개 + main_duration 0 → 빈 효과. fallback: 전체 영상 사용.
        fc_parts.append(
            f"[0:v]{_scale_filter('stretch', surface_w, surface_h)}[outv0]"
        )
        fc_parts.append(f"[0:a]anull[outa0]")
        cur_v, cur_a = "outv0", "outa0"
    else:
        concat_inputs = "".join(f"[{v}][{a}]" for v, a in seg_labels)
        fc_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[concv][conca]")
        cur_v, cur_a = "concv", "conca"

    # 캡션 overlay (alpha fade 포함)
    for i, cap in enumerate(captions):
        png_idx = png_input_index[i]
        in_s = cap.in_ms / 1000.0
        out_s = cap.out_ms / 1000.0
        fade_in = cap.fade.in_ms / 1000.0
        fade_out = cap.fade.out_ms / 1000.0
        # alpha fade 채널 — 페이드 인 0~fade_in_ms, 페이드 아웃 (out_ms - fade_out_ms)~out_ms
        alpha_chain = (
            f"[{png_idx}:v]format=rgba,"
            f"fade=t=in:st={in_s}:d={fade_in}:alpha=1,"
            f"fade=t=out:st={out_s - fade_out}:d={fade_out}:alpha=1[cap{i}]"
        )
        fc_parts.append(alpha_chain)
        next_v = f"v{i+1}"
        fc_parts.append(
            f"[{cur_v}][cap{i}]overlay=enable='between(t\\,{in_s}\\,{out_s})'[{next_v}]"
        )
        cur_v = next_v

    fc = ";".join(fc_parts)
    argv.extend(["-filter_complex", fc])
    argv.extend(["-map", f"[{cur_v}]", "-map", f"[{cur_a}]"])
    argv.extend([
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst_path),
    ])

    return argv, png_paths


def _apply_trim_to_main_segments(
    segments: list,
    trim_in_ms: int,
    trim_out_ms: int,
) -> list:
    """main segment 의 source_start/end 를 [trim_in, trim_out] 으로 clip.
    범위 밖 main segment 는 제거. insert segment 는 그대로 통과.
    combined_start/end 는 재계산.
    """
    from ..effects.timeline import TimelineSegment
    out: list = []
    combined_cursor = 0
    for seg in segments:
        if seg.source == "insert":
            length = seg.combined_end_ms - seg.combined_start_ms
            out.append(TimelineSegment(
                combined_start_ms=combined_cursor,
                combined_end_ms=combined_cursor + length,
                source="insert",
                source_id=seg.source_id,
                source_start_ms=seg.source_start_ms,
                source_end_ms=seg.source_end_ms,
            ))
            combined_cursor += length
            continue
        # main: trim 범위와 교집합
        new_start = max(seg.source_start_ms, trim_in_ms)
        new_end = min(seg.source_end_ms, trim_out_ms)
        if new_end <= new_start:
            continue
        length = new_end - new_start
        out.append(TimelineSegment(
            combined_start_ms=combined_cursor,
            combined_end_ms=combined_cursor + length,
            source="main",
            source_id=None,
            source_start_ms=new_start,
            source_end_ms=new_end,
        ))
        combined_cursor += length
    return out
