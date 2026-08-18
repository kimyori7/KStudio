"""디자인 토큰 — 모드별 팔레트.

영상 모드 (VIDEO_PALETTE): 현재 KStudio 톤 (회색 + 시안 액센트).
이미지 모드 (IMAGE_PALETTE): Mono 다크 + emerald-500 액센트 (neon 톤다운).

theme.build_qss() 가 이 dict 를 f-string 으로 QSS 에 주입한다.
모드 전환 시에는 theme_scope.ThemeScope 가 그 모드 QSS 를 chrome 위젯과 각 탭에만
적용한다 (전역 재적용은 시작 시 1회뿐).
"""
from __future__ import annotations


VIDEO_PALETTE: dict[str, str] = {
    # 현재 KStudio 톤 — 회색 4단계 + 시안 액센트.
    "bg":                  "#1F2125",
    "bg_table_alt":        "#1B1E23",
    "surface":             "#17191D",
    "surface_input":       "#2A2E36",
    "surface_msg":         "#252830",
    "surface_hover":       "#23262D",
    "surface_dock":        "#2C313B",
    "border":              "#3C414B",
    "border_strong":       "#4A5060",
    "border_dim":          "#2A2D34",
    "text":                "#E8E8EA",
    "text_pure":           "#FFFFFF",
    "text_sub":            "#A0A4AB",
    "text_dim":            "#6A6E78",
    "text_header":         "#C8CCD3",
    "primary":             "#4FC3F7",
    "primary_hover":       "#6FD7FF",
    "button_bg":           "#3A3F4B",
    "button_hover_bg":     "#4A4F5B",
    "button_hover_border": "#5A5F6B",
    "button_pressed_bg":   "#2A2D34",
    "selection_bg":        "#2D5DA8",
    "selection_pressed":   "#2A4D8A",
    "disabled_bg":         "#23252B",
    "disabled_border":     "#2D3037",
    "danger":              "#E53935",
    "danger_hover":        "#FF5C58",
}


IMAGE_PALETTE: dict[str, str] = {
    # Mono 다크 + emerald-500 (neon 톤다운 — #34D399 가 너무 광 나서 한 스텝 진하게).
    "bg":                  "#0F1115",
    "bg_table_alt":        "#13161B",
    "surface":             "#1A1D24",
    "surface_input":       "#1A1D24",
    "surface_msg":         "#1A1D24",
    "surface_hover":       "#252932",
    "surface_dock":        "#252932",
    "border":              "#2F343F",
    "border_strong":       "#3F4554",
    "border_dim":          "#2F343F",
    "text":                "#E8EAED",
    "text_pure":           "#FFFFFF",
    "text_sub":            "#9CA3AF",
    "text_dim":            "#6B7280",
    "text_header":         "#B4BCC9",
    "primary":             "#10B981",   # emerald-500
    "primary_hover":       "#34D399",   # emerald-400
    "button_bg":           "#1A1D24",
    "button_hover_bg":     "#252932",
    "button_hover_border": "#3F4554",
    "button_pressed_bg":   "#0F1115",
    "selection_bg":        "#065F46",   # emerald-800
    "selection_pressed":   "#064E3B",   # emerald-900
    "disabled_bg":         "#14171C",
    "disabled_border":     "#2F343F",
    "danger":              "#EF4444",
    "danger_hover":        "#F87171",
}


DOCUMENT_PALETTE: dict[str, str] = {
    # 문서(Markdown) 모드 — IMAGE_PALETTE 와 같은 mono 다크 베이스에 액센트만 amber 로.
    # 이미지(emerald)·영상(시안)과 한눈에 구분되도록 노랑/호박색 계열로 교체.
    # (베이스 색은 IMAGE_PALETTE 를 그대로 복사 — 액센트 4키만 swap 하여 키 누락 방지.)
    **IMAGE_PALETTE,
    "primary":           "#F59E0B",   # amber-500
    "primary_hover":     "#FBBF24",   # amber-400
    "selection_bg":      "#92400E",   # amber-800
    "selection_pressed": "#78350F",   # amber-900
}


PALETTES: dict[str, dict[str, str]] = {
    "video": VIDEO_PALETTE,
    "image": IMAGE_PALETTE,
    "document": DOCUMENT_PALETTE,
}


# 문서 DIFF(비교) 뷰 색 — 다크 배경에 은은하게(글자색은 유지). DIFF 는 문서 모드 전용이라
# QSS 에 주입하지 않고 Python extraSelections 에서만 쓴다(모든 팔레트에 키 강제 회피).
# 줄 마크는 줄 전체 배경(옅게), char 는 변경 글자만 더 진하게(줄 위에 덧칠).
DIFF_COLORS: dict[str, str] = {
    "added_line":   "#16361F",   # 초록 옅게 — 추가된 줄(오른쪽)
    "deleted_line": "#3A1D1F",   # 빨강 옅게 — 삭제된 줄(왼쪽)
    "changed_line": "#3A330E",   # 호박 옅게 — 변경된 줄(양쪽)
    "char":         "#8A6A12",   # 변경 글자 강조 — 변경 줄(amber) 위에서 또렷이 보이게 더 밝게
    # 개요 띠(overview ruler) — 16px 폭이라 위 줄-배경(옅은) 색은 안 보임 → 진한 채도 눈금색 별도.
    # (글자 뒤가 아니라 띠 위에 칠하므로 채도/명도를 높여 멀리서도 분포가 보이게.)
    "bar_bg":       "#0D1015",   # 띠 배경 — 패널보다 더 어둡게
    "added_tick":   "#3FB950",   # 초록(추가) 진하게
    "deleted_tick": "#E5534B",   # 빨강(삭제)
    "changed_tick": "#D6A015",   # 호박(변경)
}
