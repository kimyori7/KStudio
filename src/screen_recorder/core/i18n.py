"""dict 기반 가벼운 i18n — 한글이 source, 다른 언어는 사전 lookup.

Qt Linguist (`QTranslator` + `.ts/.qm`) 풀스택 대신 단순 dict 를 쓴 이유:
- KStudio 의 모든 UI 텍스트는 이미 한글로 작성돼 있어 한글을 source key 로 그대로
  쓰는 게 자연스럽다 (별도 ID 부여 없이 코드에서 바로 읽힘).
- plural form / 컨텍스트 분기 같은 고급 기능이 필요 없는 작은 앱.
- 빌드 파이프라인 추가 (`pyside6-lupdate / lrelease`) 없이 Python 만으로 끝.

사용법:
    from screen_recorder.core.i18n import tr, set_language
    label.setText(tr("녹화 중"))
    set_language("en")  # 한 번 호출하면 모든 후속 tr() 호출이 영문 반환

번역 누락 시 동작: 원문 한글을 그대로 반환 (silent fallback). 즉, wrap 만 해 두고
영문이 채워지지 않은 문자열은 한글로 보임 — 점진적 영문화에 유리.
"""
from __future__ import annotations
from typing import Callable, Literal


Lang = Literal["ko", "en"]

_lang: Lang = "ko"
# language 변경 시 호출될 콜백들 — UI 가 즉시 갱신되도록.
_observers: list[Callable[[Lang], None]] = []


# 한글 원문 → {"en": "English"} 사전.
# 점진적 추가. 누락 시 한글이 그대로 보이므로 wrap 만 하고 영문은 나중에 채워도 됨.
_TRANSLATIONS: dict[str, dict[Lang, str]] = {}


def register(translations: dict[str, dict[Lang, str]]) -> None:
    """파일별로 자기 번역 dict 를 등록. 중복 key 는 마지막 등록이 이김 (의도적).

    여러 모듈이 같은 한글 원문 ("저장" 같은 흔한 단어) 을 공유할 수 있고, 그 경우
    한 곳에서 등록하면 됨.
    """
    _TRANSLATIONS.update(translations)


def set_language(lang: Lang) -> None:
    """앱 전체 언어 변경. 등록된 observer 들에게 통지."""
    global _lang
    if lang == _lang:
        return
    _lang = lang
    for cb in list(_observers):
        try:
            cb(lang)
        except Exception:
            # observer 에러가 다른 옵저버 통지를 막지 않도록 silent.
            import logging
            logging.getLogger(__name__).exception("i18n observer failed")


def current_language() -> Lang:
    return _lang


def add_observer(cb: Callable[[Lang], None]) -> None:
    """language 변경 시 호출될 콜백 등록. 보통 main_window 가 자기 retranslate
    메서드를 등록.
    """
    _observers.append(cb)


def remove_observer(cb: Callable[[Lang], None]) -> None:
    try:
        _observers.remove(cb)
    except ValueError:
        pass


def tr(key: str) -> str:
    """한글 원문 → 현재 언어 번역. 누락 시 원문 그대로."""
    if _lang == "ko":
        return key
    entry = _TRANSLATIONS.get(key)
    if entry is None:
        return key
    return entry.get(_lang, key)
