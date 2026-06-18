"""유튜브 다운로드 end-to-end 실측 — run_download 코드 경로로 mp3 + 480p 영상 받기.

네트워크 필요. 임시 폴더에 받고 결과 파일/크기를 출력한다. 사용자 요청 "테스트해줘".
출력 리다이렉트는 logs/ 로 (개발 스크래치 규약).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.youtube.request import DownloadRequest
from screen_recorder.youtube import ytdlp_runner

# yt-dlp 자체 테스트에 쓰이는 10초짜리 공개 영상.
TEST_URL = "https://www.youtube.com/watch?v=BaW_jenozKc"


def _progress(d: dict) -> None:
    if d.get("status") == "downloading":
        got = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct = (got * 100 // total) if total else 0
        sys.stdout.write(f"\r  {pct:3d}%  {got // 1024}KB")
        sys.stdout.flush()
    elif d.get("status") == "finished":
        sys.stdout.write("\r  post-processing...      \n")


def run_one(mode: str, quality: str, out_dir: Path) -> None:
    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None, "ffmpeg not found"
    req = DownloadRequest(TEST_URL, mode, out_dir, quality)
    print(f"[{mode} / {quality}] downloading -> {out_dir}")
    path = ytdlp_runner.run_download(
        req, ffmpeg_dir=Path(ffmpeg).parent, progress_hook=_progress, cancel_check=None,
    )
    p = Path(path)
    ok = p.exists() and p.stat().st_size > 0
    size = p.stat().st_size if p.exists() else 0
    print(f"  RESULT: exists={p.exists()} size={size} bytes  path={p.name}")
    print(f"  {'PASS' if ok else 'FAIL'}\n")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kstudio_yt_") as tmp:
        out = Path(tmp)
        run_one("mp3", "192", out)
        run_one("video", "480", out)
        print("files in out dir:")
        for f in sorted(out.iterdir()):
            print(f"  {f.name}  ({f.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
