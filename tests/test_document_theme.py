"""문서(DOCUMENT) 모드 전용 amber 테마 — 이미지(emerald)와 색이 달라야 함."""


def test_document_palette_registered():
    from screen_recorder.ui.tokens import PALETTES
    assert "document" in PALETTES


def test_document_palette_amber_accent_differs_from_image():
    from screen_recorder.ui.tokens import PALETTES
    doc = PALETTES["document"]
    img = PALETTES["image"]
    # 액센트가 amber 로 바뀌어 이미지(emerald)와 구분돼야 함.
    assert doc["primary"].lower() == "#f59e0b"
    assert doc["primary"] != img["primary"]
    assert doc["selection_bg"] != img["selection_bg"]


def test_document_palette_has_all_image_keys():
    # 베이스를 IMAGE_PALETTE 에서 복사하므로 키 누락이 없어야 함 (QSS f-string KeyError 방지).
    from screen_recorder.ui.tokens import PALETTES
    assert set(PALETTES["document"]) == set(PALETTES["image"])


def test_palette_name_for_mode():
    from screen_recorder.ui.main_window import _palette_name_for_mode
    from screen_recorder.ui.mode_controller import AppMode
    assert _palette_name_for_mode(AppMode.VIDEO) == "video"
    assert _palette_name_for_mode(AppMode.IMAGE) == "image"
    assert _palette_name_for_mode(AppMode.DOCUMENT) == "document"


def test_build_qss_with_document_palette():
    # 문서 팔레트로 QSS 빌드 시 KeyError 없이 문자열이 나와야 함.
    from screen_recorder.ui.theme import build_qss
    from screen_recorder.ui.tokens import PALETTES
    qss = build_qss(PALETTES["document"])
    assert "#F59E0B" in qss  # amber primary 가 QSS 에 주입됨
