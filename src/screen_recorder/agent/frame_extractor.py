"""ffmpeg 단발 프레임 추출 + 타임라인 strip 합성.

설계 결정 (2026-05-13): PlayerWidget 의 QImage 는 UI 스레드 소유 — 에이전트
worker(asyncio) 스레드에서 호출하려면 마샬링 필요 → 디버깅 지옥. 대신 ffmpeg
subprocess 단발 호출이 thread-safe + 결정론적. 비용 200~500ms/frame.

함수:
- `extract_frame_png(src, ms, ffmpeg) -> bytes` — 한 프레임 PNG.
- `composite_timeline_strip(src, start, end, n, ffmpeg) -> bytes` — 썸네일 strip.

캐시 (2026-05-13): LRU 32 entries — Claude 가 같은 ms 재요청 시 즉시 반환.
key: (src, ms, width). reset_frame_cache() 로 수동 비움.

stderr 는 항상 보존 (CLAUDE.md 정책 — DEVNULL 금지). 실패 시 RuntimeError 에
stderr 본문 포함.
"""
from __future__ import annotations

import io
import logging
import os
import subprocess
import tempfile
import threading
from collections import OrderedDict
from typing import Optional

_log = logging.getLogger(__name__)


# 프레임 캐시 — LRU. key: (src, ms, width), value: PNG bytes.
_FRAME_CACHE_MAX = 32
_frame_cache: "OrderedDict[tuple[str, int, int], bytes]" = OrderedDict()
_frame_cache_lock = threading.Lock()


def reset_frame_cache() -> None:
    """캐시 비우기 — 영상이 바뀌었을 때 호출 가능."""
    with _frame_cache_lock:
        _frame_cache.clear()


def _cache_get(key: tuple[str, int, int]) -> Optional[bytes]:
    with _frame_cache_lock:
        if key in _frame_cache:
            _frame_cache.move_to_end(key)
            return _frame_cache[key]
    return None


def _cache_put(key: tuple[str, int, int], val: bytes) -> None:
    with _frame_cache_lock:
        _frame_cache[key] = val
        _frame_cache.move_to_end(key)
        while len(_frame_cache) > _FRAME_CACHE_MAX:
            _frame_cache.popitem(last=False)


def _format_ts(ms: int) -> str:
    s_total = max(0, ms) // 1000
    if s_total >= 3600:
        return f"{s_total // 3600}:{(s_total % 3600) // 60:02d}:{s_total % 60:02d}"
    return f"{s_total // 60}:{s_total % 60:02d}"


def extract_frame_png(
    src_path: str,
    ms: int,
    ffmpeg_path: str,
    width: int = 320,
    timeout_sec: float = 10.0,
) -> bytes:
    """영상의 ms 시점 한 프레임을 PNG 바이트로 반환. width 로 다운스케일.

    LRU 캐시 — 같은 (src, ms, width) 두 번째 호출은 디스크 액세스 없이 즉시 반환.

    빠른 seek 를 위해 `-ss` 를 `-i` 앞에. -2 는 짝수 보존 (libx264 호환성 제약은
    decoding 에는 무관하나 일관성 유지).
    """
    ms = max(0, int(ms))
    width = int(width)
    cache_key = (str(src_path), ms, width)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    sec = ms / 1000.0
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        cmd = [
            ffmpeg_path,
            "-loglevel", "error",
            "-ss", f"{sec:.3f}",
            "-i", str(src_path),
            "-frames:v", "1",
            "-vf", f"scale={width}:-2",
            "-y", tmp_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_sec)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg frame extract failed (rc={proc.returncode}): {stderr}")
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError("ffmpeg produced empty frame")
        with open(tmp_path, "rb") as f:
            data = f.read()
        _cache_put(cache_key, data)
        return data
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def composite_timeline_strip(
    src_path: str,
    start_ms: int,
    end_ms: int,
    n: int,
    ffmpeg_path: str,
    thumb_width: int = 240,
) -> bytes:
    """[start_ms, end_ms] 범위에 균일 간격 n 프레임을 가로로 합성한 PNG.

    각 썸네일 아래에 타임스탬프 텍스트 라벨. Claude 가 한 장 이미지로 범위
    gestalt 를 파악하는 용도 (~1.5k 토큰).

    PIL/Pillow 사용 — KStudio 가 이미 dep 으로 가지고 있음.
    """
    from PIL import Image, ImageDraw

    if n <= 0:
        raise ValueError("n must be > 0")
    if end_ms <= start_ms:
        # 0폭 범위 — 한 프레임만.
        n = 1

    thumb_h = max(60, thumb_width * 9 // 16)
    gap = 4
    label_h = 18
    strip_w = n * thumb_width + (n - 1) * gap
    strip_h = thumb_h + label_h

    img = Image.new("RGB", (strip_w, strip_h), (10, 15, 30))
    draw = ImageDraw.Draw(img)

    if n == 1:
        timestamps = [(start_ms + end_ms) // 2]
    else:
        step = (end_ms - start_ms) / (n - 1)
        timestamps = [int(start_ms + i * step) for i in range(n)]

    for i, t_ms in enumerate(timestamps):
        x = i * (thumb_width + gap)
        try:
            frame_bytes = extract_frame_png(
                src_path, t_ms, ffmpeg_path, width=thumb_width
            )
            thumb = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
            # ffmpeg 가 -2 로 짝수 height 을 잡아주므로 width 만 thumb_width 일치.
            # 비율 맞추려 crop 또는 resize.
            tw, th = thumb.size
            if th != thumb_h:
                ratio = thumb_h / th
                new_w = int(tw * ratio)
                thumb = thumb.resize((new_w, thumb_h), Image.LANCZOS)
                if thumb.width > thumb_width:
                    left = (thumb.width - thumb_width) // 2
                    thumb = thumb.crop((left, 0, left + thumb_width, thumb_h))
            img.paste(thumb, (x, 0))
            draw.text((x + 4, thumb_h + 2), _format_ts(t_ms), fill=(180, 200, 230))
        except Exception as exc:
            _log.warning("timeline strip: failed to extract frame at %dms: %s", t_ms, exc)
            draw.rectangle([x, 0, x + thumb_width, thumb_h], fill=(40, 40, 50))
            draw.text((x + 6, thumb_h // 2 - 6), "X", fill=(180, 80, 80))
            draw.text((x + 4, thumb_h + 2), _format_ts(t_ms), fill=(120, 140, 160))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
