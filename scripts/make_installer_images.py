"""Inno Setup 위저드 배너 BMP 생성 — 수동 1회 실행, 결과물은 installer/ 에 커밋.

사용:  python scripts/make_installer_images.py
버전 숫자는 이미지에 굽지 않는다 (버전 올릴 때마다 재생성 방지 — 스펙 결정).
색은 tokens.py 팔레트에서 가져와 단일 소스 유지.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from screen_recorder.ui.tokens import IMAGE_PALETTE, VIDEO_PALETTE  # noqa: E402

ICON_SRC = ROOT / "resources" / "app_icon_source.png"


def _hex_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


BG_TOP = _hex_rgb(VIDEO_PALETTE["bg"])          # #1F2125
BG_BOTTOM = _hex_rgb(IMAGE_PALETTE["bg"])       # #0F1115 — 더 깊은 다크로 그라데이션
ACCENT = _hex_rgb(VIDEO_PALETTE["primary"])     # 시안
TEXT = _hex_rgb(VIDEO_PALETTE["text"])

# Inno Setup 규격: 100% / 150% / 200% DPI. 쉼표 목록으로 주면 자동 선택.
BANNER_SIZES = {"": (164, 314), "_150": (246, 471), "_200": (328, 628)}
SMALL_SIZES = {"": (55, 58), "_150": (83, 87), "_200": (110, 116)}


def _vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    for y in range(h):
        t = y / max(h - 1, 1)
        row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        img.paste(Image.new("RGB", (w, 1), row), (0, y))
    return img


def _font(px: int):
    # Segoe UI Bold 우선 — 없으면(비 Windows) Pillow 기본 폰트로 폴백.
    for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def make_banner(size: tuple[int, int]) -> Image.Image:
    """환영/완료 페이지 왼쪽 세로 배너 — 아이콘 + 워드마크 + 액센트 라인."""
    w, h = size
    img = _vertical_gradient(size, BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(img)
    icon_px = int(w * 0.55)
    icon = Image.open(ICON_SRC).convert("RGBA").resize(
        (icon_px, icon_px), Image.LANCZOS)
    icon_y = int(h * 0.18)
    img.paste(icon, ((w - icon_px) // 2, icon_y), icon)
    font = _font(int(w * 0.17))
    text = "KStudio"
    tw = draw.textlength(text, font=font)
    draw.text(((w - tw) / 2, icon_y + icon_px + int(h * 0.05)),
              text, font=font, fill=TEXT)
    line_y = h - int(h * 0.08)
    margin = int(w * 0.18)
    draw.rectangle(
        [margin, line_y, w - margin, line_y + max(2, h // 160)], fill=ACCENT)
    return img


def make_small(size: tuple[int, int]) -> Image.Image:
    """내부 페이지 오른쪽 위 작은 로고 — 아이콘만."""
    w, h = size
    img = _vertical_gradient(size, BG_TOP, BG_BOTTOM)
    icon_px = int(min(w, h) * 0.8)
    icon = Image.open(ICON_SRC).convert("RGBA").resize(
        (icon_px, icon_px), Image.LANCZOS)
    img.paste(icon, ((w - icon_px) // 2, (h - icon_px) // 2), icon)
    return img


def generate(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for suffix, size in BANNER_SIZES.items():
        p = out_dir / f"wizard_banner{suffix}.bmp"
        make_banner(size).save(p, "BMP")
        written.append(p)
    for suffix, size in SMALL_SIZES.items():
        p = out_dir / f"wizard_small{suffix}.bmp"
        make_small(size).save(p, "BMP")
        written.append(p)
    return written


if __name__ == "__main__":
    for p in generate(ROOT / "installer"):
        print(p)
