"""인스톨러 배너 생성 스크립트 — 6개 BMP, 규격 크기 검증."""
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    import sys
    sys.path.insert(0, str(_ROOT / "src"))
    p = _ROOT / "scripts" / "make_installer_images.py"
    spec = importlib.util.spec_from_file_location("make_installer_images", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generate_creates_all_bmps(tmp_path):
    from PIL import Image
    mod = _load()
    written = mod.generate(tmp_path)
    assert len(written) == 6
    sizes = {p.name: Image.open(p).size for p in written}
    assert sizes["wizard_banner.bmp"] == (164, 314)      # Inno 100% DPI 규격
    assert sizes["wizard_banner_200.bmp"] == (328, 628)
    assert sizes["wizard_small.bmp"] == (55, 58)
    for p in written:
        assert Image.open(p).format == "BMP"
