from pathlib import Path

_ISS = (Path(__file__).resolve().parent.parent / "installer" / "KStudio.iss"
        ).read_text(encoding="utf-8")


def test_default_dir_is_localappdata():
    assert "{localappdata}\\Programs" in _ISS or "{localappdata}/Programs" in _ISS


def test_privileges_lowest():
    assert "PrivilegesRequired=lowest" in _ISS


def test_override_dialog_kept():
    # 원하는 사용자는 여전히 Program Files 로 격상 설치 가능해야 함.
    assert "PrivilegesRequiredOverridesAllowed=dialog" in _ISS


def test_no_autopf_default():
    # 기본이 더 이상 Program Files({autopf}) 가 아니어야 함.
    assert "DefaultDirName={autopf}" not in _ISS
