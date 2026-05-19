"""편집 제안 도구 7개 — Phase B + Plan-Gate (2026-05-19).

- `submit_plan(summary, markdown)`            — 사용자 ✓/✗ 게이트 (mutation 전 필수)
- `propose_effect(type, payload, note?)`      — 추가 제안
- `propose_remove_effect(effect_id, note?)`   — 삭제 제안
- `propose_modify_effect(effect_id, payload)` — 부분 갱신 제안
- `list_proposals()`                          — 큐 스냅샷 (게이트 없음)
- `discard_proposals()`                       — 큐 비우기 (게이트 없음)
- `apply_proposals()`                         — UI 스레드 마샬링하여 일괄 적용

직접 sidecar mutation 금지 — 모두 ProposalQueue 에 쌓고 apply 시 콜백으로 UI 스레드
에서 EditController 위임. undo/redo/autosave 자동.

Plan-Gate: propose_* + apply_proposals 는 시작 시 PlanGate.require_approval() 호출
→ 승인된 plan 없으면 'submit_plan 부터' 에러로 Claude 자기 교정 유도.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Callable, Optional

from claude_agent_sdk import tool

from ..adapter import VideoSessionAdapter
from ..plan_gate import PlanGate
from ..proposals import (
    EffectProposal, ProposalQueue,
    validate_modify_payload, validate_payload, validate_remove_payload,
)
from ._response import error_result, no_active_video, text_result

_log = logging.getLogger(__name__)


MUTATION_TOOL_NAMES = (
    "submit_plan",
    "propose_effect",
    "propose_remove_effect",
    "propose_modify_effect",
    "list_proposals",
    "discard_proposals",
    "apply_proposals",
)


ApplyCallback = Callable[[list[EffectProposal], concurrent.futures.Future], None]


def make_mutation_tools(
    adapter: VideoSessionAdapter,
    queue: ProposalQueue,
    on_apply: Optional[ApplyCallback],
    plan_gate: PlanGate,
) -> list:
    @tool(
        "submit_plan",
        "편집 의도를 한국어 markdown 으로 사용자에게 제출. "
        "propose_effect / propose_remove_effect / propose_modify_effect / apply_proposals "
        "호출 전 반드시 먼저. 사용자가 ✓ 하면 도구가 approved=true 응답 → 그때 propose_*. "
        "✗ 면 approved=false 와 reason 응답 → reason 보고 새 plan 수정해 submit_plan 재호출. "
        "단순 정보 조회 (get_*, list_proposals, preview_proposal) 는 plan 없이 자유.\n"
        "\n"
        "summary: PlanCard 헤더 1줄 — 예 '필러 단어 12곳 cut + 자막 5개 추가'.\n"
        "markdown: 본문 3~10줄 — 각 효과 종류 + ms 구간 + 이유. "
        "좌표 결정 (zoom/arrow/caption) 은 plan 작성 *이전* 에 5단계 (get_frame_at → "
        "픽셀 위치 묘사 → 정규화 → 자기 검증) 끝내고 plan 본문에 결과 좌표 포함.",
        {"summary": str, "markdown": str},
    )
    async def submit_plan(args: dict) -> dict:
        summary = str(args.get("summary", ""))
        markdown = str(args.get("markdown", ""))
        plan_id = plan_gate.submit(summary, markdown)
        decision = await plan_gate.await_decision(plan_id)
        return text_result({
            "approved": decision.approved,
            "reason": decision.reason,
        })

    @tool(
        "propose_effect",
        "영상에 새 효과 하나를 추가 제안 (큐에 쌓임 — 실제 적용은 apply_proposals). "
        "type: 'caption'|'cut'|'speed'|'zoom'|'broll'|'arrow' 중 하나. "
        "payload 필수 필드 (type 별): "
        "caption {in_ms, out_ms, text, track_idx?}, "
        "cut {in_ms, out_ms}, "
        "speed {in_ms, out_ms, rate (0.25~4.0 권장)}, "
        "zoom {in_ms, out_ms, start:{x,y,scale}, end:{x,y,scale}, mode?, "
        "region_w?, region_h?, dest_cx?, dest_cy?, dest_w?, dest_h?}, "
        "broll {in_ms, out_ms, src(파일경로), placement?, track_idx?}, "
        "arrow {in_ms, out_ms, start:{x,y}, end:{x,y}, track_idx?}. "
        "좌표는 0~1 정규화 (0,0 좌상단). note 인자로 이 제안의 이유 메모 가능.\n"
        "\n"
        "**cut 의미**: in_ms~out_ms 구간을 영상에서 *제거*. 뒤 콘텐츠가 앞으로 당겨짐. "
        "예: 3분 24초 영상에서 60초~84초 구간(24초) 잘라내려면 "
        "propose_effect(type='cut', payload={in_ms:60000, out_ms:84000}) — "
        "결과 영상은 3분 24초 - 24초 = 3분 0초. "
        "out_ms==in_ms 는 *split point* (자르지 않고 그 위치에 broll 삽입 자리만 만듦). "
        "여러 컷을 한 번에 적용 가능 — 각각 propose_effect 호출 후 apply_proposals 1회.\n"
        "\n"
        "**arrow 좌표 의미**: start = 화살표 *꼬리* (출발점, 원형 마커). "
        "end = 화살표 *촉/머리* (가리키는 대상). 직관에 반할 수 있으니 주의 — "
        "강조하려는 객체 좌표는 'end'. 예: 버튼 강조면 start=(빈 곳), end=(버튼).\n"
        "\n"
        "**zoom 의 2가지 mode — 어느 쪽을 쓸지 먼저 결정**:\n"
        "  (A) `fit_screen` (기본, mode 생략 시): 화면 *전체* 를 (cx,cy) 중심으로 줌인/팬. "
        "프레젠테이션·강조용 영화적 확대. 작은 UI 요소 강조에는 **부적합** — "
        "화면 전체가 확대돼 다른 부분이 안 보임. scale=2 면 화면 절반만 보임.\n"
        "  (B) `magnify_region`: 원본 영상은 그대로 두고, *작은 사각 영역만* 잘라 다른 "
        "위치에 크게 띄움 (돋보기 효과). 버튼·아이콘·작은 텍스트 강조에 적합. "
        "원본 region (source) 과 표시 위치 (dest) 분리: "
        "region_w/h = 잡아낼 원본 영역 크기 (0.05~1.0, 정규화), "
        "start/end.cx/cy = 원본 영역 중심점, "
        "dest_cx/dest_cy = 확대 결과를 어디에 띄울지 (0~1, 보통 빈 여백), "
        "dest_w/dest_h = 확대 결과 크기 (0.05~2.0). "
        "예 — 좌상단 버튼(원본 5% 영역) 강조 → magnify_region, "
        "start={x:0.1,y:0.1,scale:1}, end={x:0.1,y:0.1,scale:3}, "
        "region_w=0.15, region_h=0.10, dest_cx=0.75, dest_cy=0.25, dest_w=0.4, dest_h=0.3.\n"
        "**판단 규칙**: 사용자가 '버튼/아이콘/이 부분 강조' 처럼 *일부* 를 가리키면 "
        "→ magnify_region. 화면 전체 분위기를 줌인/팬 → fit_screen. "
        "전체 확대해놓고 '소용없다' 는 피드백 받지 않으려면 일부 강조엔 반드시 magnify_region.\n"
        "\n"
        "**zoom 좌표 의미** (mode 공통): start/end 의 x,y 는 *카메라 중심점* (또는 "
        "magnify_region 에선 원본 영역 중심점). 시간 보간의 시작/끝. scale=1 일 때도 "
        "x,y 는 보간 경로에 영향. **중요**: end.x/y 는 '중심점' 이지 '좌상단' 이 아님. "
        "헷갈리면 propose 후 preview_proposal 로 결과 확인.\n"
        "\n"
        "**broll src**: 파일 경로 추측 금지. list_broll_sources 로 실제 존재하는 파일 확인 후 사용.\n"
        "\n"
        "**broll placement** (2026-05-14~ 기본 'pip'): \n"
        "- `placement='pip'` (기본, 권장): 작은 PIP 박스로 곁들임 영상을 원본 위에 띄움. "
        "preview overlay 에 가이드 박스가 보이고, 사용자가 위치/크기 조정 가능. *대부분의 경우 이걸 사용.*\n"
        "- `placement='fullscreen'`: 해당 구간 동안 원본을 곁들임으로 *완전히 대체*. preview 에서 "
        "가이드 박스가 안 보임 (원본 영상이 바뀌는 거라 별도 가이드 없음). 의도적으로 cutaway "
        "삽입 (예: B-roll 보여주기) 일 때만 명시. 사용자 보고 (2026-05-14): placement 누락 시 "
        "fullscreen 으로 들어가서 preview 에 아무것도 안 보임 → 혼란. 이제 기본 'pip' 으로 변경됨.\n"
        "\n"
        "**시각 효과는 propose 후 preview_proposal 로 자기 검증 권장** — apply 전에 "
        "어긋난 좌표 잡을 수 있음. modify proposal 도 preview 지원 (2026-05-13~).",
        {"type": str, "payload": dict, "note": str},
    )
    async def propose_effect(args: dict) -> dict:
        try:
            plan_gate.require_approval()
        except ValueError as e:
            return error_result(str(e))
        if not adapter.has_active_video():
            return no_active_video()
        eff_type = str(args.get("type", ""))
        payload = args.get("payload") or {}
        note = args.get("note")
        err = validate_payload(eff_type, payload)
        if err is not None:
            return error_result(f"제안 거부: {err}")
        proposal = EffectProposal(action="add", type=eff_type, payload=payload, note=note)
        # 2026-05-19 사용자 보고: Claude 가 같은 cut 효과 (in_ms=104280, out_ms=105240) 를
        # 3번 propose → 사이드카에 의미 없는 중복. 큐 적재 시점에 차단해 즉시 자기 교정.
        if queue.is_duplicate(proposal):
            return error_result(
                f"중복 제안 거부: 같은 효과 ({eff_type}, in_ms={payload.get('in_ms')}, "
                f"out_ms={payload.get('out_ms')}) 가 큐에 이미 있습니다. "
                f"같은 구간에 여러 효과 의도면 시간 또는 식별 필드 (caption.text, "
                f"speed.rate, broll.src) 를 다르게. 단일 propose 의도면 중복 호출 중단."
            )
        queue.add(proposal)
        # 시각 효과면 자기 검증 (preview) 안내 — 좌표 어긋남을 apply 전에 잡기.
        if eff_type in ("zoom", "arrow", "caption"):
            hint = (
                f"apply 전 자기 검증 권장: preview_proposal(proposal_id='{proposal.id}', "
                f"ms={int(payload.get('in_ms', 0))}) 로 결과 확인 → 어긋났으면 "
                f"propose_modify_effect 로 좌표 보정."
            )
        else:
            hint = "apply_proposals() 호출 전엔 실제 영상에 반영되지 않습니다."
        return text_result({
            "queued": True,
            "action": "add",
            "proposal_id": proposal.id,
            "queue_count": queue.count(),
            "hint": hint,
        })

    @tool(
        "propose_remove_effect",
        "기존 효과 1개를 삭제 제안 (큐에 쌓임). "
        "effect_id 는 get_effects_in_range / get_sidecar_summary 등으로 사전 조회. "
        "여러 개 한 번에 지우려면 이 도구를 여러 번 호출 후 apply_proposals 1회.",
        {"effect_id": str, "note": str},
    )
    async def propose_remove_effect(args: dict) -> dict:
        try:
            plan_gate.require_approval()
        except ValueError as e:
            return error_result(str(e))
        if not adapter.has_active_video():
            return no_active_video()
        payload = {"effect_id": str(args.get("effect_id", ""))}
        note = args.get("note")
        err = validate_remove_payload(payload)
        if err is not None:
            return error_result(f"삭제 제안 거부: {err}")
        proposal = EffectProposal(action="remove", payload=payload, note=note)
        queue.add(proposal)
        return text_result({
            "queued": True,
            "action": "remove",
            "proposal_id": proposal.id,
            "target_effect_id": payload["effect_id"],
            "queue_count": queue.count(),
        })

    @tool(
        "propose_modify_effect",
        "기존 효과의 일부 필드를 수정 제안 (큐에 쌓임). "
        "payload 는 {effect_id, ...변경할 필드만}. "
        "예: caption 의 text 변경 → {effect_id:'cap_xx', text:'new'}. "
        "in_ms/out_ms 변경 시 다른 효과와 시간 겹침이 있으면 apply 시 거부될 수 있음.",
        {"effect_id": str, "payload": dict, "note": str},
    )
    async def propose_modify_effect(args: dict) -> dict:
        try:
            plan_gate.require_approval()
        except ValueError as e:
            return error_result(str(e))
        if not adapter.has_active_video():
            return no_active_video()
        effect_id = str(args.get("effect_id", ""))
        raw_payload = args.get("payload") or {}
        full_payload = {"effect_id": effect_id, **raw_payload}
        note = args.get("note")
        err = validate_modify_payload(full_payload)
        if err is not None:
            return error_result(f"수정 제안 거부: {err}")
        proposal = EffectProposal(action="modify", payload=full_payload, note=note)
        queue.add(proposal)
        return text_result({
            "queued": True,
            "action": "modify",
            "proposal_id": proposal.id,
            "target_effect_id": effect_id,
            "override_keys": list(raw_payload.keys()),
            "queue_count": queue.count(),
        })

    @tool(
        "list_proposals",
        "현재 큐에 쌓인 편집 제안들 — 아직 적용 안 된 것들. apply_proposals 전에 검토용.",
        {},
    )
    async def list_proposals(args: dict) -> dict:
        items = queue.list()
        return text_result({
            "count": len(items),
            "proposals": [
                {"id": p.id, "action": p.action, "type": p.type, "payload": p.payload, "note": p.note}
                for p in items
            ],
        })

    @tool(
        "discard_proposals",
        "큐의 모든 제안을 버림. 사용자가 '취소'·'그만' 한 경우 호출.",
        {},
    )
    async def discard_proposals(args: dict) -> dict:
        n = queue.count()
        queue.clear()
        return text_result({"discarded": n})

    @tool(
        "apply_proposals",
        "큐의 모든 제안을 영상에 실제 적용. UI 스레드에서 EditController 위임 — "
        "undo/redo/autosave 모두 활성. 사용자가 'OK'·'적용'·'좋아' 답할 때 호출.",
        {},
    )
    async def apply_proposals(args: dict) -> dict:
        try:
            plan_gate.require_approval()
        except ValueError as e:
            return error_result(str(e))
        if not adapter.has_active_video():
            return no_active_video()
        items = queue.take_all()
        if not items:
            return text_result({"applied": 0, "note": "큐가 비어있음 — 적용할 제안 없음."})
        if on_apply is None:
            for it in items:
                queue.add(it)
            return error_result("apply 콜백 미설정 — 런타임 wiring 점검 필요.")
        fut: concurrent.futures.Future = concurrent.futures.Future()
        try:
            on_apply(items, fut)
        except Exception as exc:
            _log.exception("apply_proposals: on_apply callback raised")
            for it in items:
                queue.add(it)
            return error_result(f"apply 디스패치 실패: {exc}")
        try:
            result = await asyncio.wrap_future(fut)
        except Exception as exc:
            _log.exception("apply_proposals: future failed")
            for it in items:
                queue.add(it)
            return error_result(f"apply 실행 실패: {exc}")
        return text_result(result)

    return [
        submit_plan,
        propose_effect,
        propose_remove_effect,
        propose_modify_effect,
        list_proposals,
        discard_proposals,
        apply_proposals,
    ]
