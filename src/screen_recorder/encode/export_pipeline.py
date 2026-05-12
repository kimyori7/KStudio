"""export_pipeline — Sidecar + main_duration → ffmpeg argv.

Stage 4c 의 build_combined_timeline 으로 segment 리스트를 받고, 각 segment 별
trim/setpts/scale → concat → 캡션 PNG overlay → broll PiP overlay 의
filter_complex 빌드.

지원 효과: trim(사이드카 .trim), cut (insert 포함), caption, speed (Stage 5),
        zoom (Stage 6, 정적), broll PiP (Stage 7).
미지원 조합:
  - speed + cut(범위/insert) → NotImplementedError (v2 follow-up).
  - zoom + cut(범위/insert) → NotImplementedError (v2 follow-up).
  - zoom + speed → NotImplementedError (v2 follow-up).
  - broll(fullscreen placement) → NotImplementedError (v2; cut+insert 사용 권장).
  - broll + cut(범위/insert) / + speed / + zoom → NotImplementedError (v2 follow-up).
  - broll audio_mix != 'original_only' → NotImplementedError (v2 audio mixing).
"""
from __future__ import annotations
import tempfile
from pathlib import Path
from typing import Optional

from ..effects import Sidecar
from ..effects.timeline import TimelineSegment, build_combined_timeline
from ..effects.types.broll import BrollEffect
from ..effects.types.caption import CaptionEffect
from ..effects.types.cut import CutEffect
from ..effects.types.speed import SpeedEffect
from ..effects.types.zoom import ZoomEffect
from .caption_png import render_caption_png


_SUPPORTED_TYPES = {"caption", "cut", "speed", "zoom", "broll"}


def _atempo_chain(rate: float) -> str:
    """ffmpeg atempo 는 [0.5, 2.0] 만 지원 — 범위 밖 rate 는 atempo 체인으로 표현.

    예: 4.0 → 'atempo=2.0,atempo=2.0', 0.25 → 'atempo=0.5,atempo=0.5', 3.0 → 'atempo=2.0,atempo=1.5'.
    rate <= 0 또는 rate == 1.0 은 식별자.
    """
    if rate <= 0:
        raise ValueError(f"rate must be > 0, got {rate}")

    def _fmt(v: float) -> str:
        # 정수면 'N.0' (atempo 인자는 보통 소수점 표기). e.g. 2.0 → '2.0'.
        # 비정수는 :g 로 trailing 0 제거. e.g. 1.5 → '1.5', 0.5 → '0.5'.
        if abs(v - round(v)) < 1e-9:
            return f"{round(v):d}.0"
        return f"{v:g}"

    parts: list[str] = []
    r = float(rate)
    # 빠르게 (rate>1): 2.0 씩 나눠 가다가 마지막 잔량을 한 번 더.
    while r > 2.0 + 1e-9:
        parts.append("atempo=2.0")
        r /= 2.0
    # 느리게 (rate<1): 0.5 씩 나눠 가다가 마지막 잔량.
    while r < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append(f"atempo={_fmt(r)}")
    return ",".join(parts)


def _speed_overlapping_segment(speeds: list[SpeedEffect], seg: TimelineSegment) -> Optional[SpeedEffect]:
    """seg 와 시간상 겹치는 SpeedEffect 를 반환 (없으면 None).

    seg 의 시간축은 main 영상의 source ms 기준 (cuts 가 없는 경우 seg 의
    source_start_ms / source_end_ms 가 main 영상의 위치와 일치). v1 에서는 cut+speed
    조합을 차단하므로 seg.source 는 항상 'main' 이고 source_*_ms == combined_*_ms.

    겹침 분류:
    - 완전 포함: speed.in_ms <= seg.start AND speed.out_ms >= seg.end → 매칭
    - 완전 밖: speed.out_ms <= seg.start OR speed.in_ms >= seg.end → 미매칭
    - 부분 겹침: NotImplementedError (v1 에서 명시적으로 차단)
    """
    seg_start = seg.source_start_ms
    seg_end = seg.source_end_ms
    for sp in speeds:
        if sp.out_ms <= seg_start or sp.in_ms >= seg_end:
            continue   # 완전 밖
        if sp.in_ms <= seg_start and sp.out_ms >= seg_end:
            return sp   # 완전 포함
        # 부분 겹침
        raise NotImplementedError(
            f"SpeedEffect partial overlap with segment "
            f"(speed: {sp.in_ms}-{sp.out_ms}, segment: {seg_start}-{seg_end}); "
            f"v1 requires speed regions to fully contain or sit outside each segment"
        )
    return None


def _zoom_overlapping_segment(zooms: list[ZoomEffect], seg: TimelineSegment) -> Optional[ZoomEffect]:
    """seg 와 시간상 겹치는 ZoomEffect 를 반환 (없으면 None).

    겹침 분류 — _speed_overlapping_segment 와 동일 규칙:
    - 완전 포함: zoom.in_ms <= seg.start AND zoom.out_ms >= seg.end → 매칭
    - 완전 밖: zoom.out_ms <= seg.start OR zoom.in_ms >= seg.end → 미매칭
    - 부분 겹침: NotImplementedError (v1 에서 명시적으로 차단)

    v1 에서는 zoom + cut/speed 조합을 차단하므로 seg.source 는 항상 'main' 이다.
    """
    seg_start = seg.source_start_ms
    seg_end = seg.source_end_ms
    for z in zooms:
        if z.out_ms <= seg_start or z.in_ms >= seg_end:
            continue   # 완전 밖
        if z.in_ms <= seg_start and z.out_ms >= seg_end:
            return z   # 완전 포함
        # 부분 겹침
        raise NotImplementedError(
            f"ZoomEffect partial overlap with segment "
            f"(zoom: {z.in_ms}-{z.out_ms}, segment: {seg_start}-{seg_end}); "
            f"v1 requires zoom regions to fully contain or sit outside each segment"
        )
    return None


def _zoom_crop_scale_filter(z: ZoomEffect, surface_w: int, surface_h: int) -> str:
    """ZoomEffect → crop+scale ffmpeg 필터 문자열.

    중심 (cx*w, cy*h) 로부터 (w/scale × h/scale) 영역을 잘라낸 뒤 원본 surface 크기로
    다시 scale. v1: start.scale 만 사용 (정적 줌).

    예: cx=0.5, cy=0.5, scale=2.0, surface 1920×1080 → crop=960:540:480:270,scale=1920:1080.
    """
    scale = max(0.1, float(z.start.scale))
    cx = float(z.start.cx)
    cy = float(z.start.cy)
    crop_w = surface_w / scale
    crop_h = surface_h / scale
    crop_x = cx * surface_w - crop_w / 2.0
    crop_y = cy * surface_h - crop_h / 2.0
    # flags=lanczos — 줌 후 upscale 시 기본 bicubic 보다 sharp. Phase 19.5 사용자
    # 요청 ("줌 화질 떨어짐") 대응.
    return (
        f"crop={crop_w:.0f}:{crop_h:.0f}:{crop_x:.0f}:{crop_y:.0f},"
        f"scale={surface_w}:{surface_h}:flags=lanczos"
    )


_BROLL_MARGIN_PX = 8   # PiP 사각형의 화면 가장자리 여백 (preview_overlay 와 일관)


def _broll_pip_xy(corner: str, surface_w: int, surface_h: int,
                   pip_w: int, pip_h: int,
                   pos_x: float | None = None,
                   pos_y: float | None = None) -> tuple[int, int]:
    """PiP 좌표 (ffmpeg overlay x, y).

    pos_x, pos_y 가 둘 다 set 이면 자유 위치 — 정규화 좌표를 픽셀로 변환.
    아니면 corner + 8px 여백 (preview_overlay 와 같은 규칙).
    """
    if pos_x is not None and pos_y is not None:
        return int(round(float(pos_x) * surface_w)), int(round(float(pos_y) * surface_h))
    m = _BROLL_MARGIN_PX
    if corner == "top-left":
        return m, m
    if corner == "top-right":
        return surface_w - pip_w - m, m
    if corner == "bottom-left":
        return m, surface_h - pip_h - m
    return surface_w - pip_w - m, surface_h - pip_h - m   # bottom-right (기본)


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

    libx264 + yuv420p 는 width/height 가 짝수여야 함. 홀수면 -22 EINVAL 로 인코딩
    실패 ("width not divisible by 2"). 사용자 화면 녹화 (예: 1903×1005) 가 둘 다
    홀수인 경우가 흔해서 입구에서 짝수로 floor 한다.
    """
    surface_w = int(surface_w) & ~1   # 짝수로 floor (1903 → 1902)
    surface_h = int(surface_h) & ~1
    # 다중 segment 트랙 export. 같은 src 든 다른 src 든 자동 처리.
    # image segment 만 v2 보류 — 정지 이미지를 영상 stream 으로 합성하는 별도 그래프 필요.
    if len(sidecar.video_track) > 1:
        if any(seg.media_kind == "image" for seg in sidecar.video_track):
            raise NotImplementedError(
                "image segment 가 포함된 트랙 export 는 v2 — 영상 segment 만 지원."
            )

    # 0) 미지원 효과 검증
    for e in sidecar.effects:
        if e.type not in _SUPPORTED_TYPES:
            raise NotImplementedError(f"{e.type!r} effect export not implemented yet")

    cuts = [e for e in sidecar.effects if isinstance(e, CutEffect)]
    captions = [e for e in sidecar.effects if isinstance(e, CaptionEffect)]
    speeds = [e for e in sidecar.effects if isinstance(e, SpeedEffect)]
    zooms = [e for e in sidecar.effects if isinstance(e, ZoomEffect)]
    brolls = [e for e in sidecar.effects if isinstance(e, BrollEffect)]

    # 0.7) broll v1 제약 — placement / audio_mix / 다른 효과와의 결합 검증.
    if brolls:
        for b in brolls:
            if b.placement != "pip":
                raise NotImplementedError(
                    "fullscreen broll export is v2 — use cut+insert instead "
                    f"(broll placement={b.placement!r})"
                )
            if b.pip is None:
                raise NotImplementedError(
                    "broll placement='pip' requires PipConfig (broll.pip is None)"
                )
            if b.audio_mix != "original_only":
                raise NotImplementedError(
                    f"broll audio_mix={b.audio_mix!r} export is v2 follow-up; "
                    "v1 supports only 'original_only'"
                )
        # broll + range cut / insert 결합은 v2.
        for c in cuts:
            if c.out_ms > c.in_ms or c.has_insert:
                raise NotImplementedError(
                    "broll+cut combined export is v2 follow-up "
                    f"(cut: {c.in_ms}-{c.out_ms}, has_insert={c.has_insert})"
                )
        if speeds:
            raise NotImplementedError("broll+speed combined export is v2 follow-up")
        if zooms:
            raise NotImplementedError("broll+zoom combined export is v2 follow-up")

    # 0.5) speed + cut(non-trivial) 조합은 v2 — 명시적 차단.
    # 기준: range cut (out > in) 또는 insert 가 있는 splice. 단순 splice (in==out, no src) 는
    # 시간축에 영향이 없어 통과 가능.
    if speeds:
        for c in cuts:
            if c.out_ms > c.in_ms or c.has_insert:
                raise NotImplementedError(
                    "speed+cut combined export is v2 follow-up "
                    f"(cut: {c.in_ms}-{c.out_ms}, has_insert={c.has_insert})"
                )

    # 0.6) zoom + cut(non-trivial) 또는 zoom + speed 조합은 v2 — 명시적 차단.
    # zoom 은 segment 마다 crop+scale 필터를 추가하는 방식이라 cut/speed 와의 결합은
    # filter_complex 그래프가 복잡해져 v2 follow-up.
    if zooms:
        for c in cuts:
            if c.out_ms > c.in_ms or c.has_insert:
                raise NotImplementedError(
                    "zoom+cut combined export is v2 follow-up "
                    f"(cut: {c.in_ms}-{c.out_ms}, has_insert={c.has_insert})"
                )
        if speeds:
            raise NotImplementedError(
                "zoom+speed combined export is v2 follow-up"
            )

    # 1) 결합 시간축 segment 리스트
    # 다중 segment 트랙: video_track 의 각 segment 를 TimelineSegment 로 직접 변환.
    # 모든 segment 의 src 가 src_path 와 같으면 source="main" 으로 간단 처리. 다른
    # src 가 섞이면 source="insert" + source_id=src 로 두고 _build_argv 가 별도 input 추가.
    track_extra_srcs: list[str] = []   # src_path 가 아닌 segment 들의 unique src
    if len(sidecar.video_track) > 1:
        segments, track_extra_srcs = _build_timeline_from_video_track(
            sidecar.video_track, str(src_path),
        )
    else:
        segments = build_combined_timeline(int(main_duration_ms), cuts)

    # 1.5) sidecar.trim 적용 — main segment 만 clip, insert 는 그대로.
    # 다중 segment 트랙은 각 segment 의 src_in/out 이 이미 자르기 표현이라 sidecar.trim 무시.
    trim_in = max(0, int(sidecar.trim.in_ms))
    trim_out = int(sidecar.trim.out_ms) if sidecar.trim.out_ms > 0 else int(main_duration_ms)
    if len(sidecar.video_track) <= 1 and (trim_in > 0 or trim_out < main_duration_ms):
        segments = _apply_trim_to_main_segments(segments, trim_in, trim_out)

    # 1.6) speed/zoom 효과 경계점에서 main segment 자동 분할.
    # 사용자가 효과 구간을 segment 보다 짧게 잡으면 partial overlap → 이전엔
    # NotImplementedError. 효과의 in_ms / out_ms 가 segment 안에 떨어지면 그
    # 지점에서 segment 를 쪼개 각 sub-segment 가 효과에 완전 포함되거나 완전
    # 밖에 있도록 만든다. 이후 _speed/zoom_overlapping_segment 가 정상 동작.
    if speeds or zooms:
        segments = _split_main_segments_at_effect_boundaries(segments, speeds, zooms)

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

    # 다중 src 트랙 segment 의 추가 입력. source_id=src 로 lookup.
    track_src_index: dict[str, int] = {}
    for src in track_extra_srcs:
        argv.extend(["-i", src])
        track_src_index[src] = next_input
        next_input += 1

    png_input_index: dict[int, int] = {}   # png_paths idx → ffmpeg input index
    for i, png in enumerate(png_paths):
        argv.extend(["-i", str(png)])
        png_input_index[i] = next_input
        next_input += 1

    # broll PiP 입력 — 캡션 PNG 다음 차례. 각 broll 마다 -i 추가.
    broll_input_index: dict[int, int] = {}   # brolls idx → ffmpeg input index
    for i, broll in enumerate(brolls):
        argv.extend(["-i", broll.src])
        broll_input_index[i] = next_input
        next_input += 1

    # 4) filter_complex 빌드
    fc_parts: list[str] = []
    seg_labels: list[tuple[str, str]] = []   # (video_label, audio_label)
    for i, seg in enumerate(segments):
        v_label = f"s{i}v"
        a_label = f"s{i}a"
        # speed 효과 적용 결정 — main segment + 다중 src track 의 insert segment.
        # 다중 src track 은 source="insert" 지만 timeline 시간축에 정상 위치하므로 적용.
        # 기존 cut.insert (source_id=cut.id) 만 차단 (위에서 이미 speed+cut 결합 차단).
        speed_match: Optional[SpeedEffect] = None
        if speeds and (seg.source == "main" or seg.source_id in track_src_index):
            speed_match = _speed_overlapping_segment(speeds, seg)
        # speed 가 적용되면 video setpts 는 PTS/{rate} (가속) 또는 PTS*N (감속) 로,
        # audio 는 atempo 체인으로. setpts=PTS/2.0 = 2배속 (시간축 절반).
        speed_v_filter = ""
        speed_a_filter = ""
        if speed_match is not None:
            r = float(speed_match.rate)
            speed_v_filter = f",setpts=PTS/{r:g}"
            speed_a_filter = "," + _atempo_chain(r)

        # zoom 효과 적용 결정 — main + 다중 src track insert.
        zoom_match: Optional[ZoomEffect] = None
        if zooms and (seg.source == "main" or seg.source_id in track_src_index):
            zoom_match = _zoom_overlapping_segment(zooms, seg)
        zoom_filter = ""
        if zoom_match is not None:
            zoom_filter = "," + _zoom_crop_scale_filter(zoom_match, surface_w, surface_h)

        # concat 필터는 모든 segment 의 stream 속성 (픽셀 포맷·SAR·오디오 sample
        # rate·채널 layout) 이 일치해야 함. 다중 segment / 다중 src 시 원본 파일
        # 별로 다를 수 있어 libx264 가 -22 (Invalid argument) 로 실패하던 회귀.
        # video: format=yuv420p,setsar=1 / audio: aformat=stereo,44100 강제.
        v_norm = ",format=yuv420p,setsar=1"
        a_norm = ",aformat=channel_layouts=stereo:sample_rates=44100"
        if seg.source == "main":
            in_s = seg.source_start_ms / 1000.0
            out_s = seg.source_end_ms / 1000.0
            fc_parts.append(
                f"[0:v]trim={in_s}:{out_s},setpts=PTS-STARTPTS{speed_v_filter},"
                f"{_scale_filter('stretch', surface_w, surface_h)}{zoom_filter}{v_norm}[{v_label}]"
            )
            fc_parts.append(
                f"[0:a]atrim={in_s}:{out_s},asetpts=PTS-STARTPTS{speed_a_filter}{a_norm}[{a_label}]"
            )
        else:
            # source_id 가 cut.id 면 cut 의 insert, src 경로면 track 다중 src.
            in_s = seg.source_start_ms / 1000.0
            out_s = seg.source_end_ms / 1000.0
            if seg.source_id in track_src_index:
                idx = track_src_index[seg.source_id]
                scale_mode = "stretch"   # 다중 src track 은 일관되게 stretch.
            else:
                cut = next(c for c in cuts if c.id == seg.source_id)
                idx = cut_src_index[cut.id]
                scale_mode = cut.scale_mode
            fc_parts.append(
                f"[{idx}:v]trim={in_s}:{out_s},setpts=PTS-STARTPTS{speed_v_filter},"
                f"{_scale_filter(scale_mode, surface_w, surface_h)}{zoom_filter}{v_norm}[{v_label}]"
            )
            fc_parts.append(
                f"[{idx}:a]atrim={in_s}:{out_s},asetpts=PTS-STARTPTS{speed_a_filter}{a_norm}[{a_label}]"
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

    # broll PiP overlay (Stage 7 v1) — 캡션 overlay 다음.
    # 각 broll 의 입력 스트림을 size_ratio 만큼 scale + setpts 시프트 후 corner 위치에 overlay.
    # placement/pip/audio_mix 는 이미 위에서 검증됨 (PiP only, audio=original_only).
    for i, broll in enumerate(brolls):
        broll_idx = broll_input_index[i]
        assert broll.pip is not None   # 위 가드가 보장
        ratio = float(broll.pip.size_ratio)
        pip_w = int(round(surface_w * ratio))
        pip_h = int(round(surface_h * ratio))
        bx, by = _broll_pip_xy(
            broll.pip.corner, surface_w, surface_h, pip_w, pip_h,
            pos_x=broll.pip.pos_x, pos_y=broll.pip.pos_y,
        )
        in_s = broll.in_ms / 1000.0
        out_s = broll.out_ms / 1000.0
        # broll 입력을 scale 후 PTS 를 in_s 만큼 시프트 — 그러면 broll 의 0초가 in_s 에 정렬.
        fc_parts.append(
            f"[{broll_idx}:v]scale={pip_w}:{pip_h},"
            f"setpts=PTS-STARTPTS+{in_s:.3f}/TB[broll{i}]"
        )
        next_v = f"vb{i}"
        fc_parts.append(
            f"[{cur_v}][broll{i}]overlay={bx}:{by}:"
            f"enable='between(t\\,{in_s}\\,{out_s})'[{next_v}]"
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


def _build_timeline_from_video_track(
    video_track, main_src_path: str,
) -> tuple[list[TimelineSegment], list[str]]:
    """sidecar.video_track 의 VideoSegment 들을 export 용 TimelineSegment 로 변환.

    각 VideoSegment 는:
    - src == main_src_path 면 source="main" (ffmpeg [0:v] 사용)
    - 다른 src 면 source="insert" + source_id=src path (별도 input 필요)

    Returns: (segments, extra_srcs) — extra_srcs 는 src_path 외 unique 경로의
    삽입 순서 리스트. 호출자가 그 순서대로 ffmpeg -i 인자를 추가하고 input idx
    를 src 경로 키로 lookup 한다.

    combined_start_ms 는 0 부터 누적합 — 사용자가 만든 갭은 export 결과에서 제거.
    """
    segs = sorted(video_track, key=lambda s: s.start_ms)
    out: list[TimelineSegment] = []
    extra_srcs: list[str] = []
    extra_set: set[str] = set()
    combined_cursor = 0
    for s in segs:
        src_in = int(s.src_in_ms)
        src_out = int(s.src_out_ms) if s.src_out_ms > 0 else int(s.src_duration_ms)
        if src_out <= src_in:
            continue
        length = src_out - src_in
        if s.src == main_src_path:
            source_type = "main"
            source_id = None
        else:
            source_type = "insert"
            source_id = s.src
            if s.src not in extra_set:
                extra_set.add(s.src)
                extra_srcs.append(s.src)
        out.append(TimelineSegment(
            combined_start_ms=combined_cursor,
            combined_end_ms=combined_cursor + length,
            source=source_type,
            source_id=source_id,
            source_start_ms=src_in,
            source_end_ms=src_out,
        ))
        combined_cursor += length
    return out, extra_srcs


def _split_main_segments_at_effect_boundaries(
    segments: list[TimelineSegment],
    speeds: list[SpeedEffect],
    zooms: list[ZoomEffect],
) -> list[TimelineSegment]:
    """speed/zoom 효과의 in_ms / out_ms 경계점에서 main segment 들을 잘라
    각 segment 가 효과에 완전 포함되거나 완전 밖에 있도록 만든다.

    이전엔 partial overlap 이면 _speed/zoom_overlapping_segment 가
    NotImplementedError. 사용자가 segment 보다 짧은 구간에 효과를 걸면 export
    자체가 막혔다. 이 함수가 그 케이스를 자동 split 으로 해결.

    insert segment 는 영향 없음 — v1 에서 speed/zoom + cut/insert 결합은 별도로
    이미 차단됨. main segment 안에서 source_start_ms ~ source_end_ms 사이에
    떨어지는 boundary 들만 split 점으로 사용. main segment 안에서 source 와
    combined 는 1:1 매핑 (build_combined_timeline 보장) 이므로 offset 만 보존.
    """
    boundary_points: set[int] = set()
    for sp in speeds:
        boundary_points.add(int(sp.in_ms))
        boundary_points.add(int(sp.out_ms))
    for z in zooms:
        boundary_points.add(int(z.in_ms))
        boundary_points.add(int(z.out_ms))

    out: list[TimelineSegment] = []
    for seg in segments:
        if seg.source != "main":
            out.append(seg)
            continue
        s_start = seg.source_start_ms
        s_end = seg.source_end_ms
        inside = sorted(b for b in boundary_points if s_start < b < s_end)
        if not inside:
            out.append(seg)
            continue
        # main segment 안 source-to-combined offset (build_combined_timeline 보장).
        offset = seg.combined_start_ms - s_start
        prev_src = s_start
        for b in inside:
            out.append(TimelineSegment(
                combined_start_ms=prev_src + offset,
                combined_end_ms=b + offset,
                source="main",
                source_id=None,
                source_start_ms=prev_src,
                source_end_ms=b,
            ))
            prev_src = b
        # 마지막 잔여 부분.
        out.append(TimelineSegment(
            combined_start_ms=prev_src + offset,
            combined_end_ms=seg.combined_end_ms,
            source="main",
            source_id=None,
            source_start_ms=prev_src,
            source_end_ms=s_end,
        ))
    return out


def _apply_trim_to_main_segments(
    segments: list[TimelineSegment],
    trim_in_ms: int,
    trim_out_ms: int,
) -> list[TimelineSegment]:
    """main segment 의 source_start/end 를 [trim_in, trim_out] 으로 clip.
    범위 밖 main segment 는 제거. insert segment 는 그대로 통과.
    combined_start/end 는 재계산.
    """
    out: list[TimelineSegment] = []
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
