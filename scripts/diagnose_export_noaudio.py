"""discriminator 3: 캡션+긴본영상 OOM 이 '오디오 muxing' 때문인가?

short-main(오디오X)+캡션6 = bounded 였다. 실제 케이스는 오디오 concat a=1 + 캡션 →
OOM. 차이가 오디오일 수 있다(video 가 audio 기다리며 mux 큐 폭증 → frame=0).

has_audio_stream 을 False 로 패치해 실제 사이드카(캡션 유지)를 '오디오 없이' 빌드 →
실원본 실행 RSS. bounded → 오디오/비디오 sync·mux 가 레버(한 줄 수정 가능).
OOM → 순수 video overlay+긴 decode (2단계 렌더 필요).
"""
from __future__ import annotations
import copy, os, re, subprocess, sys, tempfile, threading, time, json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

SRC = Path(r"E:\KStudio_Image\Video\rec_20260609_164813.mp4")
from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects.sidecar_store import SidecarStore
from screen_recorder.encode import export_pipeline as ep
from screen_recorder.services import media_probe
from screen_recorder.services.media_probe import probe_video_size

_FRAME_RE = re.compile(rb"frame=\s*(\d+)")


def _run(argv, abort_gb=8.0, abort_s=40.0):
    import psutil
    proc=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    ps=psutil.Process(proc.pid); t0=time.monotonic()
    peak=[0.0]; last=[0]; verdict=["완료"]; samples=[]
    def reader():
        for raw in proc.stderr:
            m=_FRAME_RE.search(raw)
            if m: last[0]=int(m.group(1))
    threading.Thread(target=reader,daemon=True).start()
    while proc.poll() is None:
        try:
            rss=ps.memory_info().rss
            for c in ps.children(recursive=True):
                try: rss+=c.memory_info().rss
                except psutil.Error: pass
            peak[0]=max(peak[0],rss)
        except psutil.Error: break
        el=time.monotonic()-t0
        samples.append((round(el,1),round(rss/1e9,2),last[0]))
        if rss>abort_gb*1e9: verdict[0]="8GB중단"; proc.kill(); break
        if el>abort_s: verdict[0]="40s중단"; proc.kill(); break
        time.sleep(2.0)
    return round(peak[0]/1e9,2),last[0],verdict[0],samples


def main():
    ffmpeg=find_ffmpeg()
    sidecar=SidecarStore(Path(r"E:\KStudio_Image\Video\sidecars")).load_for(SRC)
    ffprobe=Path(ffmpeg).with_name("ffprobe.exe")
    r=subprocess.run([str(ffprobe),"-v","error","-show_entries","format=duration",
                      "-of","json",str(SRC)],capture_output=True,text=True)
    dur=int(float(json.loads(r.stdout or "{}").get("format",{}).get("duration",0) or 0)*1000)
    sw,sh=probe_video_size(str(SRC))

    # 오디오 없음으로 강제 — build_export_args 가 audio chain 전체 우회.
    media_probe.has_audio_stream = lambda s: False

    out=Path(tempfile.mkdtemp(prefix="noaud_"))/"out.mp4"
    argv,pngs=ep.build_export_args(sidecar=copy.deepcopy(sidecar),src_path=SRC,dst_path=out,
        main_duration_ms=dur,surface_w=sw,surface_h=sh,ffmpeg_path=ffmpeg)
    has_a = any(a=="-map" for a in argv) and ("concat=n=3:v=1:a=1" in " ".join(argv))
    print(f"audio chain 포함? {'concat...a=1' in ' '.join(argv)} (False 여야 정상 패치)")
    print("실제 사이드카(캡션6 유지) + 오디오 강제 OFF, 실원본:")
    peak,frame,v,samples=_run(argv)
    for el,gb,fr in samples: print(f"  t={el:4.1f}s RSS={gb:5.2f}GB frame={fr}")
    print(f"  => peak={peak}GB frame={frame} {v}")
    print(f"\n비교: full(오디오ON)=9.3GB폭증.  이번 bounded → 오디오 mux 가 레버.")
    for p in pngs:
        try: Path(p).unlink(missing_ok=True)
        except OSError: pass
    return 0


if __name__=="__main__":
    sys.exit(main())
