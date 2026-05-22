"""말풍선 스타일 상수 — 모든 bubble 위젯이 공유.

chat_panel.py 에서 분리 (Task 7).  동작 변경 없음.
"""
from __future__ import annotations

# "채팅 앱" 같은 말풍선 느낌을 빼고 평문(터미널 로그) 스타일로 — 사용자 요청 2026-05-19.
# 일반 대화 (user / assistant / thinking / system) 는 배경/테두리/radius/padding 없이
# 텍스트 색만으로 role 구분. tool_use / tool_result 는 기존대로 한 줄 로그.
# 액션이 필요한 카드 (error, proposals_preview) 는 시각 강조 유지.
_BUBBLE_STYLES = {
    "user":              "color:#f1f5f9;font-weight:600;",
    "assistant":         "color:#e2e8f0;",
    "thinking":          "color:#64748b;font-style:italic;font-size:11px;",
    "system":            "color:#94a3b8;font-style:italic;font-size:11px;",
    "tool_use":          "color:#fcd34d;padding:0px 2px;font-family:Consolas,monospace;font-size:10px;",
    "tool_result":       "color:#86efac;padding:0px 2px;font-family:Consolas,monospace;font-size:10px;",
    "error":             "background:#3f1d1d;color:#fca5a5;border:1px solid #7f1d1d;border-radius:6px;padding:6px 10px;",
    "proposals_preview": "background:#0c1322;color:#dbeafe;border:1px solid #38bdf8;border-radius:8px;padding:10px 12px;",
    "plan_card": "background:#1a2533;color:#e0f2fe;border:1px solid #0ea5e9;"
                 "border-radius:8px;padding:10px 12px;",
}

# 로그 스타일 (배경 없음) role 들 — spacing 더 좁게 + 줄바꿈 안 함.
_LOG_LINE_ROLES = frozenset(("tool_use", "tool_result"))

_ACTION_LABEL_KO = {"add": "추가", "remove": "삭제", "modify": "수정"}
_TYPE_LABEL_KO = {
    "caption": "캡션", "cut": "자르기", "speed": "배속",
    "zoom": "줌", "broll": "곁들임", "arrow": "화살표",
}
