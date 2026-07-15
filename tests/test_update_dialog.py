"""UpdateDialog 통합 카드 — 순수 함수 + 상태 전환 + 시그널."""
from screen_recorder.ui.tokens import VIDEO_PALETTE
from screen_recorder.ui.update_dialog import format_bytes, notes_html


def test_format_bytes_units():
    assert format_bytes(512) == "512 B"
    assert format_bytes(10 * 1024) == "10 KB"
    assert format_bytes(25_600_000) == "24.4 MB"        # 24.4140625 MB
    assert format_bytes(2 * 1024 ** 3) == "2.00 GB"


def test_notes_html_bullets():
    html = notes_html("- 기능 A\n- 기능 B", VIDEO_PALETTE)
    assert "기능 A" in html and "<li" in html


def test_notes_html_empty_fallback():
    assert "패치 내역" in notes_html("", VIDEO_PALETTE)


def test_notes_html_escapes():
    assert "<script>" not in notes_html("- <script>x</script>", VIDEO_PALETTE)
