"""멀티모니터 합성 캡처 정확성 검증 (실하드웨어).

advisor 지적 #2: '프레임이 나온다' != '올바르게 합성된다'. 이음매를 가로지르는 영역을
실제 _run_multi 로 캡처한 합성 프레임을, 각 모니터에서 직접 grab 한 기준 sub-region 과
픽셀 비교한다. left/right 뒤바뀜·이음매 어긋남·tearing 을 잡는다.
"""
from __future__ import annotations
import queue
import sys
import time
from pathlib import Path

import numpy as np

from screen_recorder.capture.targets import RegionTarget, Rect
from screen_recorder.capture.video import (
    VideoCaptureThread,
    resolve_output_rects,
    plan_capture_tiles,
)
import dxcam

OUT = Path(__file__).resolve().parent / "_diag_out"
OUT.mkdir(exist_ok=True)


def save_png(bgra, path):
    rgb = np.ascontiguousarray(bgra[:, :, [2, 1, 0]])
    try:
        from PIL import Image
        Image.fromarray(rgb, "RGB").save(path)
    except Exception:
        small = rgb[::8, ::8]
        h, w = small.shape[:2]
        with open(str(path) + ".ppm", "wb") as f:
            f.write(f"P6\n{w} {h}\n255\n".encode())
            f.write(np.ascontiguousarray(small).tobytes())


def main():
    outs = resolve_output_rects()
    print("outputs:", outs)
    if len(outs) < 2:
        print("SKIP: 모니터가 2개 미만")
        return 1

    # 두 output 의 이음매를 가로지르는 rect (양쪽 600px). 짝수 차원.
    a, b = outs[0], outs[1]
    seam = a.right  # = b.left (좌우 인접 가정)
    rect = Rect(seam - 600, 300, 1200, 600)
    tiles = plan_capture_tiles(rect, outs)
    print("rect:", rect)
    for t in tiles:
        print("  tile:", t)
    if len(tiles) != 2:
        print("SKIP: 이 레이아웃에선 2-tile 이 안 나옴")
        return 1

    # 1) 실제 합성 경로로 캡처
    q: queue.Queue = queue.Queue(maxsize=120)
    th = VideoCaptureThread(target=RegionTarget(rect), fps=30, output_queue=q)
    th.start()
    time.sleep(0.8)
    th.stop()
    th.join(timeout=3.0)
    composite = None
    while not q.empty():
        composite = q.get()  # 가장 최근 프레임
    if composite is None:
        print("FAIL: 합성 프레임 0개")
        return 1
    print("composite shape:", composite.shape)
    save_png(composite, OUT / "composite.png")

    # 2) 기준: 각 모니터에서 tile region 직접 grab (합성 직후라 화면 거의 정적)
    refs = []
    for t in sorted(tiles, key=lambda x: x.dst_x):
        cam = dxcam.create(output_idx=t.output_idx, output_color="BGRA")
        ref = cam.grab(region=t.region, new_frame_only=False)
        cam.release()
        refs.append((t, ref))
        if ref is not None:
            save_png(ref, OUT / f"ref_out{t.output_idx}.png")

    # 3) 비교: composite 의 각 슬라이스 vs 기준. 뒤바뀜이면 cross diff 가 더 작다.
    def mad(x, y):
        n = min(x.shape[0], y.shape[0]); m = min(x.shape[1], y.shape[1])
        return float(np.mean(np.abs(x[:n, :m].astype(np.int16) - y[:n, :m].astype(np.int16))))

    (ta, ra), (tb, rb) = refs
    left = composite[:, ta.dst_x:ta.dst_x + ta.w]
    right = composite[:, tb.dst_x:tb.dst_x + tb.w]
    print("\n=== 정합 비교 (낮을수록 일치) ===")
    print(f"  left  vs ref_out{ta.output_idx} (정상): MAD={mad(left, ra):.2f}")
    print(f"  right vs ref_out{tb.output_idx} (정상): MAD={mad(right, rb):.2f}")
    # 뒤바뀜 가설: left 가 오른쪽 모니터와 더 닮았는지
    print(f"  left  vs ref_out{tb.output_idx} (뒤바뀜?): MAD={mad(left, rb):.2f}")
    print(f"  right vs ref_out{ta.output_idx} (뒤바뀜?): MAD={mad(right, ra):.2f}")
    print(f"\nPNGs in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
