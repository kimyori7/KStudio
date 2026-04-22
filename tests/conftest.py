import pytest
from screen_recorder.core import ffmpeg_check


@pytest.fixture(autouse=True)
def reset_ffmpeg_cache():
    ffmpeg_check.reset_cache()
    yield
    ffmpeg_check.reset_cache()
