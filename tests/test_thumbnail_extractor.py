"""ThumbnailExtractor — segment 의 (src, ms) 에서 썸네일 1개 추출 + LRU 캐시."""
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from PySide6.QtGui import QImage

from screen_recorder.services.thumbnail_extractor import ThumbnailExtractor


@pytest.fixture
def extractor():
    return ThumbnailExtractor(cache_size=4)


def test_cache_hit_returns_cached_image(extractor):
    """같은 (src, ms) 두 번째 요청은 ffmpeg 안 부름."""
    img = QImage(96, 54, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    extractor._cache[("a.mp4", 1000)] = img
    out, was_cached = extractor.get_or_none("a.mp4", 1000)
    assert was_cached is True
    assert out is not None


def test_cache_miss_returns_none_and_was_cached_false(extractor):
    out, was_cached = extractor.get_or_none("a.mp4", 1000)
    assert out is None
    assert was_cached is False


def test_lru_eviction(extractor):
    """캐시 가득 차면 가장 오래된 entry 제거."""
    img = QImage(96, 54, QImage.Format_ARGB32)
    extractor._put_cache("a.mp4", 0, img)
    extractor._put_cache("a.mp4", 1000, img)
    extractor._put_cache("a.mp4", 2000, img)
    extractor._put_cache("a.mp4", 3000, img)
    # 5번째 추가 → 첫 번째 evict.
    extractor._put_cache("a.mp4", 4000, img)
    assert ("a.mp4", 0) not in extractor._cache
    assert ("a.mp4", 4000) in extractor._cache


def test_extract_calls_ffmpeg(tmp_path):
    """동기 추출 — ffmpeg 호출 + QImage 반환."""
    extractor = ThumbnailExtractor(cache_size=4)
    fake_png = tmp_path / "shot.png"
    img = QImage(96, 54, QImage.Format_ARGB32)
    img.fill(0xFF223344)
    img.save(str(fake_png), "PNG")

    # 입력 영상 파일이 존재해야 extract_sync 가 ffmpeg 까지 진행.
    fake_input = tmp_path / "input.mp4"
    fake_input.write_bytes(b"fake")

    with patch("screen_recorder.services.thumbnail_extractor.subprocess.run") as mock_run:
        def fake_run(*args, **kwargs):
            argv = args[0]
            out_path = argv[-1]
            from shutil import copyfile
            copyfile(fake_png, out_path)
            return MagicMock(returncode=0, stderr=b"")
        mock_run.side_effect = fake_run

        out = extractor.extract_sync(str(fake_input), 5000)
        assert out is not None
        assert not out.isNull()
        cached, was = extractor.get_or_none(str(fake_input), 5000)
        assert was is True


def test_extract_returns_none_for_missing_src(tmp_path):
    extractor = ThumbnailExtractor()
    out = extractor.extract_sync(str(tmp_path / "nope.mp4"), 1000)
    assert out is None


def test_extract_returns_none_for_empty_src():
    extractor = ThumbnailExtractor()
    out = extractor.extract_sync("", 0)
    assert out is None


def test_extract_returns_none_when_ffmpeg_fails(tmp_path):
    extractor = ThumbnailExtractor()
    fake_input = tmp_path / "input.mp4"
    fake_input.write_bytes(b"fake")
    with patch("screen_recorder.services.thumbnail_extractor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr=b"ffmpeg error")
        out = extractor.extract_sync(str(fake_input), 1000)
        assert out is None
