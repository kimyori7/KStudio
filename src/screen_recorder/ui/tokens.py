"""디자인 토큰 — 모드별 팔레트.

영상 모드 (VIDEO_PALETTE): 현재 KStudio 톤 (회색 + 시안 액센트).
이미지 모드 (IMAGE_PALETTE): Mono 다크 + emerald-500 액센트 (neon 톤다운).

theme.build_qss() 가 이 dict 를 f-string 으로 QSS 에 주입한다.
mode_controller 의 mode_changed 시그널이 발화될 때마다 main_window 가
적절한 팔레트로 theme.apply_theme 를 다시 호출.
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


PALETTES: dict[str, dict[str, str]] = {
    "video": VIDEO_PALETTE,
    "image": IMAGE_PALETTE,
}
