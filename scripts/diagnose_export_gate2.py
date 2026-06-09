"""Gate 2: 실제 사이드카 export 를 완주시키고 결과가 맞는지 검증.

RSS bounded(gate1)만으론 부족 — 완주 + 캡션 위치 + 오디오 + 길이 확인 필요.
실 build_export_args(수정본) → 실원본 완주 → ffprobe(스트림/길이) + 캡션 구간 프레임
추출(PNG) 로 캡션이 화면 맞는 위치에 떴는지 눈으로 검증.
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, time, json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

SRC = Path(r"E:\KStudio_Image\Video\rec_20260609_164813.mp4")
from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects.sidecar_store import SidecarStore
from screen_recorder.encode import export_pipeline as ep
from screen_recorder.services.media_probe import probe_video_size


def main():
    ffmpeg = find_ffmpeg()
    sidecar = SidecarStore(Path(r"E:\KStudio_Image\Video\sidecars")).load_for(SRC)
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe")
    r = subprocess.run([str(ffprobe),"-v","error","-show_entries","format=duration",
                        "-of","json",str(SRC)],capture_output=True,text=True)
    dur = int(float(json.loads(r.stdout or "{}").get("format",{}).get("duration",0) or 0)*1000)
    sw, sh = probe_video_size(str(SRC))

    out_dir = Path(tempfile.mkdtemp(prefix="gate2_"))
    out = out_dir / "rec_edited.mp4"
    argv, pngs = ep.build_export_args(sidecar=sidecar, src_path=SRC, dst_path=out,
        main_duration_ms=dur, surface_w=sw, surface_h=sh, ffmpeg_path=ffmpeg)

    print(f"출력: {out}")
    print("완주 인코딩 중... (29분 디코딩, 수 분 소요)")
    t0 = time.monotonic()
    proc = subprocess.run(argv, capture_output=True, timeout=900)
    el = time.monotonic() - t0
    print(f"ffmpeg 종료 rc={proc.returncode}  경과={el:.0f}s")
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8","replace").splitlines()[-15:]
        print("STDERR tail:"); print("\n".join(tail))
        return 1
    if not out.exists():
        print("FAIL: 출력 파일 없음"); return 1

    # ffprobe — 스트림/길이
    r = subprocess.run([str(ffprobe),"-v","error","-print_format","json",
                        "-show_format","-show_streams",str(out)],capture_output=True,text=True)
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams",[])
    v = [s for s in streams if s.get("codec_type")=="video"]
    a = [s for s in streams if s.get("codec_type")=="audio"]
    odur = float(info.get("format",{}).get("duration",0) or 0)
    size = out.stat().st_size
    print(f"\n결과 mp4: {size}B  duration={odur:.1f}s")
    print(f"  video streams={len(v)}  audio streams={len(a)}")
    if v: print(f"  video: {v[0].get('width')}x{v[0].get('height')} {v[0].get('codec_name')}")
    if a: print(f"  audio: {a[0].get('codec_name')} {a[0].get('sample_rate')}Hz ch={a[0].get('channels')}")

    # 캡션 구간 프레임 추출 (출력 시간 기준) — cap0~2s, cap4~22s, cap6~70s
    for ts in (2.0, 22.0, 70.0):
        if ts > odur: continue
        fp = out_dir / f"frame_{int(ts)}s.png"
        subprocess.run([ffmpeg,"-y","-ss",f"{ts}","-i",str(out),"-frames:v","1",str(fp)],
                       capture_output=True)
        print(f"  프레임 추출 t={ts}s → {fp}")

    ok = len(v)==1 and len(a)==1 and odur>0
    print(f"\n=== Gate2: {'PASS — 완주+영상+오디오 정상' if ok else 'FAIL'} ===")
    print(f"프레임 PNG 폴더: {out_dir}")
    for p in pngs:
        try: Path(p).unlink(missing_ok=True)
        except OSError: pass
    return 0 if ok else 1


if __name__=="__main__":
    sys.exit(main())
