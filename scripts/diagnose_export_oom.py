"""export OOM 메커니즘 분리 검증 (실 ffmpeg, 짧은 합성 영상).

사고: 28분 영상 + 컷3 + 전체화면 자막7 export 가 frame=0 인 채 4분 버퍼링하다
'-12 Cannot allocate memory' 로 죽음. 49GB free 였는데도 OOM.

frame=0 이 처음부터 끝까지였다는 게 핵심 — concat/cut 이 범인이면 첫 세그먼트
프레임은 흘러나와야(frame 증가) 한다. 출력이 0 에서 못 나갔다 = 자막 overlay 가
'미래 시점 secondary(-itsoffset)'를 기다리며 본영상을 통째로 버퍼링하는 패턴 의심.

이 스크립트는 짧은 합성 영상으로 메커니즘만 분리한다. 한 변수씩(Phase 3):
  V1 caption-current : -itsoffset <late> 로 늦게 시작하는 caption overlay (현재 코드 패턴)
  V2 caption-fixed   : -itsoffset 없이 전체 구간 loop + fade/enable (수정안)
  V3 cuts-only       : trim×3 → concat, 자막 없음 (mechanism A 단독 검사)

각 변종: 자식 ffmpeg RSS 를 0.5s 마다 샘플 → peak. stderr 의 frame= 진행 파싱 →
2초 시점 frame, 최종 frame, exit code, 경과. frame 이 2초에도 0 이고 mem 이
치솟으면 = 그 변종이 버퍼링 폭주.
"""
from __future__ import annotations
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

FFMPEG = r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.EXE"

# 빠른 1차 검증용. 실패 시 res/dur 키워 OOM 재현.
W, H = 1280, 720
SRC_DUR = 40           # 합성 원본 길이(초)
CAP_IN = 34            # 자막 등장 시점(초) — 늦을수록 버퍼링 폭주가 커짐
CAP_DUR = 4

_FRAME_RE = re.compile(rb"frame=\s*(\d+)")


def _make_assets(d: Path) -> tuple[Path, Path]:
    src = d / "src.mp4"
    cap = d / "cap.png"
    # 합성 원본 — ultrafast 로 빨리.
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi",
         "-i", f"testsrc=size={W}x{H}:rate=30:duration={SRC_DUR}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)],
        check=True, capture_output=True,
    )
    # 투명 배경 + 노란 박스 자막 PNG (rgba).
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi",
         "-i", f"color=c=black@0.0:s={W}x{H},format=rgba,"
               f"drawbox=x=80:y=80:w=520:h=140:color=yellow@1.0:t=fill",
         "-frames:v", "1", str(cap)],
        check=True, capture_output=True,
    )
    return src, cap


def _run(argv: list[str], label: str) -> dict:
    """ffmpeg 실행하며 자식 RSS peak + frame 진행 추적."""
    t0 = time.monotonic()
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    ps = psutil.Process(proc.pid)

    peak_mb = [0.0]
    frame_at_2s = [None]
    last_frame = [0]
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            try:
                rss = ps.memory_info().rss
                for c in ps.children(recursive=True):
                    try:
                        rss += c.memory_info().rss
                    except psutil.Error:
                        pass
                peak_mb[0] = max(peak_mb[0], rss / 1e6)
            except psutil.Error:
                break
            if frame_at_2s[0] is None and time.monotonic() - t0 >= 2.0:
                frame_at_2s[0] = last_frame[0]
            time.sleep(0.3)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()

    assert proc.stderr is not None
    for raw in proc.stderr:
        m = _FRAME_RE.search(raw)
        if m:
            last_frame[0] = int(m.group(1))
    rc = proc.wait()
    stop.set()
    th.join(timeout=1)
    if frame_at_2s[0] is None:
        frame_at_2s[0] = last_frame[0]
    return {
        "label": label,
        "rc": rc,
        "peak_mb": round(peak_mb[0]),
        "frame_2s": frame_at_2s[0],
        "final_frame": last_frame[0],
        "elapsed": round(time.monotonic() - t0, 1),
    }


def main() -> int:
    d = Path(tempfile.mkdtemp(prefix="oomdiag_"))
    print(f"작업 폴더: {d}")
    src, cap = _make_assets(d)
    out = d / "out.mp4"

    def base_out():
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                "-f", "null", "-"]   # 디스크 안 쓰고 인코드 경로만

    # V1 caption-current: -itsoffset <late> 로 늦게 시작하는 secondary (현재 코드)
    v1 = [FFMPEG, "-y",
          "-i", str(src),
          "-loop", "1", "-framerate", "30", "-t", str(CAP_DUR),
          "-itsoffset", str(CAP_IN), "-i", str(cap),
          "-filter_complex",
          f"[1:v]format=rgba,fade=t=in:st={CAP_IN}:d=0.3:alpha=1[capf];"
          f"[0:v][capf]overlay=enable='between(t\\,{CAP_IN}\\,{CAP_IN+CAP_DUR})'[v]",
          "-map", "[v]"] + base_out()

    # V2 caption-fixed: itsoffset 없이 전체 구간 loop, fade st 로 타이밍 제어
    v2 = [FFMPEG, "-y",
          "-i", str(src),
          "-loop", "1", "-framerate", "30", "-t", str(SRC_DUR), "-i", str(cap),
          "-filter_complex",
          f"[1:v]format=rgba,fade=t=in:st={CAP_IN}:d=0.3:alpha=1,"
          f"fade=t=out:st={CAP_IN+CAP_DUR-0.3}:d=0.3:alpha=1[capf];"
          f"[0:v][capf]overlay=enable='between(t\\,{CAP_IN}\\,{CAP_IN+CAP_DUR})'[v]",
          "-map", "[v]"] + base_out()

    # V3 cuts-only: trim×3 → concat, 자막 없음 (mechanism A 단독)
    third = SRC_DUR / 3.0
    v3 = [FFMPEG, "-y", "-i", str(src),
          "-filter_complex",
          f"[0:v]trim=0:{third:.2f},setpts=PTS-STARTPTS,format=yuv420p,setsar=1[a];"
          f"[0:v]trim={third:.2f}:{2*third:.2f},setpts=PTS-STARTPTS,format=yuv420p,setsar=1[b];"
          f"[0:v]trim={2*third:.2f}:{SRC_DUR},setpts=PTS-STARTPTS,format=yuv420p,setsar=1[c];"
          f"[a][b][c]concat=n=3:v=1:a=0[v]",
          "-map", "[v]"] + base_out()

    rows = []
    for argv, label in [(v1, "V1 caption-current(-itsoffset)"),
                        (v2, "V2 caption-fixed(full loop)"),
                        (v3, "V3 cuts-only(trim+concat)")]:
        print(f"\n>>> {label} 실행...")
        r = _run(argv, label)
        print(f"    rc={r['rc']} peak={r['peak_mb']}MB frame@2s={r['frame_2s']} "
              f"final={r['final_frame']} elapsed={r['elapsed']}s")
        rows.append(r)

    print("\n================ 요약 ================")
    print(f"{'변종':38} {'rc':>3} {'peak(MB)':>9} {'frame@2s':>9} {'final':>7} {'elapsed':>8}")
    for r in rows:
        print(f"{r['label']:38} {r['rc']:>3} {r['peak_mb']:>9} "
              f"{str(r['frame_2s']):>9} {r['final_frame']:>7} {r['elapsed']:>7}s")
    print("\n해석: frame@2s 가 0 이고 peak 가 치솟는 변종 = 본영상 버퍼링 폭주(범인).")
    print("      frame@2s 가 크면서 peak 가 낮은 변종 = 정상 스트리밍.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
