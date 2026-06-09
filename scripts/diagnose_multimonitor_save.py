"""멀티모니터 합성 영역을 실제 RecorderController 로 녹화 → mp4 저장 검증 (실하드웨어).

advisor 지적: 합성 프레임이 '큐까지'는 맞게 나오는 걸 봤지만, 실제 인코더→ffmpeg→mp4
경로는 안 거쳤다. 원래 사고 증상이 바로 '저장 안 됨(스트림 없는 깡통 mp4)'이므로, 단일/
멀티 무관하게 진짜 mp4 가 나오는지 ffprobe 로 확정한다.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 사용자 settings 보호 (dev 실행이 settings 덮어쓰는 사고 방지).
os.environ["KSTUDIO_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="ksdiag_")

from screen_recorder.core.settings import AppSettings
from screen_recorder.core.controller import RecorderController
from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.capture.targets import RegionTarget, Rect
from screen_recorder.capture.video import resolve_output_rects, plan_capture_tiles


def main() -> int:
    outs = resolve_output_rects()
    if len(outs) < 2:
        print("SKIP: 모니터 2개 미만")
        return 1
    a, b = outs[0], outs[1]
    seam = a.right
    rect = Rect(seam - 600, 300, 1200, 600)  # 이음매 가로지름, 짝수
    tiles = plan_capture_tiles(rect, outs)
    print(f"rect={rect} tiles={len(tiles)} (>=2 여야 multi 경로)")
    if len(tiles) != 2:
        print("SKIP: 2-tile 안 나옴")
        return 1

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        print("SKIP: ffmpeg 없음")
        return 1

    out_dir = Path(tempfile.mkdtemp(prefix="ksrec_"))
    settings = AppSettings()
    settings.general.output_dir = str(out_dir)
    settings.general.mode = "video"
    settings.sound.system_audio_enabled = False  # 비디오 경로만 검증
    settings.video.fps = 30

    ctrl = RecorderController(settings=settings, ffmpeg_path=ffmpeg)
    saved: list[str] = []
    errors: list[str] = []
    ctrl.recording_finished.connect(lambda p: saved.append(p))
    ctrl.error_occurred.connect(lambda e: errors.append(e))

    print("녹화 시작 (multi 합성 경로)...")
    ctrl.start_recording(RegionTarget(rect))
    time.sleep(1.2)
    ctrl.stop_recording()

    # finalize(인코더 join + mp4 마무리)까지 대기 — Qt 이벤트루프 없이 플래그 폴링.
    for _ in range(600):  # 최대 ~60s
        if not ctrl.is_finalizing():
            break
        time.sleep(0.1)

    if errors:
        print("error_occurred:", errors)
    # 출력 파일 찾기
    mp4s = list(out_dir.glob("*.mp4"))
    print("저장 후보:", [p.name for p in mp4s], "| recording_finished:", saved)
    if not mp4s:
        print("FAIL: mp4 가 저장되지 않음")
        return 1
    out = mp4s[0]
    size = out.stat().st_size
    print(f"파일: {out.name} size={size}B")

    # ffprobe 로 스트림/해상도/길이 확인
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe")
    if not ffprobe.exists():
        ffprobe = Path(ffmpeg).with_name("ffprobe")
    try:
        r = subprocess.run(
            [str(ffprobe), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(out)],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(r.stdout or "{}")
    except Exception as e:
        print(f"ffprobe 실패({e}) — 파일 크기로만 판정: {'PASS' if size > 1000 else 'FAIL'}")
        return 0 if size > 1000 else 1

    streams = info.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    print(f"nb_streams={len(streams)} video_streams={len(vstreams)}")
    if not vstreams:
        print("FAIL: 비디오 스트림 없음 (깡통 mp4!)")
        return 1
    v = vstreams[0]
    w, h = v.get("width"), v.get("height")
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    print(f"video: {w}x{h} codec={v.get('codec_name')} duration={dur:.2f}s")
    ok = (w == rect.w and h == rect.h and dur > 0)
    print("\n=== 결과:", "PASS - 합성 영역이 정상 mp4 로 저장됨 ===" if ok
          else "FAIL - 해상도/길이 불일치 ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
