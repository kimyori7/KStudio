"""실파일 end-to-end: mp4 오디오 추출 → 앞/뒤 트림 + 중간 컷 → mp3 내보내기 검증.

AudioTab 의 실제 코드 경로(_on_duration/_on_trim_changed/_on_cuts_changed)로 사이드카를
만들고, main_window._on_export_audio 가 쓰는 것과 동일한 compute_audio_keep_intervals +
build_audio_export_args + ffmpeg 으로 출력해, ffprobe 로 길이를 검증한다.

출력: logs/ (mp3 + 로그). 사용자 settings 안 건드리도록 KSTUDIO_SETTINGS_DIR=temp.
"""
from __future__ import annotations
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("KSTUDIO_SETTINGS_DIR", tempfile.mkdtemp(prefix="kstudio_diag_"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.core.ffmpeg_check import find_ffmpeg  # noqa: E402
from screen_recorder.services.media_probe import _find_ffprobe  # noqa: E402
from screen_recorder.core.settings import PlayerSettings  # noqa: E402
from screen_recorder.ui.audio_tab import AudioTab  # noqa: E402
from screen_recorder.encode.audio_export import (  # noqa: E402
    AudioExportSettings, compute_audio_keep_intervals, build_audio_export_args,
)

SRC_MP4 = r"E:\KStudio_Image\Video\rec_20260601_163650.mp4"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _probe_ms(ffprobe: str, path: str) -> int:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    try:
        return int(round(float(out.stdout.decode().strip()) * 1000))
    except (ValueError, AttributeError):
        return 0


def _has_audio(ffprobe: str, path: str) -> bool:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    return bool(out.stdout.decode().strip())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    ff = find_ffmpeg()
    if not ff:
        print("FAIL: ffmpeg 못 찾음"); return 1
    ff = str(ff)
    ffprobe = _find_ffprobe()

    if not os.path.exists(SRC_MP4):
        print(f"FAIL: 원본 없음 {SRC_MP4}"); return 1
    print(f"원본 mp4: {SRC_MP4}")
    print(f"  오디오 스트림: {_has_audio(ffprobe, SRC_MP4)}")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(out_dir, exist_ok=True)

    # 1) 오디오만 추출 (사용자 '오디오만 빼서' — 자르기 대상 audio 파일 생성).
    extracted = os.path.join(out_dir, "diag_extracted.mp3")
    rc = subprocess.run(
        [ff, "-y", "-i", SRC_MP4, "-vn", "-c:a", "libmp3lame", "-b:a", "192k", extracted],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    if rc.returncode != 0:
        print("FAIL: 오디오 추출 실패\n" + rc.stderr.decode("utf-8", "replace")[-400:])
        return 1
    dur = _probe_ms(ffprobe, extracted)
    print(f"추출 mp3: {extracted}  (길이 {dur} ms = {dur/1000:.1f}s)")
    if dur < 8000:
        print("WARN: 원본이 너무 짧아 8s 미만 — 컷 값 축소")

    # 2) AudioTab 실제 경로로 사이드카 구성: 앞 트림 1s, 뒤 트림 1s, 중간 컷 0.5s.
    front = 1000
    back = 1000
    mid = dur // 2
    cut = (max(front, mid - 250), min(dur - back, mid + 250))
    tab = AudioTab(path=extracted, player_settings=PlayerSettings(),
                   sidecar_dir=tempfile.mkdtemp(prefix="diag_sc_"))
    tab._on_duration(dur)                      # src_duration 채움(player 로드 모사)
    tab._on_trim_changed(front, dur - back)    # 앞/뒤 트림
    tab._on_cuts_changed([cut])                # 중간 컷
    sc = tab._edit_controller.sidecar()
    seg = sc.video_track[0]
    cuts = [(e.in_ms, e.out_ms) for e in sc.effects if e.type == "cut"]
    print(f"사이드카: src_in={seg.src_in_ms} src_out={seg.src_out_ms} cuts={cuts}")

    # 3) main_window._on_export_audio 와 동일한 export 계산 + 실행.
    audio_src, keep = compute_audio_keep_intervals(sc)
    expected = sum(e - s for s, e in keep)
    print(f"keep 구간: {keep}  → 기대 길이 {expected} ms = {expected/1000:.1f}s")
    out_mp3 = os.path.join(out_dir, "diag_trimmed.mp3")
    argv = build_audio_export_args(
        src_path=str(audio_src), keep_intervals=keep,
        settings=AudioExportSettings(format="mp3", channels=2, sample_rate=44100,
                                     mp3_bitrate=192),
        dst_path=out_mp3, ffmpeg_path=ff)
    print("ffmpeg argv:\n  " + " ".join(argv))
    rc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=_NO_WINDOW)
    if rc.returncode != 0:
        print("FAIL: 내보내기 ffmpeg 실패\n" + rc.stderr.decode("utf-8", "replace")[-600:])
        return 1

    # 4) 검증.
    got = _probe_ms(ffprobe, out_mp3)
    diff = abs(got - expected)
    print(f"\n결과 mp3: {out_mp3}")
    print(f"  실제 길이 {got} ms = {got/1000:.1f}s / 기대 {expected/1000:.1f}s / 오차 {diff} ms")
    ok = os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1000 and diff <= 600
    print("\n" + ("PASS ✅ 앞/뒤 트림 + 중간 컷이 반영된 mp3 정상 생성"
                  if ok else "FAIL ❌ 길이 불일치 또는 결과 비정상"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
