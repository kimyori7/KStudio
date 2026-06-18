"""정보창(About) HTML — 버전을 인자로 받는 순수 함수.

버전을 하드코딩하지 않고 `screen_recorder.__version__`(단일 소스)에서 받아 끼운다.
순수 함수라 위젯 없이 단위 테스트로 버전 주입을 검증할 수 있다.
"""
from __future__ import annotations


def about_html(version: str) -> str:
    """정보 다이얼로그에 보여줄 HTML. version 만 가변, 나머지는 고정."""
    return (
        f"<h3>KStudio {version}</h3>"
        "<p>Windows 전용 화면 캡처 · 녹화 · 이미지 편집 통합 툴</p>"
        "<p>© 2026 kimyori</p>"
    )
