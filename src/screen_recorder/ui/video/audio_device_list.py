"""오디오 출력 장치 목록 순수 헬퍼 (Qt 비의존).

컨트롤바 드롭다운 구성·복원에 쓰는 계산만 분리해 단위테스트 가능하게 한다.
실제 QMediaDevices 열거/적용은 player_widget·video_tab(Qt 계층)에서 처리.
"""
from __future__ import annotations

# 드롭다운 맨 위 "시스템 기본 따라가기" 항목 + 저장값의 의미. 빈 문자열 = 기본 따라가기.
FOLLOW_DEFAULT_ID = ""


def disambiguate_labels(devices: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(id, description) 목록에서 같은 description 이 2개 이상이면 2번째부터 " (N)" 부여.

    예: DELL U2724D 모니터 2대 → "DELL U2724D", "DELL U2724D (2)". 첫 번째는 그대로.
    순서 보존.
    """
    seen: dict[str, int] = {}
    out: list[tuple[str, str]] = []
    for dev_id, desc in devices:
        n = seen.get(desc, 0) + 1
        seen[desc] = n
        label = desc if n == 1 else f"{desc} ({n})"
        out.append((dev_id, label))
    return out


def resolve_current_id(saved_id: str, available_ids: list[str]) -> str:
    """저장된 장치 id 가 현재 사용 가능 목록에 있으면 그대로, 없으면 기본 따라가기.

    저장값이 빈 문자열이면 그대로 기본 따라가기. 장치가 사라졌다 다시 나타나면 그때
    다시 매칭된다(호출 측이 audioOutputsChanged 마다 재호출).
    """
    if saved_id and saved_id in available_ids:
        return saved_id
    return FOLLOW_DEFAULT_ID
