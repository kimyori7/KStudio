"""실제 사이드카 → 진짜 build_export_args → argv 정적 검사 (Test B, 인코딩 없음).
+ 옵션으로 실원본에 돌리며 RSS 곡선 관찰 후 10GB/60s 에서 강제 중단 (Test A).

advisor: 49GB free 는 크래시 '후' 측정이라 무의미 → 점진적 버퍼링이 1순위.
synthetic 말고 실제 사이드카로 진짜 코드경로를 재현해야 한다. argv 의 -itsoffset/-t/
총길이를 눈으로 보면 (B) 병적 값 여부를 즉시 알 수 있고, (A) 실행 RSS 곡선이 t=0
부터 계속 오르면 버퍼링 폭주 확정 — OOM 까지 안 기다려도 된다.

사용:
  python scripts/diagnose_export_real_sidecar.py          # Test B 만 (즉시)
  python scripts/diagnose_export_real_sidecar.py --run    # B + A (실행, 10GB/60s 중단)
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# 캡션 PNG 렌더링이 Qt(QPainter/QFont) 를 쓰므로 offscreen QApplication 필수.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

SRC = Path(r"E:\KStudio_Image\Video\rec_20260609_164813.mp4")

from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects.sidecar_store import SidecarStore, default_sidecar_dir
from screen_recorder.encode.export_pipeline import build_export_args


def _probe_duration_ms(ffmpeg: Path, src: Path) -> int:
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe")
    if not ffprobe.exists():
        ffprobe = Path(ffmpeg).with_name("ffprobe")
    r = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(src)],
        capture_output=True, text=True,
    )
    dur = float(json.loads(r.stdout or "{}").get("format", {}).get("duration", 0) or 0)
    return int(dur * 1000)


def _group_inputs(argv: list[str]) -> list[dict]:
    """argv 를 input 블록으로 분해 — 각 -i 와 그 앞 옵션(-itsoffset/-t/-loop 등)."""
    inputs = []
    cur: dict = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "-filter_complex":
            i += 2
            continue
        if a in ("-itsoffset", "-t", "-framerate", "-loop", "-ss", "-to"):
            cur[a] = argv[i + 1]
            i += 2
            continue
        if a == "-i":
            cur["path"] = argv[i + 1]
            inputs.append(cur)
            cur = {}
            i += 2
            continue
        i += 1
    return inputs


def main() -> int:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        print("ffmpeg 없음"); return 1
    if not SRC.exists():
        print(f"원본 없음: {SRC}"); return 1

    # 실제 사이드카 폴더는 설정에서 지정한 커스텀(E:) — 기본(APPDATA)엔 옛것만 있음.
    candidate_dirs = [
        Path(r"E:\KStudio_Image\Video\sidecars"),
        default_sidecar_dir(),
    ]
    sidecar = None
    for d in candidate_dirs:
        sc = SidecarStore(d).load_for(SRC)
        if sc is not None:
            sidecar = sc
            print(f"사이드카 폴더: {d}")
            break
    if sidecar is None:
        print(f"사이드카 없음 (탐색: {candidate_dirs})"); return 1

    dur_ms = _probe_duration_ms(ffmpeg, SRC)
    print(f"원본: {SRC.name}  duration={dur_ms}ms ({dur_ms/1000:.1f}s)")
    print(f"effects: {[type(e).__name__ for e in sidecar.effects]}")
    print(f"effects_active: {[type(e).__name__ for e in sidecar.active_effects()]}")
    print(f"video_track segs: {len(sidecar.video_track)}")

    # 실제 surface = 영상 해상도
    from screen_recorder.services.media_probe import probe_video_size
    primary = sidecar.video_track[0].src if sidecar.video_track else str(SRC)
    sw, sh = probe_video_size(primary)
    print(f"surface: {sw}x{sh}")

    out = Path(tempfile.mkdtemp(prefix="exparg_")) / "out.mp4"
    argv, pngs = build_export_args(
        sidecar=sidecar, src_path=SRC, dst_path=out,
        main_duration_ms=dur_ms, surface_w=sw, surface_h=sh, ffmpeg_path=ffmpeg,
    )

    # combined timeline 총길이 (progress 분모 = 출력 영상 길이)
    from screen_recorder.effects.timeline import build_combined_timeline
    from screen_recorder.effects.types.cut import CutEffect
    cuts = [e for e in sidecar.effects if isinstance(e, CutEffect)]
    segs = build_combined_timeline(dur_ms, cuts)
    total_out_ms = segs[-1].combined_end_ms if segs else dur_ms
    total_out_s = total_out_ms / 1000.0
    print(f"\n총 출력 길이(combined): {total_out_ms}ms ({total_out_s:.1f}s)")

    print("\n===== INPUT 블록 ({}개) =====".format(len(_group_inputs(argv))))
    seen_paths: dict[str, int] = {}
    flags = []
    for idx, blk in enumerate(_group_inputs(argv)):
        p = blk.get("path", "?")
        name = Path(p).name if p != "?" else "?"
        its = blk.get("-itsoffset")
        t = blk.get("-t")
        loop = blk.get("-loop")
        print(f"  [{idx}] {name:50} loop={loop} itsoffset={its} t={t}")
        # 병적 값 플래그
        if its is not None:
            itsf = float(its)
            if itsf < 0:
                flags.append(f"[{idx}] itsoffset 음수: {its}")
            if itsf >= total_out_s:
                flags.append(f"[{idx}] itsoffset({its}) >= 총길이({total_out_s:.1f}) — 영원히 등장 안 함 + framesync 대기 위험")
        if t is not None:
            tf = float(t)
            if tf > total_out_s * 1.5:
                flags.append(f"[{idx}] -t({t}) 가 총길이보다 큼 — 과다 loop")
            if tf <= 0:
                flags.append(f"[{idx}] -t({t}) <= 0")
        if p != "?":
            seen_paths[p] = seen_paths.get(p, 0) + 1

    dups = {p: n for p, n in seen_paths.items() if n > 1}
    if dups:
        for p, n in dups.items():
            flags.append(f"중복 입력 {n}회: {Path(p).name}")

    # filter_complex 추출
    fc = ""
    for i, a in enumerate(argv):
        if a == "-filter_complex":
            fc = argv[i + 1]
            break
    print(f"\n===== filter_complex (길이 {len(fc)}자) =====")
    for part in fc.split(";"):
        print("  " + part)

    print("\n===== 병적 값 플래그 =====")
    if flags:
        for f in flags:
            print("  ⚠ " + f)
    else:
        print("  (없음 — 값은 정상. 버퍼링은 그래프 구조/규모 문제일 가능성)")

    # ---- Test A: 실행 + RSS 곡선, 10GB/60s 중단 ----
    if "--run" in sys.argv:
        print("\n===== Test A: 실행하며 RSS 추적 (10GB 또는 60s 에서 중단) =====")
        import re, psutil
        frame_re = re.compile(rb"frame=\s*(\d+)")
        argv_run = list(argv)
        proc = subprocess.Popen(argv_run, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        ps = psutil.Process(proc.pid)
        t0 = time.monotonic()
        last_frame = [0]
        stop = threading.Event()
        killed = ["완료"]

        def reader():
            assert proc.stderr is not None
            for raw in proc.stderr:
                m = frame_re.search(raw)
                if m:
                    last_frame[0] = int(m.group(1))
        rt = threading.Thread(target=reader, daemon=True); rt.start()

        while proc.poll() is None:
            try:
                rss = ps.memory_info().rss
                for c in ps.children(recursive=True):
                    try: rss += c.memory_info().rss
                    except psutil.Error: pass
            except psutil.Error:
                break
            el = time.monotonic() - t0
            print(f"  t={el:4.1f}s  RSS={rss/1e9:5.2f}GB  frame={last_frame[0]}")
            if rss > 10e9:
                killed[0] = "10GB 초과 → 강제 종료"; proc.kill(); break
            if el > 60:
                killed[0] = "60s 초과 → 강제 종료"; proc.kill(); break
            time.sleep(2.0)
        stop.set()
        print(f"  결과: {killed[0]}  (마지막 frame={last_frame[0]})")
        print("  해석: RSS 가 t=0 부터 계속 우상향 + frame 정체 = 버퍼링 폭주 확정.")

    # 정리 — build 가 만든 캡션 PNG 삭제
    for p in pngs:
        try: Path(p).unlink(missing_ok=True)
        except OSError: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
