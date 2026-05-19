"""읽기 전용 도구 5개 — 사이드카 통째 덤프 금지 원칙.

정보 전달 패턴 (2026-05-13 연구 결과):
- `get_sidecar_summary`  — 한 문단 항상-pin (Claude 가 매 작업 시작 시 호출).
- `get_effects_in_range` — 시간/타입 슬라이스 (전체 덤프 대체).
- 나머지 3개 (state / duration / position) — 단일 필드 조회.
"""
from __future__ import annotations

from claude_agent_sdk import tool

from ..adapter import VideoSessionAdapter, list_video_tabs_safe, source_duration_ms_safe
from ._format import effect_summary, sidecar_summary_text
from ._response import no_active_video, text_result


READ_TOOL_NAMES = (
    "get_video_state",
    "get_sidecar_summary",
    "get_effects_in_range",
    "get_duration_ms",
    "get_current_position_ms",
    "inspect_effect",
    "list_video_tabs",
    "list_broll_sources",
)


def make_read_tools(adapter: VideoSessionAdapter) -> list:
    @tool(
        "get_video_state",
        "현재 열려 있는 영상 탭의 기본 상태 — 경로, 세 가지 길이, 재생 위치, "
        "효과 종류별 개수(effects_by_type), 세그먼트 개수. 가장 먼저 부르는 도구.\n"
        "\n"
        "**길이 세 개 — 절대 혼동 금지** (2026-05-14 사용자 보고: 셋을 안 구분하면 환각으로 오해):\n"
        "- `source_duration_ms`: 원본 파일의 길이. 미디어 플레이어로 열었을 때 보이는 시간. "
        "사용자가 '이 영상 몇 분짜리야?' 라고 물으면 보통 이 값을 기대.\n"
        "- `duration_ms`: 현재 *편집 타임라인* 길이 (KStudio 슬라이더가 가리키는 끝). "
        "**KStudio 의 cut 효과는 편집 타임라인에 즉시 적용되지 않음** — 사이드카에 마커로만 "
        "등록되고 export 시점에 잘림. 그래서 source=duration 이 정상 상태. trim·segment "
        "삭제 같은 *트랙 수준* 편집이 있을 때만 source 보다 짧아짐.\n"
        "- `export_duration_ms`: cut 효과들이 적용된 *예상 출력* 길이. = source - cut_planned_ms "
        "(B-roll 삽입은 별도 가산). 사용자가 '편집 결과 / 출력하면 몇 분?' 이라고 물으면 이 값이 답.\n"
        "- `cut_planned_ms`: 등록된 cut 효과들이 export 시 *제거할* 총 ms (단순 자르기만, B-roll "
        "삽입 cut 은 제외 — 그건 replace 라 길이가 줄지 않음). 0 이면 단순 자르기 효과 없음.\n"
        "- `cut_count_planned`: 단순 자르기 cut 효과 개수. effects_by_type.cut 와 다를 수 있음 "
        "(B-roll 삽입 cut 은 effects_by_type 엔 포함, 여기엔 제외).\n"
        "\n"
        "**보고 규칙**: 길이 보고할 때 세 값 중 사용자 의도에 맞는 *하나만 골라* 답변하지 말 것. "
        "'원본 X분짜리이고, 등록된 cut N개로 export 시 Y분이 됩니다' 식으로 *맥락* 같이 제시. "
        "특히 cut_count_planned>0 인데 export_duration_ms == source 면 cut 이 splice 점이거나 "
        "0 길이 — 그대로 보고 (사용자 사례).\n"
        "\n"
        "효과 종류는 effects_by_type 에서 직접 확인 — 개수만 보고 종류 추측 금지.",
        {},
    )
    async def get_video_state(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        sc = adapter.sidecar()
        n_segments = len(sc.video_track) if sc is not None else 0
        # 효과 종류별 개수 — 모든 알려진 type 키 항상 노출 (없으면 0).
        by_type = {"cut": 0, "caption": 0, "speed": 0, "zoom": 0, "broll": 0, "arrow": 0}
        n_effects = 0
        # cut 효과들 — export 시점에 실제로 잘려나갈 ms 계산용.
        # 사용자 보고 (2026-05-14): "cut 효과가 등록되어 있는데 cut_total_ms=0"
        # 원인: source-duration 산술은 *편집 타임라인* 차이만 보여줌. KStudio 의 cut 은
        # 편집엔 즉시 적용 안 되고 사이드카에 마커로만 등록 → 편집 timeline 그대로.
        # 진짜 metric 은 등록된 CutEffect 들의 in/out 합산.
        cut_planned = 0
        cut_count_planned = 0
        if sc is not None:
            from ...effects.types.cut import CutEffect
            for e in sc.effects:
                t = str(getattr(e, "type", "unknown"))
                by_type[t] = by_type.get(t, 0) + 1
                n_effects += 1
                if isinstance(e, CutEffect) and e.in_ms < e.out_ms and not e.src:
                    # 단순 자르기 (splice 가 아니고 B-roll 삽입도 아님) 만 합산.
                    cut_planned += e.out_ms - e.in_ms
                    cut_count_planned += 1
        editor_dur = int(adapter.duration_ms() or 0)
        source_dur = source_duration_ms_safe(adapter)
        if source_dur <= 0:
            source_dur = editor_dur
        # export 예상 길이 — source 에서 cut 들이 빠진 길이 (B-roll 삽입은 별도 모델링).
        export_dur = max(0, source_dur - cut_planned)
        return text_result({
            "source_path": adapter.source_path(),
            "source_duration_ms": source_dur,
            "duration_ms": editor_dur,
            "export_duration_ms": export_dur,
            "cut_planned_ms": cut_planned,
            "cut_count_planned": cut_count_planned,
            "position_ms": adapter.position_ms(),
            "n_effects": n_effects,
            "effects_by_type": by_type,
            "n_segments": n_segments,
        })

    @tool(
        "get_sidecar_summary",
        "현재 영상의 효과 분포를 한 문단 요약 (효과 총합 + 종류별 개수 + 시간 분포). "
        "context 토큰을 적게 쓰면서 전체 그림을 파악하는 용도. 작업 시작 시 한 번 호출.",
        {},
    )
    async def get_sidecar_summary(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        sc = adapter.sidecar()
        if sc is None:
            return text_result({"summary": "영상 비어있음. 효과 없음."})
        return text_result({"summary": sidecar_summary_text(sc, adapter.duration_ms())})

    @tool(
        "get_effects_in_range",
        "지정한 시간 구간 안의 효과를 반환. "
        "**모든 인자 optional** — 전부 생략하면 전체 사이드카의 모든 효과 반환 "
        "(start_ms=0, end_ms=영상 끝, types 필터 없음). "
        "types 는 list 또는 빈 list 또는 생략 = 모든 종류. 특정만 보고 싶으면 "
        "['caption', 'arrow'] 처럼. "
        "유효 type 키: cut/caption/speed/zoom/broll/arrow.",
        {"start_ms": int, "end_ms": int, "types": list},
    )
    async def get_effects_in_range(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        sc = adapter.sidecar()
        if sc is None:
            return text_result({"effects": []})
        # 인자 전부 optional. 누락이면 영상 전체 + 모든 타입.
        start = int(args.get("start_ms") or 0)
        end_arg = args.get("end_ms")
        end = int(end_arg) if end_arg is not None else adapter.duration_ms()
        types_filter = args.get("types")
        # 빈 list / None / 누락 모두 "필터 없음" 처리.
        if not types_filter:
            types_set = None
        else:
            types_set = {str(t) for t in types_filter}
        out: list[dict] = []
        for e in sc.effects:
            e_in = int(getattr(e, "in_ms", 0))
            e_out = int(getattr(e, "out_ms", 0))
            if e_out < start or e_in > end:
                continue
            e_type = str(getattr(e, "type", "unknown"))
            if types_set is not None and e_type not in types_set:
                continue
            out.append(effect_summary(e))
        return text_result({
            "range": {"start_ms": start, "end_ms": end},
            "filtered_types": list(types_set) if types_set else None,
            "n_in_range": len(out),
            "effects": out,
        })

    @tool(
        "get_duration_ms",
        "현재 영상의 총 길이 (밀리초). get_video_state 의 부분 집합 — 길이만 필요할 때.",
        {},
    )
    async def get_duration_ms(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        return text_result({"duration_ms": adapter.duration_ms()})

    @tool(
        "get_current_position_ms",
        "현재 재생 위치 (밀리초). 사용자가 '지금 위치' 라고 할 때 참조.",
        {},
    )
    async def get_current_position_ms(args: dict) -> dict:
        if not adapter.has_active_video():
            return no_active_video()
        return text_result({"position_ms": adapter.position_ms()})

    @tool(
        "inspect_effect",
        "특정 효과의 모든 상세 필드 반환 (nested dataclass 포함). "
        "effect_id 로 조회. 효과 수정(propose_modify_effect) 전에 현재 값 확인용. "
        "예: caption 의 font/stroke/background, zoom 의 keyframe 좌표 등.",
        {"effect_id": str},
    )
    async def inspect_effect(args: dict) -> dict:
        from dataclasses import asdict, is_dataclass
        if not adapter.has_active_video():
            return no_active_video()
        eid = str(args.get("effect_id", ""))
        if not eid:
            from ._response import error_result
            return error_result("effect_id 인자 필수.")
        sc = adapter.sidecar()
        if sc is None:
            from ._response import error_result
            return error_result("사이드카 없음.")
        for eff in sc.effects:
            if getattr(eff, "id", "") == eid:
                if is_dataclass(eff):
                    return text_result(asdict(eff))
                return text_result({"id": eid, "raw": str(eff)})
        from ._response import error_result
        return error_result(f"effect_id '{eid}' 를 찾을 수 없습니다.")

    @tool(
        "list_video_tabs",
        "현재 열려 있는 모든 영상 탭 목록 + 활성 표시. "
        "사용자가 '어느 영상?' 또는 '다른 영상 보여줘' 같이 요청할 때 ambiguity 해소용. "
        "각 항목: {index, label, path, is_active}.",
        {},
    )
    async def list_video_tabs(args: dict) -> dict:
        tabs = list_video_tabs_safe(adapter)
        return text_result({"n_tabs": len(tabs), "tabs": tabs})

    @tool(
        "list_broll_sources",
        "broll 효과의 'src' 파일 경로로 사용 가능한 후보 목록 (라이브러리 영상 + 열린 탭). "
        "propose_effect(type='broll') 호출 전에 *반드시* 이 도구로 실제 존재하는 파일 확인. "
        "파일 경로 추측 금지 — 사용자 디스크에 없는 경로 보내면 apply 단계에서 실패. "
        "반환: [{label, path, source: 'library'|'tab', duration_ms?}].",
        {},
    )
    async def list_broll_sources(args: dict) -> dict:
        fn = getattr(adapter, "list_broll_sources", None)
        if not callable(fn):
            return text_result({"n_sources": 0, "sources": [],
                                "note": "이 어댑터는 broll 소스 검색을 지원하지 않습니다."})
        try:
            sources = list(fn())
        except Exception as exc:
            from ._response import error_result
            return error_result(f"broll 소스 조회 실패: {exc}")
        return text_result({"n_sources": len(sources), "sources": sources})

    return [
        get_video_state,
        get_sidecar_summary,
        get_effects_in_range,
        get_duration_ms,
        get_current_position_ms,
        inspect_effect,
        list_video_tabs,
        list_broll_sources,
    ]
