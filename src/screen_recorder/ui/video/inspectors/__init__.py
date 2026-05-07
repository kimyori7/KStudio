"""효과별 인스펙터 폼 — 우측 도크 안에서 효과 선택에 따라 교체된다.

베이스: InspectorBase — set_effect(effect) + effect_changed 시그널.
빈 상태: EmptyInspector — 효과 미선택 시 안내 라벨.
효과별: caption_inspector / speed_inspector / zoom_inspector / broll_inspector
       (Stage 3+ 에서 추가).
"""
