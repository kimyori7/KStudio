from pathlib import Path
from screen_recorder.app.updater.cleanup import cleanup_old_exe


def test_removes_old(tmp_path: Path):
    old = tmp_path / "KStudio.exe.old"
    old.write_bytes(b"stale")
    cleanup_old_exe(tmp_path)
    assert not old.exists()


def test_noop_when_absent(tmp_path: Path):
    cleanup_old_exe(tmp_path)   # 예외 없이 조용히 통과


def test_does_not_touch_current_exe(tmp_path: Path):
    cur = tmp_path / "KStudio.exe"
    cur.write_bytes(b"live")
    cleanup_old_exe(tmp_path)
    assert cur.exists()
