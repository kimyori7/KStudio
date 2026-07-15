"""업데이트 통합 카드 다이얼로그 — 안내/다운로드/실패 3상태 한 창.

뷰 전용: 시그널만 내보내고, 설정 저장·다운로드 시작·적용은 controller 책임.
색은 tokens 팔레트 키만 사용 — theme.current_palette() 로 현재 모드
(영상/이미지/문서) 액센트를 자동으로 따라간다.
"""
from __future__ import annotations

import html as _html


def format_bytes(n: int) -> str:
    """바이트 → 사람 읽는 단위. KB 이하 정수, MB 소수 1자리, GB 소수 2자리."""
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.2f} GB"


def notes_html(notes: str, p: dict) -> str:
    """릴리스 노트 문자열 → 불릿 목록 HTML(순수). 빈 문자열이면 안내 문구.

    manifest.notes 는 릴리스 파이프라인이 넣는 자유 텍스트 — 줄 단위로 쪼개고
    선행 불릿 기호(-, •, ·)는 벗겨서 우리 스타일로 통일한다.
    """
    lines = [ln.strip().lstrip("-•· ").strip() for ln in (notes or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return (f'<p style="color:{p["text_sub"]};">자세한 변경 내역은 '
                f'업데이트 후 패치 내역에서 확인할 수 있어요.</p>')
    items = "".join(f'<li style="margin:2px 0;">{_html.escape(ln)}</li>'
                    for ln in lines)
    return f'<ul style="margin:0; padding-left:18px; color:{p["text"]};">{items}</ul>'
