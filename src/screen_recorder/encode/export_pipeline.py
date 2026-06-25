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
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

_NVENC_CACHE: dict[str, bool] = {}


def nvenc_available(ffmpeg_path) -> bool:
    """h264_nvenc(NVIDIA GPU 인코더)가 이 머신에서 **실제로 동작**하는지.

    빌드에 --enable-nvenc 가 있어도 드라이버/GPU 가 없으면 실패하므로, encoders 목록
    조회로는 부족하고 작은 테스트 인코드(256×256 1프레임)를 실제로 돌려 rc 로 판정한다.
    (NVENC 는 최소 프레임 크기가 있어 64×64 같은 너무 작은 해상도는 'Frame Dimension
    less than minimum' 으로 실패 — 256 이면 안전.) 결과는 ffmpeg 경로별로 캐시(세션 1회).
    ffmpeg_path 가 실제 파일이 아닐 때(단위 테스트의 더미 'ffmpeg')는 테스트하지 않고
    False — 테스트가 libx264 로 결정적이게.
    """
    key = str(ffmpeg_path)
    if key in _NVENC_CACHE:
        return _NVENC_CACHE[key]
    ok = False
    if Path(ffmpeg_path).exists():
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            r = subprocess.run(
                [str(ffmpeg_path), "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1:r=5",
                 "-c:v", "h264_nvenc", "-f", "null", "-"],
                capture_output=True, timeout=20, creationflags=flags,
            )
            ok = (r.returncode == 0)
        except Exception:
            ok = False
    _NVENC_CACHE[key] = ok
    return ok


def _alpha_overlay_chain(png_idx, label, in_s, out_s, fade_in, fade_out) -> str:
    """PNG 입력 → format=rgba + (0보다 큰) alpha fade → [label]. fade 가 0 이면 그
    필터를 **생략**한다.

    ⚠ ffmpeg 의 fade 는 `d=0` 을 '페이드 없음'이 아니라 **기본 길이 페이드**로 처리한다.
    그래서 경계를 넘는 캡션이 조각으로 쪼개질 때 이음매 fade 를 0 으로 줘도 `d=0` 필터를
    그대로 두면 오히려 기본 길이만큼 다시 페이드되어 캡션이 깜빡인다 → 0 이면 필터 자체를 뺀다.
    """
    parts = ["format=rgba"]
    if fade_in > 0:
        parts.append(f"fade=t=in:st={in_s}:d={fade_in}:alpha=1")
    if fade_out > 0:
        parts.append(f"fade=t=out:st={out_s - fade_out}:d={fade_out}:alpha=1")
    return f"[{png_idx}:v]" + ",".join(parts) + f"[{label}]"

from ..effects import Sidecar
from ..effects.timeline import TimelineSegment, build_combined_timeline
from ..effects.types.arrow import ArrowEffect
from ..effects.types.rect import RectEffect
from ..effects.types.broll import BrollEffect
from ..effects.types.caption import CaptionEffect
from ..effects.types.cut import CutEffect
from ..effects.types.speed import SpeedEffect
from ..effects.types.zoom import ZoomEffect
from .arrow_png import render_arrow_png
from .rect_png import render_rect_png
from .caption_png import render_caption_png
from .speed_hud_png import render_speed_hud_png


_SUPPORTED_TYPES = {"caption", "cut", "speed", "zoom", "broll", "arrow", "rect"}


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

    effect.in_ms/out_ms 는 combined timeline ms 기준. 따라서 segment 도
    combined_start_ms/combined_end_ms 로 비교해야 정확. 다중 segment 트랙에서
    src_in/out 으로 자르기를 한 경우 source ms ≠ combined ms 가 되는데, 이전엔
    source_start_ms 와 비교해 partial overlap 오분류 회귀가 있었음.

    겹침 분류 (combined ms 기준):
    - 완전 포함: sp.in_ms <= combined_start AND sp.out_ms >= combined_end → 매칭
    - 완전 밖: sp.out_ms <= combined_start OR sp.in_ms >= combined_end → 미매칭
    - 부분 겹침: NotImplementedError (호출 측이 사전에 _split_main_segments_at_effect_boundaries 로 해결)
    """
    seg_start = seg.combined_start_ms
    seg_end = seg.combined_end_ms
    for sp in speeds:
        if sp.out_ms <= seg_start or sp.in_ms >= seg_end:
            continue   # 완전 밖
        if sp.in_ms <= seg_start and sp.out_ms >= seg_end:
            return sp   # 완전 포함
        # 부분 겹침
        raise NotImplementedError(
            f"SpeedEffect partial overlap with segment "
            f"(speed: {sp.in_ms}-{sp.out_ms}, combined segment: {seg_start}-{seg_end}); "
            f"v1 requires speed regions to fully contain or sit outside each segment"
        )
    return None


def _zoom_overlapping_segment(zooms: list[ZoomEffect], seg: TimelineSegment) -> Optional[ZoomEffect]:
    """seg 와 시간상 겹치는 ZoomEffect 를 반환 (없으면 None). _speed_overlapping_segment
    와 동일 규칙, combined ms 기준."""
    seg_start = seg.combined_start_ms
    seg_end = seg.combined_end_ms
    for z in zooms:
        if z.out_ms <= seg_start or z.in_ms >= seg_end:
            continue   # 완전 밖
        if z.in_ms <= seg_start and z.out_ms >= seg_end:
            return z   # 완전 포함
        # 부분 겹침
        raise NotImplementedError(
            f"ZoomEffect partial overlap with segment "
            f"(zoom: {z.in_ms}-{z.out_ms}, combined segment: {seg_start}-{seg_end}); "
            f"v1 requires zoom regions to fully contain or sit outside each segment"
        )
    return None


def _zoom_crop_scale_filter(z: ZoomEffect, surface_w: int, surface_h: int) -> str:
    """ZoomEffect → ffmpeg 필터 문자열.

    mode == "fit_screen" (기본): 중심 (cx*w, cy*h) 로부터 (w/scale × h/scale) 영역을
    잘라낸 뒤 원본 surface 크기로 다시 scale — 영역이 화면 전체를 채움.

    mode == "magnify_region" (Phase 24): region_w × region_h 크기의 부분 영역만 N배
    확대해 같은 중심 위치에 덮어쓰기. 나머지는 원본 그대로 (split → overlay).

    flags=lanczos — 줌 후 upscale 시 기본 bicubic 보다 sharp.
    """
    scale = max(0.1, float(z.start.scale))
    cx = float(z.start.cx)
    cy = float(z.start.cy)
    mode = getattr(z, "mode", "fit_screen")

    if mode == "magnify_region":
        region_w = max(0.05, min(1.0, float(getattr(z, "region_w", 0.3))))
        region_h = max(0.05, min(1.0, float(getattr(z, "region_h", 0.3))))
        # Phase 27 — dest rect 는 source 와 분리. 사이드카에 없는 구버전은 source × scale 로 보정.
        dest_cx = float(getattr(z, "dest_cx", cx))
        dest_cy = float(getattr(z, "dest_cy", cy))
        dest_w_n = float(getattr(z, "dest_w", region_w * scale))
        dest_h_n = float(getattr(z, "dest_h", region_h * scale))
        src_w = surface_w * region_w
        src_h = surface_h * region_h
        src_x = cx * surface_w - src_w / 2.0
        src_y = cy * surface_h - src_h / 2.0
        dst_w = surface_w * dest_w_n
        dst_h = surface_h * dest_h_n
        dst_x = dest_cx * surface_w - dst_w / 2.0
        dst_y = dest_cy * surface_h - dst_h / 2.0
        return (
            f"split=2[mzbg][mzsrc];"
            f"[mzsrc]crop={src_w:.0f}:{src_h:.0f}:{src_x:.0f}:{src_y:.0f},"
            f"scale={dst_w:.0f}:{dst_h:.0f}:flags=lanczos[mzmag];"
            f"[mzbg][mzmag]overlay=x={dst_x:.0f}:y={dst_y:.0f}"
        )

    crop_w = surface_w / scale
    crop_h = surface_h / scale
    crop_x = cx * surface_w - crop_w / 2.0
    crop_y = cy * surface_h - crop_h / 2.0
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
    mute_audio: bool = False,
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
    # 2026-05-20: active_effects() — 사용자가 OFF 한 효과는 export 도 제외.
    # 비활성 효과의 미지원 type 도 검사 skip (어차피 export 안 함).
    effects_active = sidecar.active_effects()
    for e in effects_active:
        if e.type not in _SUPPORTED_TYPES:
            raise NotImplementedError(f"{e.type!r} effect export not implemented yet")

    cuts = [e for e in effects_active if isinstance(e, CutEffect)]
    captions = [e for e in effects_active if isinstance(e, CaptionEffect)]
    speeds = [e for e in effects_active if isinstance(e, SpeedEffect)]
    zooms = [e for e in effects_active if isinstance(e, ZoomEffect)]
    brolls = [e for e in effects_active if isinstance(e, BrollEffect)]
    arrows = [e for e in effects_active if isinstance(e, ArrowEffect)]
    rects = [e for e in effects_active if isinstance(e, RectEffect)]

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
            # audio_mix v2 — 'original_only' / 'mute' / 'broll_only' / 'both' 모두 지원.
            # 이미지 broll (확장자 .png/.jpg/.gif) 은 audio stream 없음 → 'original_only'
            # 동작으로 자연 fallback. 사용자 명시적 audio_mix 가 그 외라도 export 통과.
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
        # gap-collapsed 시간축으로 effects 의 in_ms/out_ms 도 remap.
        # 사용자 effects 는 user combined ms (gap 포함). export 결과는 concat 으로
        # gap 이 제거된 시간축. mapping 안 하면 효과가 시간창 밖이라 안 보임.
        captions = _remap_effects_to_gap_collapsed(captions, sidecar.video_track)
        speeds = _remap_effects_to_gap_collapsed(speeds, sidecar.video_track)
        zooms = _remap_effects_to_gap_collapsed(zooms, sidecar.video_track)
        brolls = _remap_effects_to_gap_collapsed(brolls, sidecar.video_track)
        arrows = _remap_effects_to_gap_collapsed(arrows, sidecar.video_track)
        rects = _remap_effects_to_gap_collapsed(rects, sidecar.video_track)
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

    # 2) 캡션 / 화살표 PNG 생성
    png_dir_path = Path(png_dir) if png_dir is not None else Path(tempfile.mkdtemp(prefix="kstudio_export_"))
    png_paths: list[Path] = []
    for cap in captions:
        png = png_dir_path / f"caption_{cap.id}.png"
        render_caption_png(cap, surface_w=surface_w, surface_h=surface_h, dst=png)
        png_paths.append(png)
    # arrow PNG — caption 과 같은 패턴. arrow 와 caption 은 별개 overlay 체인이라
    # png_paths 는 caption 만 담고 arrow 는 별도 리스트로 추적.
    arrow_png_paths: list[Path] = []
    for arr in arrows:
        png = png_dir_path / f"arrow_{arr.id}.png"
        render_arrow_png(arr, surface_w=surface_w, surface_h=surface_h, dst=png)
        arrow_png_paths.append(png)

    # 사각형 PNG — arrow 와 같은 패턴, 별도 overlay 체인.
    rect_png_paths: list[Path] = []
    for rc in rects:
        png = png_dir_path / f"rect_{rc.id}.png"
        render_rect_png(rc, surface_w=surface_w, surface_h=surface_h, dst=png)
        rect_png_paths.append(png)

    # 배속 HUD ("▶▶ N× 배속") PNG — show_hud=True 인 SpeedEffect 만.
    # font_pt: preview 의 14pt 가 ~800px 위젯에 맞으니 surface_w/800 비례로 잡음 — 4K 도 자연스럽게.
    speed_hud_pngs: list[tuple[Path, SpeedEffect, int, int]] = []   # (png, eff, w_px, h_px)
    hud_font_pt = max(14, int(round(14 * surface_w / 800.0)))
    for sp in speeds:
        if not getattr(sp, "show_hud", False):   # 2026-06-23 기본 OFF 와 일관
            continue
        png = png_dir_path / f"speed_hud_{sp.id}.png"
        w_px, h_px = render_speed_hud_png(sp, font_pt=hud_font_pt, dst=png)
        speed_hud_pngs.append((png, sp, w_px, h_px))

    # 3) ffmpeg 입력 — A + B (cut 의 src 들, 중복 제거) + caption PNG 들
    argv: list[str] = [str(ffmpeg_path), "-y", "-loglevel", "info"]
    argv.extend(["-i", str(src_path)])

    # 2026-06-09 OOM fix: main src 의 segment 가 ≥2 개면 [0:v] 한 디코더에서 여러
    # trim 이 split 으로 갈라지고 concat 이 순서대로(seg0→seg1→…) 소비한다. 그러면
    # 아직 차례가 안 온 가지(예: 마지막 25분 구간)에 디코더가 읽는 프레임이 통째로
    # 버퍼링되어 29분 영상에서 수십 GB → '-12 Cannot allocate memory' 로 죽었다
    # (실측: 6초만에 14GB, frame=0). 첫 main segment 만 [0:v]trim 으로 두어 [0:v]
    # 소비자를 1개로 유지(= split fan-out 없음)하고, 나머지 main segment 는 각자
    # -ss/-t 로 그 구간부터 독립 디코딩하는 별도 입력으로 분리한다. 컷 없는 단일
    # segment(흔한 경우)는 main_seg_input 이 비어 동작이 전혀 바뀌지 않는다.
    next_input = 1
    main_seg_input: dict[int, int] = {}   # segments idx → seek 입력 index (첫 조각은 [0] 재사용 → 미포함)
    _main_seen = False
    for si, seg in enumerate(segments):
        if seg.source != "main":
            continue
        if not _main_seen:
            _main_seen = True            # 첫 main 조각: input 0 의 trim 으로 처리 (별도 입력 X)
            continue
        seg_in_s = seg.source_start_ms / 1000.0
        seg_dur_s = max(0.001, (seg.source_end_ms - seg.source_start_ms) / 1000.0)
        argv.extend(["-ss", f"{seg_in_s:.3f}", "-t", f"{seg_dur_s:.3f}", "-i", str(src_path)])
        main_seg_input[si] = next_input
        next_input += 1

    cut_src_index: dict[str, int] = {}    # cut.id → ffmpeg input index
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

    # 각 input 의 audio stream 유무 확인. 하나라도 없으면 audio chain 전체 우회
    # (filter 의 [idx:a] 가 "matches no streams" 로 export 실패하던 회귀).
    # 화면 녹화에 마이크 입력 없거나 drag-drop 한 영상에 audio 없을 때 발생.
    from ..services.media_probe import has_audio_stream
    _audio_srcs = [str(src_path)] + [c.src for c in cuts if c.has_insert] + list(track_extra_srcs)
    # mute_audio: 사용자 음소거 토글. True 면 오디오를 아예 없는 것으로 취급 →
    # 아래 OOM fix 의 전용 오디오 입력/분리 concat/-c:a 가 모두 if audio_available:
    # 게이트로 빠져 무음 mp4. OOM fix 구조는 건드리지 않는다.
    audio_available = (not mute_audio) and all(has_audio_stream(s) for s in _audio_srcs)

    # 2026-06-09 OOM fix part 2: 오디오를 비디오와 **다른 디코더**로 분리한다.
    # concat 이 v/a 를 한 묶음으로 당기는데, 오디오(atempo)는 가볍고 빨라서 공유 디코더를
    # 앞질러 끌고 간다. 그러면 디코딩된 무거운 비디오 프레임이 느린 caption overlay 체인
    # 앞에 쌓여 긴 영상(29분)+캡션+오디오에서 수십 GB → OOM (실측: 오디오만 끄면 bounded).
    # main src 오디오 전용 입력(-i)을 따로 두면 비디오 디코더는 overlay 소비 속도로만
    # 진행 → 오디오 끈 것과 같은 bounded 상태가 된다. 오디오 프레임은 작아 racing 해도 영향
    # 미미. (insert/track 오디오는 이미 별도 입력이라 그대로.)
    main_audio_input = 0
    if audio_available:
        argv.extend(["-i", str(src_path)])
        main_audio_input = next_input
        next_input += 1

    # 캡션 / broll 의 in_ms/out_ms 는 user gap-collapsed ms. setpts 로 압축된 output
    # 스트림의 t 와 일치하려면 segment 별 rate 로 변환해야 함. 이 매핑은 segments +
    # speeds 가 확정된 후에만 가능 — 이 함수 끝까지 둘 다 결정돼 있음.
    user_to_output = _build_user_to_output_time_map(segments, speeds)

    png_input_index: dict[int, int] = {}   # png_paths idx → ffmpeg input index
    # PNG 는 single frame demuxer — overlay enable 시간창에 도달 전 stream EOF 회피용
    # bound. -t 는 *output duration*, -itsoffset 으로 output timebase 의 변환된 in 시점에
    # PTS 시작. 이전엔 user time 을 그대로 써서 배속 segment 의 캡션이 잘못된 시간에 또는
    # 아예 안 나타나던 회귀.
    for i, (png, cap) in enumerate(zip(png_paths, captions)):
        out_in_s = user_to_output(cap.in_ms) / 1000.0
        out_out_s = user_to_output(cap.out_ms) / 1000.0
        cap_dur_s = max(0.1, out_out_s - out_in_s)
        argv.extend([
            "-loop", "1", "-framerate", "30",
            "-t", f"{cap_dur_s:.3f}",
            "-itsoffset", f"{out_in_s:.3f}",
            "-i", str(png),
        ])
        png_input_index[i] = next_input
        next_input += 1

    # 화살표 PNG 입력 — 캡션과 같은 패턴.
    arrow_input_index: dict[int, int] = {}
    for i, (png, arr) in enumerate(zip(arrow_png_paths, arrows)):
        out_in_s = user_to_output(arr.in_ms) / 1000.0
        out_out_s = user_to_output(arr.out_ms) / 1000.0
        dur_s = max(0.1, out_out_s - out_in_s)
        argv.extend([
            "-loop", "1", "-framerate", "30",
            "-t", f"{dur_s:.3f}",
            "-itsoffset", f"{out_in_s:.3f}",
            "-i", str(png),
        ])
        arrow_input_index[i] = next_input
        next_input += 1

    # 사각형 PNG 입력 — arrow 와 같은 패턴.
    rect_input_index: dict[int, int] = {}
    for i, (png, rc) in enumerate(zip(rect_png_paths, rects)):
        out_in_s = user_to_output(rc.in_ms) / 1000.0
        out_out_s = user_to_output(rc.out_ms) / 1000.0
        dur_s = max(0.1, out_out_s - out_in_s)
        argv.extend([
            "-loop", "1", "-framerate", "30",
            "-t", f"{dur_s:.3f}",
            "-itsoffset", f"{out_in_s:.3f}",
            "-i", str(png),
        ])
        rect_input_index[i] = next_input
        next_input += 1

    # 배속 HUD PNG 입력 — 캡션과 같은 패턴. output 시간으로 -t / -itsoffset bound.
    speed_hud_input_index: dict[int, int] = {}   # speed_hud_pngs idx → ffmpeg input index
    for i, (png, sp, _w, _h) in enumerate(speed_hud_pngs):
        out_in_s = user_to_output(sp.in_ms) / 1000.0
        out_out_s = user_to_output(sp.out_ms) / 1000.0
        hud_dur_s = max(0.1, out_out_s - out_in_s)
        argv.extend([
            "-loop", "1", "-framerate", "30",
            "-t", f"{hud_dur_s:.3f}",
            "-itsoffset", f"{out_in_s:.3f}",
            "-i", str(png),
        ])
        speed_hud_input_index[i] = next_input
        next_input += 1

    # broll PiP 입력 — speed HUD PNG 다음 차례. 각 broll 마다 -i 추가.
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
            # 비디오: 첫 조각은 [0:v]trim, 이후 조각은 -ss 로 이미 잘린 독립 입력 [k:v]
            # (한 디코더 fan-out → concat 버퍼링 폭주 방지, 위 OOM fix part 1 참조).
            if i in main_seg_input:
                v_src = f"[{main_seg_input[i]}:v]"
            else:
                v_src = f"[0:v]trim={in_s}:{out_s},"
            # 오디오: 항상 **전용 오디오 입력**에서 atrim — 비디오 디코더와 분리(part 2).
            a_src = f"[{main_audio_input}:a]atrim={in_s}:{out_s},"
            fc_parts.append(
                f"{v_src}setpts=PTS-STARTPTS{speed_v_filter},"
                # fit = 비율 보존 레터박스. main 조각이 캔버스(surface)와 같은 비율이면
                # no-op(검은 띠 없음)이고, 캔버스가 다른 클립 기준일 때만 늘이지 않고
                # 검은 여백을 넣어 찌그러짐 방지 (2026-06-19 사용자 보고).
                f"{_scale_filter('fit', surface_w, surface_h)}{zoom_filter}{v_norm}[{v_label}]"
            )
            if audio_available:
                fc_parts.append(
                    f"{a_src}asetpts=PTS-STARTPTS{speed_a_filter}{a_norm}[{a_label}]"
                )
        else:
            # source_id 가 cut.id 면 cut 의 insert, src 경로면 track 다중 src.
            in_s = seg.source_start_ms / 1000.0
            out_s = seg.source_end_ms / 1000.0
            if seg.source_id in track_src_index:
                idx = track_src_index[seg.source_id]
                # 다중 src track 은 fit(레터박스)로 캔버스에 맞춘다 — 비율 다른 클립을
                # 늘여 찌그러뜨리지 않고 검은 여백으로 채움 (2026-06-19 사용자 보고).
                # 캔버스=첫 클립(surface_w/h) 기준은 그대로.
                scale_mode = "fit"
            else:
                cut = next(c for c in cuts if c.id == seg.source_id)
                idx = cut_src_index[cut.id]
                scale_mode = cut.scale_mode
            fc_parts.append(
                f"[{idx}:v]trim={in_s}:{out_s},setpts=PTS-STARTPTS{speed_v_filter},"
                f"{_scale_filter(scale_mode, surface_w, surface_h)}{zoom_filter}{v_norm}[{v_label}]"
            )
            if audio_available:
                fc_parts.append(
                    f"[{idx}:a]atrim={in_s}:{out_s},asetpts=PTS-STARTPTS{speed_a_filter}{a_norm}[{a_label}]"
                )
        seg_labels.append((v_label, a_label))

    # concat — audio_available 따라 a=1 or a=0.
    n = len(seg_labels)
    if n == 0:
        # cut 0 개 + main_duration 0 → 빈 효과. fallback: 전체 영상 사용.
        fc_parts.append(
            f"[0:v]{_scale_filter('stretch', surface_w, surface_h)}[outv0]"
        )
        if audio_available:
            fc_parts.append(f"[0:a]anull[outa0]")
            cur_v, cur_a = "outv0", "outa0"
        else:
            cur_v, cur_a = "outv0", None
    else:
        if audio_available:
            # OOM fix part 2: 비디오·오디오 concat 을 **분리**한다. 하나의 concat=v=1:a=1
            # 은 v/a 를 한 묶음으로 당겨, 빠른 오디오가 전체를 앞질러 끌고 가 무거운 비디오
            # 프레임이 느린 overlay 앞에 쌓인다 → 긴 영상에서 OOM. 비디오 concat 은 a=0 으로
            # 두어 오직 비디오 인코더(overlay 체인)에만 끌려가게 하고, 오디오는 독립 concat.
            v_inputs = "".join(f"[{v}]" for v, _a in seg_labels)
            a_inputs = "".join(f"[{a}]" for _v, a in seg_labels)
            fc_parts.append(f"{v_inputs}concat=n={n}:v=1:a=0[concv]")
            fc_parts.append(f"{a_inputs}concat=n={n}:v=0:a=1[conca]")
            cur_v, cur_a = "concv", "conca"
        else:
            concat_inputs = "".join(f"[{v}]" for v, _a in seg_labels)
            fc_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[concv]")
            cur_v, cur_a = "concv", None

    # 캡션 overlay (alpha fade 포함). enable 의 t 는 output 스트림 시간 — speed
    # 압축 후의 시간이므로 user_to_output 변환 필수.
    for i, cap in enumerate(captions):
        png_idx = png_input_index[i]
        in_s = user_to_output(cap.in_ms) / 1000.0
        out_s = user_to_output(cap.out_ms) / 1000.0
        # 페이드 길이는 사용자 의도 그대로 (output 시간 척도). 배속 안 캡션 페이드도
        # output 시간에서 fade_in_ms 동안 페이드.
        fade_in = cap.fade.in_ms / 1000.0
        fade_out = cap.fade.out_ms / 1000.0
        # PNG input 이 -loop 1 -t <output duration> 로 bound 됐으므로 filter 안 loop 불필요.
        # alpha fade 채널 — fade=0(경계로 쪼개진 이음매)이면 필터 생략(깜빡임 방지).
        fc_parts.append(_alpha_overlay_chain(png_idx, f"cap{i}", in_s, out_s, fade_in, fade_out))
        next_v = f"v{i+1}"
        fc_parts.append(
            f"[{cur_v}][cap{i}]overlay=enable='between(t\\,{in_s}\\,{out_s})'[{next_v}]"
        )
        cur_v = next_v

    # 화살표 overlay — 캡션 다음. alpha fade + 시간창 enable.
    for i, arr in enumerate(arrows):
        png_idx = arrow_input_index[i]
        in_s = user_to_output(arr.in_ms) / 1000.0
        out_s = user_to_output(arr.out_ms) / 1000.0
        fade_in = arr.fade.in_ms / 1000.0
        fade_out = arr.fade.out_ms / 1000.0
        fc_parts.append(_alpha_overlay_chain(png_idx, f"arr{i}", in_s, out_s, fade_in, fade_out))
        next_v = f"va{i}"
        fc_parts.append(
            f"[{cur_v}][arr{i}]overlay=enable='between(t\\,{in_s}\\,{out_s})'[{next_v}]"
        )
        cur_v = next_v

    # 사각형 overlay — 화살표 다음. alpha fade + 시간창 enable.
    for i, rc in enumerate(rects):
        png_idx = rect_input_index[i]
        in_s = user_to_output(rc.in_ms) / 1000.0
        out_s = user_to_output(rc.out_ms) / 1000.0
        fade_in = rc.fade.in_ms / 1000.0
        fade_out = rc.fade.out_ms / 1000.0
        fc_parts.append(_alpha_overlay_chain(png_idx, f"rect{i}", in_s, out_s, fade_in, fade_out))
        next_v = f"vr{i}"
        fc_parts.append(
            f"[{cur_v}][rect{i}]overlay=enable='between(t\\,{in_s}\\,{out_s})'[{next_v}]"
        )
        cur_v = next_v

    # 배속 HUD overlay — 화살표 다음. 오른쪽 위 corner + _HUD_MARGIN_PX 마진.
    # preview 의 reposition_huds 가 우측 상단 기본 — export 도 동일 의도로.
    _HUD_MARGIN_PX = 16
    for i, (_png, sp, w_px, h_px) in enumerate(speed_hud_pngs):
        png_idx = speed_hud_input_index[i]
        out_in_s = user_to_output(sp.in_ms) / 1000.0
        out_out_s = user_to_output(sp.out_ms) / 1000.0
        x = surface_w - w_px - _HUD_MARGIN_PX
        y = _HUD_MARGIN_PX
        next_v = f"vh{i}"
        fc_parts.append(
            f"[{cur_v}][{png_idx}:v]overlay={x}:{y}:"
            f"enable='between(t\\,{out_in_s}\\,{out_out_s})'[{next_v}]"
        )
        cur_v = next_v

    # broll PiP overlay (Stage 7 v1) — 캡션·HUD overlay 다음.
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
        # broll 도 output 시간 척도로 변환 (배속 segment 안에 들어 있다면 압축됨).
        in_s = user_to_output(broll.in_ms) / 1000.0
        out_s = user_to_output(broll.out_ms) / 1000.0
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

    # broll audio mixing (v2) — audio_mix 모드별 main + broll audio 합성.
    # original_only: 변경 없음 (main 만)
    # mute: main 의 broll 시간창 silence
    # broll_only: main silence + broll audio 추가
    # both: main 의 broll 시간창에 audio_balance 만큼 attenuate + broll audio (1-audio_balance) 만큼 mix
    # 이미지 broll (확장자 .png/.jpg/.gif) 은 audio stream 없으니 original_only 로 자동 fallback.
    if cur_a is not None:
        _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
        for i, broll in enumerate(brolls):
            if broll.audio_mix == "original_only":
                continue
            broll_idx = broll_input_index[i]
            src_ext = Path(broll.src).suffix.lower() if broll.src else ""
            broll_has_audio = src_ext not in _IMAGE_EXTS
            in_s = user_to_output(broll.in_ms) / 1000.0
            out_s = user_to_output(broll.out_ms) / 1000.0
            # 1. main audio 의 broll 시간창 attenuation.
            if broll.audio_mix == "mute":
                main_vol = 0.0
            elif broll.audio_mix == "broll_only":
                main_vol = 0.0
            elif broll.audio_mix == "both":
                # audio_balance: 0.0 = broll 우세, 1.0 = 원본 우세.
                main_vol = float(broll.audio_balance)
            else:
                continue   # 알 수 없는 모드 — 안전하게 건너뜀
            a_main_next = f"am{i}"
            fc_parts.append(
                f"[{cur_a}]volume=enable='between(t\\,{in_s}\\,{out_s})':"
                f"volume={main_vol:.3f}[{a_main_next}]"
            )
            cur_a = a_main_next
            # 2. broll audio 추가 (mute 모드 또는 이미지 broll 이면 추가 X).
            if broll.audio_mix == "mute" or not broll_has_audio:
                continue
            if broll.audio_mix == "broll_only":
                broll_vol = 1.0
            else:   # both
                broll_vol = 1.0 - float(broll.audio_balance)
            # broll source 에서 audio 잘라내고 in_s 만큼 delay 후 volume 조절.
            # adelay 의 ms 단위 정수, asetpts 으로 PTS reset 한 뒤 delay.
            in_ms_int = int(round(in_s * 1000.0))
            broll_dur_s = max(0.001, out_s - in_s)
            ba_label = f"ba{i}"
            fc_parts.append(
                f"[{broll_idx}:a]atrim=0:{broll_dur_s:.3f},"
                f"asetpts=PTS-STARTPTS,"
                f"adelay={in_ms_int}|{in_ms_int},"
                f"volume={broll_vol:.3f}[{ba_label}]"
            )
            # 3. main + broll audio amix (1:1 weight, 이미 volume 으로 미리 조절됨).
            a_mix_next = f"amx{i}"
            fc_parts.append(
                f"[{cur_a}][{ba_label}]amix=inputs=2:duration=first:"
                f"dropout_transition=0[{a_mix_next}]"
            )
            cur_a = a_mix_next

    fc = ";".join(fc_parts)
    argv.extend(["-filter_complex", fc])
    argv.extend(["-map", f"[{cur_v}]"])
    if cur_a is not None:
        argv.extend(["-map", f"[{cur_a}]"])
    # 인코더 — GPU(NVENC) 가 동작하면 그걸로(인코드 단계를 GPU 로 offload, CPU 부담↓
    # + 일반 영상 export 가속), 없으면 libx264(CPU) 로 자동 폴백. 디코드·overlay 합성은
    # 여전히 CPU 라, 긴 원본 + 캡션 多 인 경우 체감 가속은 인코드 비중만큼만.
    if nvenc_available(ffmpeg_path):
        argv.extend([
            "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
            "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p",
        ])
    else:
        argv.extend([
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        ])
    if cur_a is not None:
        argv.extend(["-c:a", "aac", "-b:a", "128k"])
    # PNG 는 filter chain 의 loop filter 로 처리 — main video 가 끝나면 overlay
    # 가 자연 종료. -shortest 명시 불필요.
    argv.extend([
        "-movflags", "+faststart",
        str(dst_path),
    ])

    # caller 가 PNG 정리해야 — caption + arrow + (speed HUD 는 위 list 에 별도) 모두 포함.
    all_pngs = (list(png_paths) + list(arrow_png_paths) + list(rect_png_paths)
                + [p for p, *_ in speed_hud_pngs])
    return argv, all_pngs


def _build_user_to_output_time_map(segments, speeds):
    """gap-collapsed user_ms → output stream ms 변환 함수.

    각 segment 가 setpts=PTS/rate 로 출력 시간이 압축되므로 caption overlay 의
    `enable='between(t, in, out)'` 는 output 시간 기준으로 in/out 을 줘야 한다.
    이전엔 cap.in_ms/1000 을 그대로 enable 에 넣어 배속 segment 안의 캡션 시간이
    실제로는 사라진 위치에 표시되던 회귀.

    segments 는 _split_segments_at_effect_boundaries 후라서 각 segment 가 speed 에
    완전 포함되거나 완전 밖. segment 별 rate 찾기 1회 lookup.
    """
    mapping: list[tuple[int, int, float, float]] = []
    out_cursor = 0.0
    for seg in segments:
        cs = seg.combined_start_ms
        ce = seg.combined_end_ms
        rate = 1.0
        for sp in speeds:
            if sp.in_ms <= cs and sp.out_ms >= ce:
                rate = max(0.01, float(sp.rate))
                break
        seg_user_dur = ce - cs
        seg_out_dur = seg_user_dur / rate
        mapping.append((cs, ce, rate, out_cursor))
        out_cursor += seg_out_dur

    def user_to_output(u_ms: int) -> float:
        for cs, ce, rate, out_start in mapping:
            if cs <= u_ms < ce:
                return out_start + (u_ms - cs) / rate
        # 끝 경계 또는 끝 너머: 마지막 segment 의 끝 위치 + 잔여.
        if mapping:
            cs, ce, rate, out_start = mapping[-1]
            seg_out_dur = (ce - cs) / rate
            if u_ms == ce:
                return out_start + seg_out_dur
            return out_start + seg_out_dur + (u_ms - ce)
        return float(u_ms)

    return user_to_output


def _remap_effects_to_gap_collapsed(effects, video_track):
    """video_track 의 gap-collapsed 시간축에 맞춰 effect in_ms/out_ms 를 shift.

    각 segment 에 대해 (user_start_ms, user_end_ms, export_offset) 매핑.
    effect 가 여러 segment 에 걸쳐 있으면 각 segment 마다 sub-effect 를 하나씩
    생성 (배속·줌 효과가 segment 경계를 넘어갈 때 뒤 segment 에 효과가 적용 안 되던 버그).
    gap 에 떨어진 효과 및 gap 만 걸친 효과는 제거.
    """
    from dataclasses import replace
    if not effects or not video_track:
        return list(effects)
    segs = sorted(video_track, key=lambda s: s.start_ms)
    # (user_start, user_end, export_start) 리스트.
    cursor = 0
    ranges: list[tuple[int, int, int]] = []
    for s in segs:
        ranges.append((s.start_ms, s.end_ms, cursor))
        cursor += s.duration_ms
    out = []
    for eff in effects:
        has_fade = getattr(eff, "fade", None) is not None
        # 이 effect 와 겹치는 모든 segment 마다 sub-effect 생성.
        for us, ue, exp in ranges:
            if eff.out_ms <= us or eff.in_ms >= ue:
                continue  # 완전히 밖
            delta = exp - us
            clipped_in = max(eff.in_ms, us)
            clipped_out = min(eff.out_ms, ue)
            if clipped_out <= clipped_in:
                continue
            piece = replace(eff, in_ms=int(clipped_in + delta), out_ms=int(clipped_out + delta))
            # 캡션/화살표가 segment 경계로 쪼개질 때, **이음매(seam) 쪽 fade 를 0** 으로
            # 만든다. 안 그러면 조각1 의 fade-out 과 조각2 의 fade-in 이 이음매에서 겹쳐
            # 캡션이 잠깐 투명해졌다 돌아오며 **깜빡인다**(사용자 보고). 진짜 바깥
            # 가장자리(실제 effect in/out 과 일치하는 쪽)만 fade 유지 → 조각 사이 연속.
            if has_fade:
                fin = piece.fade.in_ms if clipped_in == eff.in_ms else 0
                fout = piece.fade.out_ms if clipped_out == eff.out_ms else 0
                piece = replace(piece, fade=replace(piece.fade, in_ms=fin, out_ms=fout))
            out.append(piece)
    return out


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


def _split_segments_at_effect_boundaries(
    segments: list[TimelineSegment],
    speeds: list[SpeedEffect],
    zooms: list[ZoomEffect],
) -> list[TimelineSegment]:
    """speed/zoom 효과의 in_ms / out_ms (combined ms 기준) 경계점에서 segment 들을
    잘라 각 segment 가 효과에 완전 포함되거나 완전 밖에 있도록 만든다.

    effect 는 combined ms, segment 의 combined_*_ms 와 비교. 자른 sub-segment 의
    source_*_ms 는 원본 segment 의 src 시간축에서 비례 매핑 — segment 안에서
    source 진행 속도가 일정하다는 (자르기/배속 없음) 가정.

    cut.insert (source_id 가 cut.id) 도 그 시간창에 효과가 걸리면 같이 split —
    이전엔 main 만 split 했는데 다중 src 트랙의 insert segment 도 timeline 시간
    축에 정상 위치하므로 일관 처리.
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
        c_start = seg.combined_start_ms
        c_end = seg.combined_end_ms
        inside = sorted(b for b in boundary_points if c_start < b < c_end)
        if not inside:
            out.append(seg)
            continue
        # source 길이 / combined 길이 비율 (보통 1, 단 매우 짧은 segment 안에서
        # 부동소수점 round 영향 회피 위해 ratio 사용).
        c_len = max(1, c_end - c_start)
        s_len = seg.source_end_ms - seg.source_start_ms
        ratio = s_len / c_len
        prev_c = c_start
        for b in inside:
            sub_c_start = prev_c
            sub_c_end = b
            sub_s_start = seg.source_start_ms + int(round((prev_c - c_start) * ratio))
            sub_s_end = seg.source_start_ms + int(round((b - c_start) * ratio))
            out.append(TimelineSegment(
                combined_start_ms=sub_c_start,
                combined_end_ms=sub_c_end,
                source=seg.source,
                source_id=seg.source_id,
                source_start_ms=sub_s_start,
                source_end_ms=sub_s_end,
            ))
            prev_c = b
        # 마지막 잔여.
        out.append(TimelineSegment(
            combined_start_ms=prev_c,
            combined_end_ms=c_end,
            source=seg.source,
            source_id=seg.source_id,
            source_start_ms=seg.source_start_ms + int(round((prev_c - c_start) * ratio)),
            source_end_ms=seg.source_end_ms,
        ))
    return out


# 하위 호환 alias — 이전 이름으로 부르는 곳이 있을 수 있어 보존.
_split_main_segments_at_effect_boundaries = _split_segments_at_effect_boundaries


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
