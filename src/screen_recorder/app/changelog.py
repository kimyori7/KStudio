"""패치 내역(체인지로그) — 버전별 사용자용 한글 요약 + 보여줄 범위 선택(순수).

Qt 의존 없음. semver 비교는 updater 의 parse_semver 재사용.
릴리스마다 CHANGELOG 맨 위에 (버전, [요약 줄]) 한 항목 추가.
"""
from __future__ import annotations

from screen_recorder.app.updater.version_compare import parse_semver

# 자동 업데이트(패치)가 시작된 버전 — 전체 목록의 하한.
PATCH_BASELINE = "0.1.4"

# 최신이 위. (version, [user-facing 한글 요약 줄들]).
CHANGELOG: list[tuple[str, list[str]]] = [
    ("1.0.1", [
        "문서 모드: 외부 변경 팝업이 떠 있는 동안 파일이 계속 수정되면 이후 갱신·팝업이 멈추던 문제를 고쳤습니다.",
        "문서 모드: 라이브러리에 MD 파일을 추가하면 그 문서가 즉시 열려 내용이 보입니다.",
    ]),
    ("1.0.0", [
        "설치 용량을 약 35MB 줄였습니다(자동 배경 제거에 실제로 쓰지 않는 라이브러리 정리).",
        "창을 X로 닫아 트레이로 숨길 때마다 뜨던 알림을 없앴습니다.",
        "패치 내역 보기: 업데이트 후 바뀐 점을 알려주고, 도움말 ▸ 패치 내역에서 전체를 볼 수 있습니다.",
    ]),
    ("0.1.5", [
        "업데이트를 30MB 코드 패치로 더 빠르게 받도록 개선했습니다.",
    ]),
    ("0.1.4", [
        "자동 업데이트 추가: 새 버전이 나오면 앱이 알려주고 받아서 적용합니다.",
    ]),
]


def notes_since(prev: str, current: str,
                changelog=CHANGELOG) -> list[tuple[str, list[str]]]:
    """prev < 버전 <= current 인 항목을 최신순으로. 파싱 불가 시 빈 목록."""
    try:
        lo, hi = parse_semver(prev), parse_semver(current)
    except ValueError:
        return []
    return [(v, notes) for v, notes in changelog if lo < parse_semver(v) <= hi]


def all_notes(changelog=CHANGELOG) -> list[tuple[str, list[str]]]:
    """전체(=PATCH_BASELINE~최신), 최신순."""
    return list(changelog)


def decide_startup_changelog(last_seen: str, current: str, settings_existed: bool,
                             changelog=CHANGELOG) -> list[tuple[str, list[str]]]:
    """시작 시 보여줄 항목 결정.

    - last_seen 있음: prev~current 사이(없으면 빈 목록).
    - last_seen 없음 + 기존 설정 있음: 전체 1회(기능 첫 도입).
    - last_seen 없음 + 설정 없음(생 새 설치): 빈 목록.
    """
    if last_seen:
        return notes_since(last_seen, current, changelog)
    return all_notes(changelog) if settings_existed else []
