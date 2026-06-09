"""discriminator 2: -itsoffset(캡션 늦은 시작)가 본영상 버퍼링의 레버인가?

tinycap(작은 캡션 + 현행 -itsoffset) = 8.09GB 폭증 이미 측정. 여기선 캡션 입력에서
-itsoffset 을 제거하고 전체 구간 span(-t 큰 값) 으로 바꿔 재측정. fade/enable 은 이미
절대 output 시간을 쓰므로 타이밍은 보존. 캡션도 작게(64x64) — 캡션 픽셀 영향 배제.

bounded(<3GB) → itsoffset 늦은 시작이 framesync 본영상 버퍼링의 레버 → fix = 캡션
입력에서 itsoffset 빼고 전체 구간 loop.
"""
from __future__ import annotations
import copy, os, re, subprocess, sys, tempfile, threading, time, json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
_app = QApplication.instance() or QApplication([])

SRC = Path(r"E:\KStudio_Image\Video\rec_20260609_164813.mp4")
from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects.sidecar_store import SidecarStore
from screen_recorder.encode import export_pipeline as ep
from screen_recorder.services.media_probe import probe_video_size

_FRAME_RE = re.compile(rb"frame=\s*(\d+)")


def _run(argv, abort_gb=8.0, abort_s=30.0):
    import psutil
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    ps = psutil.Process(proc.pid); t0 = time.monotonic()
    peak=[0.0]; last=[0]; verdict=["완료"]; samples=[]
    def reader():
        for raw in proc.stderr:
            m=_FRAME_RE.search(raw)
            if m: last[0]=int(m.group(1))
    threading.Thread(target=reader, daemon=True).start()
    while proc.poll() is None:
        try:
            rss=ps.memory_info().rss
            for c in ps.children(recursive=True):
                try: rss+=c.memory_info().rss
                except psutil.Error: pass
            peak[0]=max(peak[0],rss)
        except psutil.Error: break
        el=time.monotonic()-t0
        samples.append((round(el,1), round(rss/1e9,2), last[0]))
        if rss>abort_gb*1e9: verdict[0]="8GB중단"; proc.kill(); break
        if el>abort_s: verdict[0]="30s중단"; proc.kill(); break
        time.sleep(1.0)
    return round(peak[0]/1e9,2), last[0], verdict[0], samples


def rewrite_caption_inputs_no_offset(argv, total_s):
    """argv 의 캡션 입력 블록(-loop 1 ... -itsoffset X ... -i caption_*.png)을
    -loop 1 -framerate 30 -t total_s -i caption.png (itsoffset 제거) 로 교체."""
    out=[]; i=0
    while i < len(argv):
        if argv[i]=="-loop":
            # 입력 블록 수집: -i <path> 까지
            j=i; blk={}
            while j < len(argv) and argv[j] != "-i":
                if argv[j] in ("-loop","-framerate","-t","-itsoffset"):
                    blk[argv[j]]=argv[j+1]; j+=2
                else: j+=1
            path=argv[j+1]; j+=2
            if "caption_" in Path(path).name:
                out += ["-loop","1","-framerate","30","-t",f"{total_s:.3f}","-i",path]
            else:
                # 원래대로 (arrow/hud) — 블록 그대로 복원
                seg=["-loop",blk.get("-loop","1"),"-framerate",blk.get("-framerate","30"),
                     "-t",blk.get("-t","1")]
                if "-itsoffset" in blk: seg += ["-itsoffset", blk["-itsoffset"]]
                seg += ["-i",path]
                out += seg
            i=j
        else:
            out.append(argv[i]); i+=1
    return out


def main():
    ffmpeg=find_ffmpeg()
    sidecar=SidecarStore(Path(r"E:\KStudio_Image\Video\sidecars")).load_for(SRC)
    ffprobe=Path(ffmpeg).with_name("ffprobe.exe")
    r=subprocess.run([str(ffprobe),"-v","error","-show_entries","format=duration",
                      "-of","json",str(SRC)],capture_output=True,text=True)
    dur=int(float(json.loads(r.stdout or "{}").get("format",{}).get("duration",0) or 0)*1000)
    sw,sh=probe_video_size(str(SRC))

    def tiny_cap(cap,*,surface_w,surface_h,dst,sample_ms=None):
        img=QImage(64,64,QImage.Format_RGBA8888); img.fill(QColor(255,255,0,200)); img.save(str(dst),"PNG")
    ep.render_caption_png=tiny_cap

    out=Path(tempfile.mkdtemp(prefix="nooff_"))/"out.mp4"
    argv,pngs=ep.build_export_args(sidecar=copy.deepcopy(sidecar),src_path=SRC,dst_path=out,
        main_duration_ms=dur,surface_w=sw,surface_h=sh,ffmpeg_path=ffmpeg)
    total_s = dur/20.0/1000.0 + 30  # 20배속 출력 ≈ 87s, 여유 둠
    argv2=rewrite_caption_inputs_no_offset(argv, max(120.0, total_s))

    print(f"캡션 입력 itsoffset 제거 + 전체 span(-t {max(120.0,total_s):.0f}s), 캡션 64x64:")
    peak,frame,v,samples=_run(argv2)
    for el,gb,fr in samples: print(f"  t={el:4.1f}s RSS={gb:5.2f}GB frame={fr}")
    print(f"  => peak={peak}GB frame={frame} {v}")
    print(f"\n비교: tinycap(itsoffset 유지)=8.09GB폭증.  이번 <3GB 면 = itsoffset 가 레버.")
    for p in pngs:
        try: Path(p).unlink(missing_ok=True)
        except OSError: pass
    return 0


if __name__=="__main__":
    sys.exit(main())
