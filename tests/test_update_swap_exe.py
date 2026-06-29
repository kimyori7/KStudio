import pytest
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


def test_swap_rolls_back_when_replace_fails(tmp_path: Path) -> None:
    """os.replace 가 OSError 를 던지면 target_exe 가 원본으로 복원돼야 한다.

    부분 swap(target.old 는 있지만 target 은 없음) 상태로 남으면
    사용자 바로가기/작업표시줄이 exe 를 찾지 못해 앱이 사라지는 것처럼 보인다.
    """
    target = tmp_path / "KStudio.exe"
    target.write_bytes(b"ORIG")
    missing_new = tmp_path / "does_not_exist.exe"  # os.replace 는 FileNotFoundError 발생

    with pytest.raises(OSError):
        swap_exe(missing_new, target)

    # 항상 실행 가능한 exe 가 남아있어야 함 (rollback)
    assert target.exists(), "target_exe 가 복원되지 않음 — 'app vanishes' 상태"
    assert target.read_bytes() == b"ORIG", "target_exe 내용이 원본과 다름"
    # .old 고아 파일이 남아있으면 안 됨 (롤백 완료)
    assert not (tmp_path / ("KStudio.exe" + OLD_SUFFIX)).exists(), ".old 고아 파일이 남아있음"
