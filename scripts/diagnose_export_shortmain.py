"""decisive: 짧은 본영상 + 캡션 6개 overlay 가 bounded 인가?

확정된 사실: 캡션 overlay 가 있으면 본영상 프레임이 무한 버퍼(크기·offset 무관),
없으면 2.3GB 평탄. 가설: '29분 원본을 라이브 디코딩하며 overlay 통과'가 문제 →
2단계(짧은 base 위에 caption)면 bounded.

여기서 90s testsrc(실해상도 2554x1362) + 캡션 6개 overlay 를 돌려 RSS 측정.
bounded(<2GB) → 2단계 렌더가 정답. 폭증 → overlay 자체가 근본 문제(2단계도 위험).
"""
from __future__ import annotations
import os, re, subprocess, sys, tempfile, threading, time
from pathlib import Path

FFMPEG = r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.EXE"
W,H = 2554,1362
DUR = 90
_FRAME_RE = re.compile(rb"frame=\s*(\d+)")


def _run(argv, abort_gb=6.0, abort_s=60.0):
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
        if rss>abort_gb*1e9: verdict[0]="6GB중단"; proc.kill(); break
        if el>abort_s: verdict[0]="60s중단"; proc.kill(); break
        time.sleep(2.0)
    return round(peak[0]/1e9,2),last[0],verdict[0],samples


def main():
    d=Path(tempfile.mkdtemp(prefix="shortmain_"))
    src=d/"src.mp4"; cap=d/"cap.png"
    subprocess.run([FFMPEG,"-y","-f","lavfi","-i",f"testsrc=size={W}x{H}:rate=30:duration={DUR}",
                    "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",str(src)],
                   check=True,capture_output=True)
    # 실제와 동일: 전체화면 RGBA 캡션 PNG
    subprocess.run([FFMPEG,"-y","-f","lavfi",
                    "-i",f"color=c=black@0.0:s={W}x{H},format=rgba,drawbox=x=80:y=80:w=520:h=140:color=yellow@1.0:t=fill",
                    "-frames:v","1",str(cap)],check=True,capture_output=True)

    # 캡션 6개 — 실제 사이드카처럼 offset 분산(0,12,24,36,48,60s), 각 4s 창
    wins=[(0,4),(12,16),(24,28),(36,40),(48,52),(60,64)]
    argv=[FFMPEG,"-y","-i",str(src)]
    for ci,(a,b) in enumerate(wins):
        argv += ["-loop","1","-framerate","30","-t",f"{b-a:.1f}","-itsoffset",f"{a:.1f}","-i",str(cap)]
    parts=[]; cur="0:v"
    for ci,(a,b) in enumerate(wins):
        idx=ci+1
        parts.append(f"[{idx}:v]format=rgba,fade=t=in:st={a}:d=0.3:alpha=1,fade=t=out:st={b-0.3}:d=0.3:alpha=1[c{ci}]")
        nv=f"v{ci+1}"
        parts.append(f"[{cur}][c{ci}]overlay=enable='between(t\\,{a}\\,{b})'[{nv}]")
        cur=nv
    fc=";".join(parts)
    argv += ["-filter_complex",fc,"-map",f"[{cur}]","-c:v","libx264","-preset","ultrafast","-crf","30","-f","null","-"]

    print(f"90s 본영상(2554x1362) + 전체화면 캡션 6개 overlay (itsoffset 분산):")
    peak,frame,v,samples=_run(argv)
    for el,gb,fr in samples: print(f"  t={el:4.1f}s RSS={gb:5.2f}GB frame={fr}")
    print(f"  => peak={peak}GB frame={frame} {v}")
    print("\nbounded(<2GB)+frame증가 → 짧은 base 위 caption 은 안전 → 2단계 렌더가 정답.")
    return 0


if __name__=="__main__":
    sys.exit(main())
