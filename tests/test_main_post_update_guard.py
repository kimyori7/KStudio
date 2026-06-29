import re
from pathlib import Path

_MAIN = (Path(__file__).resolve().parent.parent
         / "src" / "screen_recorder" / "app" / "main.py").read_text(encoding="utf-8")


def test_post_update_flag_present():
    assert "--post-update" in _MAIN


def test_forward_guarded_by_post_update():
    # try_forward 가 --post-update 일 때는 건너뛰도록 가드돼야 함.
    assert re.search(r"post_update.*try_forward|not\s+_post_update", _MAIN)


def test_cleanup_old_exe_called():
    assert "cleanup_old_exe" in _MAIN


def test_update_check_hooked():
    assert "start_update_check" in _MAIN
