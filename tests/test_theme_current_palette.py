"""current_palette — apply_theme 가 마지막으로 적용한 팔레트를 기억하는지."""
from screen_recorder.ui import theme
from screen_recorder.ui.tokens import IMAGE_PALETTE, VIDEO_PALETTE


def test_current_palette_follows_apply(qapp):
    theme.apply_theme(qapp, "image")
    assert theme.current_palette() == IMAGE_PALETTE
    theme.apply_theme(qapp, "video")
    assert theme.current_palette() == VIDEO_PALETTE
