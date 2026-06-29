from pathlib import Path
from screen_recorder.app.updater.apply_code_patch import swap_exe, OLD_SUFFIX


def test_swap_moves_new_into_place(tmp_path: Path):
    target = tmp_path / "KStudio.exe"
    target.write_bytes(b"OLD-v1")
    new = tmp_path / "downloaded" / "KStudio.exe"
    new.parent.mkdir()
    new.write_bytes(b"NEW-v2")

    swap_exe(new, target)

    assert target.read_bytes() == b"NEW-v2"                       # 새 버전이 자리에
    assert (tmp_path / ("KStudio.exe" + OLD_SUFFIX)).read_bytes() == b"OLD-v1"  # 옛 것은 .old
    assert not new.exists()                                       # 원본 이동됨


def test_swap_replaces_existing_old(tmp_path: Path):
    target = tmp_path / "KStudio.exe"
    target.write_bytes(b"OLD-v2")
    stale = tmp_path / ("KStudio.exe" + OLD_SUFFIX)
    stale.write_bytes(b"STALE-v0")           # 이전 패치 잔여
    new = tmp_path / "new.exe"
    new.write_bytes(b"NEW-v3")

    swap_exe(new, target)

    assert target.read_bytes() == b"NEW-v3"
    assert (tmp_path / ("KStudio.exe" + OLD_SUFFIX)).read_bytes() == b"OLD-v2"  # 갱신됨
