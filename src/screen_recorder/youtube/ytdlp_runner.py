"""yt-dlp 옵션 구성(순수) + 실행 래퍼.

build_ydl_opts 는 yt_dlp 를 import 하지 않는다 — 순수 dict 만 만들어
yt-dlp 미설치 환경에서도 단위 테스트가 가능하다. run_download 만 lazy import.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from .request import DownloadRequest

_log = logging.getLogger(__name__)

# 영상 화질 → yt-dlp format selector. height 상한으로 해상도 제한, 합치기는 mp4.
_VIDEO_FORMAT = {
    "best": "bestvideo+bestaudio/best",
    "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480": "bestvideo[height<=480]+bestaudio/best[height<=480]",
}


def build_ydl_opts(
    req: DownloadRequest,
    ffmpeg_dir: Path,
    progress_hook: Callable[[dict], None],
) -> dict:
    """yt-dlp YoutubeDL 옵션 사전을 구성한다 (순수, 다운로드 없음)."""
    opts: dict = {
        # 재생목록(&list=) 이 섞여도 영상 1개만.
        "noplaylist": True,
        "outtmpl": str(req.out_dir / "%(title)s.%(ext)s"),
        # 동봉 ffmpeg 를 명시 — PATH 자동 탐색에 의존하지 않는다.
        "ffmpeg_location": str(ffmpeg_dir),
        "progress_hooks": [progress_hook],
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if req.mode == "video":
        opts["format"] = _VIDEO_FORMAT.get(req.quality, _VIDEO_FORMAT["best"])
        opts["merge_output_format"] = "mp4"
    else:  # mp3
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": req.quality,
        }]
    return opts


class CancelledError(Exception):
    """사용자 취소로 다운로드 중단."""


def run_download(
    req: DownloadRequest,
    ffmpeg_dir: Path,
    progress_hook: Callable[[dict], None],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """yt-dlp 다운로드 실행. 최종 파일 경로(str)를 반환. 취소 시 CancelledError.

    cancel_check 가 참이면 다음 progress 콜백에서 CancelledError 를 던져 중단한다
    (yt-dlp 는 별도 취소 API 가 없어 hook 예외로 중단하는 게 표준).
    """
    import yt_dlp  # lazy import — 미설치 환경에서도 build_ydl_opts 테스트는 가능

    final_path: dict = {"path": ""}

    def _hook(d: dict) -> None:
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        if d.get("status") == "finished":
            final_path["path"] = d.get("filename", "") or final_path["path"]
        progress_hook(d)

    opts = build_ydl_opts(req, ffmpeg_dir, _hook)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(req.url, download=True)
        # mp3 후처리 시 실제 확장자는 .mp3, video 머지는 .mp4 — prepare_filename 으로 보정.
        try:
            base = ydl.prepare_filename(info)
            if req.mode == "mp3":
                final_path["path"] = str(Path(base).with_suffix(".mp3"))
            elif not final_path["path"]:
                final_path["path"] = str(Path(base).with_suffix(".mp4"))
        except Exception:  # noqa: BLE001
            pass
    return final_path["path"]
