"""SVG 아이콘 시스템 — lucide-icons 풍 24px stroke 1.5 currentColor.

- `load_icon(name, size, color)` → QIcon. (name, size, color) 키로 LRU 캐시.
- SVG 본문은 `_PATHS` 에 path 데이터만 보관 — 런타임에 같은 24×24 viewBox + stroke
  설정으로 감싸서 색상 치환 후 QSvgRenderer 로 렌더.
- 색상 = `#E8E9EE`(base) / `#FFFFFF`(hover) / `#5A5E68`(disabled). UI 가 그때그때
  지정. 명시 안 하면 base.
- 폰트 fallback 없이 모든 OS·DPI 에서 동일하게 보임.
"""
from __future__ import annotations
from functools import lru_cache
from typing import Optional

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


COLOR_BASE = "#E8E9EE"
COLOR_HOVER = "#FFFFFF"
COLOR_DISABLED = "#5A5E68"


# 각 항목은 SVG path/shape 본문 (color 토큰을 포함한 inner). lucide-icons MIT 스타일.
# stroke="currentColor" 는 _wrap 에서 실제 색으로 치환.
_PATHS: dict[str, str] = {
    "play": '<polygon points="6 3 20 12 6 21 6 3"/>',
    "pause": '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
    "volume-2": (
        '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>'
        '<path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>'
        '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>'
    ),
    "volume-x": (
        '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>'
        '<line x1="22" x2="16" y1="9" y2="15"/>'
        '<line x1="16" x2="22" y1="9" y2="15"/>'
    ),
    "maximize": (
        '<path d="M8 3H5a2 2 0 0 0-2 2v3"/>'
        '<path d="M21 8V5a2 2 0 0 0-2-2h-3"/>'
        '<path d="M3 16v3a2 2 0 0 0 2 2h3"/>'
        '<path d="M16 21h3a2 2 0 0 0 2-2v-3"/>'
    ),
    "minimize": (
        '<path d="M8 3v3a2 2 0 0 1-2 2H3"/>'
        '<path d="M21 8h-3a2 2 0 0 1-2-2V3"/>'
        '<path d="M3 16h3a2 2 0 0 1 2 2v3"/>'
        '<path d="M16 21v-3a2 2 0 0 1 2-2h3"/>'
    ),
    "scissors": (
        '<circle cx="6" cy="6" r="3"/>'
        '<path d="M8.12 8.12 12 12"/>'
        '<path d="M20 4 8.12 15.88"/>'
        '<circle cx="6" cy="18" r="3"/>'
        '<path d="M14.8 14.8 20 20"/>'
    ),
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "crop": (
        '<path d="M6 2v14a2 2 0 0 0 2 2h14"/>'
        '<path d="M18 22V8a2 2 0 0 0-2-2H2"/>'
    ),
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "camera": (
        '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
        '<circle cx="12" cy="13" r="3"/>'
    ),
    "square-arrow-left": (
        '<rect width="18" height="18" x="3" y="3" rx="2"/>'
        '<path d="m12 8-4 4 4 4"/>'
        '<path d="M16 12H8"/>'
    ),
    "square-arrow-right": (
        '<rect width="18" height="18" x="3" y="3" rx="2"/>'
        '<path d="m12 16 4-4-4-4"/>'
        '<path d="M8 12h8"/>'
    ),
    "settings": (
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    # 도구 팔레트
    "mouse-pointer": (
        '<path d="m4 4 7.07 17 2.51-7.39L21 11.07z"/>'
    ),
    "square-dashed": (
        '<path d="M5 3a2 2 0 0 0-2 2"/>'
        '<path d="M19 3a2 2 0 0 1 2 2"/>'
        '<path d="M21 19a2 2 0 0 1-2 2"/>'
        '<path d="M5 21a2 2 0 0 1-2-2"/>'
        '<path d="M9 3h1"/>'
        '<path d="M9 21h1"/>'
        '<path d="M14 3h1"/>'
        '<path d="M14 21h1"/>'
        '<path d="M3 9v1"/>'
        '<path d="M21 9v1"/>'
        '<path d="M3 14v1"/>'
        '<path d="M21 14v1"/>'
    ),
    "square": '<rect width="18" height="18" x="3" y="3" rx="2"/>',
    "move-right": (
        '<path d="M18 8L22 12L18 16"/>'
        '<path d="M2 12H22"/>'
    ),
    "type": '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" x2="15" y1="20" y2="20"/><line x1="12" x2="12" y1="4" y2="20"/>',
    "brush": (
        '<path d="m9.06 11.9 8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08"/>'
        '<path d="M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z"/>'
    ),
    "eraser": (
        '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/>'
        '<path d="M22 21H7"/>'
        '<path d="m5 11 9 9"/>'
    ),
    "wand-2": (
        '<path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72"/>'
        '<path d="m14 7 3 3"/>'
        '<path d="M5 6v4"/>'
        '<path d="M19 14v4"/>'
        '<path d="M10 2v2"/>'
        '<path d="M7 8H3"/>'
        '<path d="M21 16h-4"/>'
        '<path d="M11 3H9"/>'
    ),
    "sparkles": (
        '<path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/>'
        '<path d="M5 3v4"/>'
        '<path d="M19 17v4"/>'
        '<path d="M3 5h4"/>'
        '<path d="M17 19h4"/>'
    ),
    "save": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/>'
        '<polyline points="7 3 7 8 15 8"/>'
    ),
    "copy": (
        '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
        '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'
    ),
    "circle-record": (
        '<circle cx="12" cy="12" r="9"/>'
        '<circle cx="12" cy="12" r="3" fill="currentColor"/>'
    ),
    "bandage": (
        '<path d="M10 10.01h.01"/>'
        '<path d="M10 14.01h.01"/>'
        '<path d="M14 10.01h.01"/>'
        '<path d="M14 14.01h.01"/>'
        '<path d="M18 6v11.5"/>'
        '<path d="M6 17.5V6"/>'
        '<rect width="20" height="12" x="2" y="6" rx="2"/>'
    ),
    # 폴더 — 환경설정 폴더 picker 버튼용. 다른 아이콘과 달리 fill 색상 (노란/베이지)
    # 을 path 에 직접 명시 — _wrap 의 root-level fill="none" 보다 path attribute 가
    # 우선. stroke 는 wrapper 의 currentColor 가 그대로 적용돼 outline 도 테마 따라감.
    "folder": (
        '<path fill="#FFC976" '
        'd="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2'
        'A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'
    ),
    # 드래그-저장 — 이미지 카드 + 우상단으로 빠져나가는 export 화살표 ("들어
    # 올려서 끄집어 내기" 메타포). lucide 의 image 아이콘에 export 화살표를 합성.
    "drag-save": (
        # 이미지 프레임 (좌하단에 살짝 치우쳐 화살표 자리 확보)
        '<rect width="14" height="14" x="3" y="7" rx="2"/>'
        # 태양
        '<circle cx="7" cy="11" r="1.5"/>'
        # 산 — lucide image 의 곡선 봉우리 패턴
        '<path d="m17 21-3.086-3.086a2 2 0 0 0-2.828 0L7 21"/>'
        # 우상단 export 화살표
        '<path d="m18 6 4-4"/>'
        '<path d="M22 6V2h-4"/>'
    ),
}


def _wrap(name: str, color: str) -> str:
    """SVG path 본문을 24×24 viewBox 의 stroke-only SVG 로 감싼다."""
    body = _PATHS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'{body}'
        f'</svg>'
    )


@lru_cache(maxsize=256)
def _render_pixmap(name: str, size: int, color: str) -> QPixmap:
    svg = _wrap(name, color).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(svg))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def load_icon(name: str, *, size: int = 20, color: Optional[str] = None) -> QIcon:
    """이름과 크기/색을 주면 QIcon 반환. 알 수 없는 이름이면 빈 QIcon 반환.

    QIcon 은 다양한 모드(state)별로 pixmap 을 갖는다 — 여기서는 base 한 개만 등록.
    버튼 hover/disabled 색은 호출자가 별도 인스턴스로 만들거나 stylesheet 로 처리.
    """
    if name not in _PATHS:
        return QIcon()
    actual_color = color or COLOR_BASE
    pm = _render_pixmap(name, int(size), actual_color)
    icon = QIcon()
    icon.addPixmap(pm, QIcon.Normal, QIcon.Off)
    # disabled 변형 — 같은 호출자가 setEnabled(False) 만으로 자동 회색이 되도록.
    pm_disabled = _render_pixmap(name, int(size), COLOR_DISABLED)
    icon.addPixmap(pm_disabled, QIcon.Disabled, QIcon.Off)
    return icon


def has_icon(name: str) -> bool:
    return name in _PATHS


def icon_size(default: int = 20) -> QSize:
    return QSize(default, default)
