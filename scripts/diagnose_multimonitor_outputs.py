"""dxcam output_idx <-> QScreen 매핑 + 데스크톱 좌표 확인 (멀티모니터 영역 캡처 사전검증).

advisor 지적 #1: tile 의 output_idx 를 QGuiApplication.screens() 순서로 잡으면
dxcam outputs(DXGI 열거 순서)와 다를 수 있다. 이 스크립트로 둘의 데스크톱 좌표를
직접 비교해 'index 매핑이 맞는지' + '위치 기반 매핑에 쓸 좌표가 일치하는지' 확인한다.

각 dxcam output 에서 한 프레임씩 grab → PNG 저장 → 어느 물리 모니터인지 눈으로 확인.
"""
from __future__ import annotations
import sys
from pathlib import Path

import dxcam
import numpy as np

OUT_DIR = Path(__file__).resolve().parent / "_diag_out"
OUT_DIR.mkdir(exist_ok=True)


def dump_dxcam_outputs():
    factory = vars(dxcam)["__factory"]
    print("=== dxcam outputs (DXGI enumeration order) ===")
    rows = []
    for didx, outputs in enumerate(factory.outputs):
        for oidx, out in enumerate(outputs):
            dc = out.desc.DesktopCoordinates
            rect = (dc.left, dc.top, dc.right, dc.bottom)
            meta = factory.output_metadata.get(out.devicename)
            primary = meta[1] if meta else None
            print(f"  device[{didx}] output[{oidx}]: name={out.devicename} "
                  f"res={out.resolution} rot={out.rotation_angle} "
                  f"DesktopCoords(L,T,R,B)={rect} primary={primary}")
            rows.append((didx, oidx, rect, out.resolution))
    return rows


def dump_qscreens():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    print("=== QGuiApplication.screens() (Qt order) ===")
    for i, s in enumerate(app.screens()):
        g = s.geometry()
        print(f"  screen[{i}]: name={s.name()!r} "
              f"geom(x,y,w,h)=({g.x()},{g.y()},{g.width()},{g.height()}) "
              f"DPR={s.devicePixelRatio()}")


def grab_each_output(rows):
    print("=== grab one frame per dxcam output ===")
    for (didx, oidx, rect, res) in rows:
        try:
            cam = dxcam.create(device_idx=didx, output_idx=oidx, output_color="BGRA")
            frame = cam.grab()  # one-shot full output
            if frame is None:
                # new_frame_only=True 면 변화 없을 때 None — 재시도
                frame = cam.grab(new_frame_only=False)
            if frame is not None:
                # BGRA -> RGB 로 저장 (PIL 없으면 numpy 로 PPM)
                rgb = frame[:, :, [2, 1, 0]]
                _save_png(rgb, OUT_DIR / f"output_{didx}_{oidx}.png")
                # 중앙 픽셀과 모서리 평균으로 내용 식별 힌트
                h, w = rgb.shape[:2]
                cen = rgb[h // 2, w // 2].tolist()
                print(f"  output[{didx}][{oidx}] {res}: saved, center_px(RGB)={cen}")
            else:
                print(f"  output[{didx}][{oidx}]: grab returned None twice")
            cam.release()
        except Exception as e:
            print(f"  output[{didx}][{oidx}]: ERROR {e}")


def _save_png(rgb, path):
    try:
        from PIL import Image
        Image.fromarray(np.ascontiguousarray(rgb), "RGB").save(path)
    except Exception:
        # PIL 없으면 작은 썸네일 PPM
        small = rgb[::8, ::8]
        h, w = small.shape[:2]
        with open(str(path) + ".ppm", "wb") as f:
            f.write(f"P6\n{w} {h}\n255\n".encode())
            f.write(np.ascontiguousarray(small).tobytes())


if __name__ == "__main__":
    dump_qscreens()
    print()
    rows = dump_dxcam_outputs()
    print()
    grab_each_output(rows)
    print(f"\nPNGs in: {OUT_DIR}")
