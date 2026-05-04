"""이미지 업/다운스케일 — Pillow LANCZOS.

캔버스 합성 결과(QImage) 를 입력받아 목표 픽셀 크기로 리사이즈한 새 QImage 를
반환한다. 다운스케일은 LANCZOS 가 사실상 표준 품질이고, 1~2배 정도의 가벼운
업스케일도 충분히 깔끔. 더 큰 배율의 AI 업스케일(Real-ESRGAN 등)은 별도 작업.

호출자는 결과 QImage 를 받아 새 PNG 파일로 저장하면 된다. 트림 패턴(원본 보존
+ 새 파일 + 새 라이브러리 entry + 새 탭) 을 그대로 따라 단순하게 처리.
"""
from __future__ import annotations
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QImage


def scale_qimage(image: QImage, target_w: int, target_h: int) -> QImage:
    """QImage → Pillow LANCZOS → QImage. 입력은 손상하지 않는다.

    target_w/target_h 는 1 이상이어야 한다. 입력과 같은 크기여도 그냥 사본 반환.
    """
    if target_w <= 0 or target_h <= 0:
        raise ValueError(f"잘못된 목표 크기: {target_w}×{target_h}")

    src = image.convertToFormat(QImage.Format_RGBA8888)
    w, h = src.width(), src.height()
    ptr = src.bits()
    pil_in = Image.frombytes("RGBA", (w, h), bytes(ptr), "raw", "RGBA")

    pil_out = pil_in.resize((int(target_w), int(target_h)), Image.LANCZOS)

    raw = pil_out.tobytes("raw", "RGBA")
    out = QImage(raw, pil_out.width, pil_out.height,
                 pil_out.width * 4, QImage.Format_RGBA8888).copy()
    return out


def resolve_scaled_path(src: Path, target_w: int, target_h: int) -> Path:
    """`<원본>_scaled_<W>x<H>_NNN.png` 형식으로 충돌 없는 새 경로 반환.

    같은 폴더에 같은 크기로 여러 번 만들 수 있도록 NNN 카운터 자동 증가.
    원본이 PNG 가 아니어도 결과는 항상 PNG (알파 보존).
    """
    parent = src.parent
    stem = src.stem
    base = f"{stem}_scaled_{target_w}x{target_h}"
    n = 1
    candidate = parent / f"{base}_{n:03d}.png"
    while candidate.exists():
        n += 1
        if n > 999:
            raise OSError("출력 파일명 충돌 (>999)")
        candidate = parent / f"{base}_{n:03d}.png"
    return candidate


def save_scaled(image: QImage, dst: Path) -> None:
    """결과 QImage 를 PNG 로 저장. 실패 시 OSError."""
    ok = image.save(str(dst), "PNG")
    if not ok:
        raise OSError(f"이미지 저장 실패: {dst}")
