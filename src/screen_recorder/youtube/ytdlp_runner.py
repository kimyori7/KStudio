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


def final_output_path(base_filename: str, mode: str) -> str:
    """다운로드 결과의 최종 경로 — mode 가 결정하는 확장자로 보정.

    video 는 merge_output_format=mp4, mp3 는 FFmpegExtractAudio 라 최종 확장자가
    결정적이다. yt-dlp 의 prepare_filename 은 머지/후처리 *전* 확장자(.webm·.f251 등
    조각 파일)를 줄 수 있으므로 여기서 .mp4/.mp3 로 강제한다.

    한계: 같은 제목을 같은 폴더에 두 번 받으면 yt-dlp 가 ' (1)' 로 dedup 하지만
    이 경로엔 반영되지 않는다(드문 경우 — '열기' 버튼이 옛 파일을 가리킬 수 있음).
    """
    ext = ".mp3" if mode == "mp3" else ".mp4"
    return str(Path(base_filename).with_suffix(ext))


_truststore_injected = False


def _ensure_truststore() -> None:
    """OS(Windows) 인증서 저장소로 TLS 검증 — 사내 프록시(TLS 인터셉트) 환경 대응.

    yt-dlp/certifi 기본 번들엔 사내 루트 CA 가 없어 CERTIFICATE_VERIFY_FAILED 로
    다운로드가 실패한다(실측 2026-06-18, COMPANY 사내망). truststore 는 OS 네이티브
    검증기를 써 Windows 가 신뢰하는 체인(사내 CA 포함)을 그대로 인정한다.
    inject 는 프로세스 전역이라 한 번만 호출하면 되고, 다운로드 경로에서 lazy 로
    호출해 영향 범위를 최소화한다. truststore 미설치/실패해도 일반 네트워크에선
    동작하므로 best-effort.
    """
    global _truststore_injected
    if _truststore_injected:
        return
    _truststore_injected = True
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001
        pass


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
    from yt_dlp.utils import DownloadCancelled

    _ensure_truststore()

    def _check_cancel() -> None:
        # yt-dlp 의 DownloadCancelled 를 던지면 다운로드/후처리가 깔끔히 중단된다
        # (커스텀 예외는 yt-dlp 가 DownloadError 로 감쌀 수 있어 사용하지 않음).
        if cancel_check is not None and cancel_check():
            raise DownloadCancelled()

    def _dl_hook(d: dict) -> None:
        _check_cancel()
        progress_hook(d)

    def _pp_hook(d: dict) -> None:
        # mp3 추출(FFmpegExtractAudio) 등 후처리 단계 — 다운로드 progress_hook 이
        # 안 불리는 구간이라 여기서도 취소를 확인해야 변환 중 취소가 먹는다.
        _check_cancel()

    opts = build_ydl_opts(req, ffmpeg_dir, _dl_hook)
    opts["postprocessor_hooks"] = [_pp_hook]

    final = ""
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            try:
                final = final_output_path(ydl.prepare_filename(info), req.mode)
            except Exception:  # noqa: BLE001
                final = ""
    except DownloadCancelled as exc:
        raise CancelledError() from exc
    return final
