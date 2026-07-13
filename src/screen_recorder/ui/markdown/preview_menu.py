"""미리보기 우클릭 메뉴 구성 — 순수 함수 (WebEngine 비의존, 단위 테스트 가능).

QWebEngineView 기본 메뉴(Back/Forward/Reload/Save page/View page source)는
"빈 template.html 에 JS 로 본문 주입" 설계에서 전부 무의미하거나 유해하다
(Reload = 주입된 본문 소실 → 빈 화면, 2026-07-13 사용자 보고). 여기서 정의한
최소 항목으로 교체하며, key 는 preview.py 가 QWebEnginePage.WebAction 으로 매핑.
"""
from __future__ import annotations


def context_menu_items(has_selection: bool, link_url: str) -> list[tuple[str, str]]:
    """(key, 표시 라벨) 목록. key: copy | copy_link | select_all."""
    items: list[tuple[str, str]] = []
    if has_selection:
        items.append(("copy", "복사"))
    if link_url:
        items.append(("copy_link", "링크 주소 복사"))
    items.append(("select_all", "모두 선택"))
    return items
