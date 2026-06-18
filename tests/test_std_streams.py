"""콘솔 없는 실행(pythonw.exe / PyInstaller console=False)에서 sys.stdout·stderr 가
None 일 때, 서드파티(rembg→pooch→tqdm)가 stderr.write 로 죽지 않도록 안전한 싱크로
교체하는지 검증."""
from __future__ import annotations
import sys

from screen_recorder.app.std_streams import ensure_std_streams


def test_replaces_none_streams_with_writable():
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        sys.stdout = None
        sys.stderr = None
        ensure_std_streams()
        # None 이 아니어야 하고, tqdm 이 호출하는 write/flush 가 예외 없이 동작해야 한다.
        assert sys.stdout is not None
        assert sys.stderr is not None
        progress_line = "\r 50%|#####     | 2.5/5MB"  # tqdm 가 쓰는 형태
        n = sys.stderr.write(progress_line)
        assert n == len(progress_line)
        sys.stdout.write("anything")
        sys.stderr.flush()
        sys.stdout.flush()
        assert sys.stderr.isatty() is False
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err


def test_leaves_existing_streams_untouched():
    # 콘솔 있는 실행(또는 pytest 캡처) — None 이 아니면 건드리지 않는다 (idempotent).
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        ensure_std_streams()
        assert sys.stdout is saved_out
        assert sys.stderr is saved_err
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err


def test_replaces_only_the_none_one():
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        sys.stderr = None  # stderr 만 None
        ensure_std_streams()
        assert sys.stdout is saved_out      # stdout 은 그대로
        assert sys.stderr is not None       # stderr 만 교체
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
