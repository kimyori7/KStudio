import importlib.util
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    p = _ROOT / "scripts" / "internal_hash.py"
    spec = importlib.util.spec_from_file_location("internal_hash", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk(dirpath: Path, files: dict):
    for rel, content in files.items():
        f = dirpath / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)


def test_same_content_same_hash(tmp_path: Path):
    ih = _load()
    a, b = tmp_path / "a", tmp_path / "b"
    _mk(a, {"x.dll": b"111", "sub/y.pyd": b"222"})
    _mk(b, {"x.dll": b"111", "sub/y.pyd": b"222"})
    assert ih.compute_internal_hash(a) == ih.compute_internal_hash(b)


def test_content_change_changes_hash(tmp_path: Path):
    ih = _load()
    a, b = tmp_path / "a", tmp_path / "b"
    _mk(a, {"x.dll": b"111"})
    _mk(b, {"x.dll": b"999"})            # 내용 다름
    assert ih.compute_internal_hash(a) != ih.compute_internal_hash(b)


def test_added_file_changes_hash(tmp_path: Path):
    ih = _load()
    a, b = tmp_path / "a", tmp_path / "b"
    _mk(a, {"x.dll": b"111"})
    _mk(b, {"x.dll": b"111", "new.dll": b"000"})   # 파일 추가
    assert ih.compute_internal_hash(a) != ih.compute_internal_hash(b)


def test_decide_code_patch():
    ih = _load()
    assert ih.decide_code_patch("h1", None) is False     # 부트스트랩
    assert ih.decide_code_patch("h1", "h1") is True      # 의존성 불변 → 30MB
    assert ih.decide_code_patch("h2", "h1") is False     # 의존성 변함 → full


def test_zip_member_order_does_not_change_hash(tmp_path: Path):
    """base_library.zip 함정: 같은 멤버를 다른 순서로 담은 zip 은 같은 해시여야 함."""
    ih = _load()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    with zipfile.ZipFile(a / "base_library.zip", "w") as z:
        z.writestr("m1.pyc", b"AAA"); z.writestr("m2.pyc", b"BBB")
    with zipfile.ZipFile(b / "base_library.zip", "w") as z:
        z.writestr("m2.pyc", b"BBB"); z.writestr("m1.pyc", b"AAA")   # 역순
    # raw 바이트는 순서 차이로 다르지만, 정규화 해시는 같아야 함
    assert (a / "base_library.zip").read_bytes() != (b / "base_library.zip").read_bytes()
    assert ih.compute_internal_hash(a) == ih.compute_internal_hash(b)


def test_zip_member_content_change_changes_hash(tmp_path: Path):
    """멤버 내용이 실제로 바뀌면 해시가 달라져야 함(과도한 정규화 방지)."""
    ih = _load()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    with zipfile.ZipFile(a / "base_library.zip", "w") as z:
        z.writestr("m1.pyc", b"AAA")
    with zipfile.ZipFile(b / "base_library.zip", "w") as z:
        z.writestr("m1.pyc", b"ZZZ")   # 내용 변경
    assert ih.compute_internal_hash(a) != ih.compute_internal_hash(b)
