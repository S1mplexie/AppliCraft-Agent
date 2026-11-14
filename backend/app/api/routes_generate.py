"""生成接口：SSE 流式推送（主用）与同步生成（供脚本 / 测试使用）。"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import check_quota, get_current_user, get_db, get_llm, get_user_store
from app.config import Settings, get_settings
from app.db.models import GenerationLog, User
from app.db.session import SessionLocal
from app.graph import nodes, prompts
from app.graph.workflow import build_graph, initial_state, merge_updates
from app.llm.client import LLMClient
from app.library.service import build_reference_context
from app.models.schemas import GeneratePlanResponse, GenerateRequest, NODE_LABELS
from app.skills.service import build_skill_context
from app.storage.filestore import FileStore

router = APIRouter(prefix="/generate", tags=["generate"])
logger = logging.getLogger(__name__)

GRAPH_CONFIG = {"recursion_limit": 30}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _trace(state: dict[str, Any], request: dict[str, Any], settings: Settings) -> dict[str, Any]:
    critique = state.get("critique") or {}
    return {
        "request": request,
        "model": settings.llm_model,
        # 事实清单快照：按建议重新生成时据此还原生成时的素材锁定状态，
        # 即使档案其后被修改或删除，重生成也不会引入新事实。
        "facts": state.get("facts") or {},
        "facts_text": state.get("facts_text") or "",
        "outline": state.get("outline") or [],
        "critique": critique,
        "issues": critique.get("issues") or [],
        "passed_verification": bool(critique.get("passed")),
        "score": critique.get("score"),
        # 各轮自检的分数序列（初稿 → 每次复检），供前端/文档库还原修复曲线。
        "score_history": state.get("score_history") or [],
        "dimensions": critique.get("dimensions") or {},
        "knowledge": state.get("knowledge") or {},
        "references": state.get("reference_meta") or [],
        "skills": state.get("skill_meta") or [],
        "events": state.get("events") or [],
        "warnings": state.get("warnings") or [],
        "revision_count": state.get("revision_count", 0),
    }


def _subject(state: dict[str, Any], request: dict[str, Any]) -> str:
    facts = state.get("facts") or {}
    target = facts.get("target") or {}
    basics = facts.get("basics") or {}
    if request["doc_type"] == "cv":
        return basics.get("name_en") or "CV"
    if request["doc_type"] == "recommendation":
        recommender = facts.get("recommender") or {}
        return recommender.get("name") or "推荐人待定"
    return " ".join(x for x in (target.get("university", ""), target.get("program", "")) if x).strip() or "通用"


def _llm_source(llm: LLMClient | None) -> str:
    """本次生成扣的是谁的额度；测试桩没有 source 时按系统 Key 处理。"""
    return "personal" if getattr(llm, "source", "system") == "personal" else "system"


def _log_generation(
    user_id: str, doc_type: str, document_id: str | None = None,
    status: str = "ok", error: str | None = None, llm_source: str = "system",
) -> None:
    """写审计日志；日志失败不能影响用户拿到的文书。

    llm_source 决定这条记录是否计入「系统 Key 每日免费次数」。
    本地部署版（standalone）没有数据库，也不做计费审计，直接跳过。
    """
    if get_settings().standalone:
        return
    try:
        with SessionLocal() as db:
            db.add(
                GenerationLog(
                    user_id=user_id,
                    doc_type=doc_type,
                    document_id=document_id,
                    status=status,
                    llm_source=llm_source,
                    error=(error or "")[:1000] or None,
                )
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - 审计失败仅告警
        logger.warning("生成审计写入失败：%s", exc)


def _persist(
    state: dict[str, Any], request: dict[str, Any], store: FileStore,
    settings: Settings, user_id: str, llm_source: str = "system",
):
    markdown = state.get("final") or ""
    if not markdown.strip():
        raise RuntimeError("生成结果为空，未生成文档")
    meta = store.save_document(
        profile_id=request["profile_id"],
        doc_type=request["doc_type"],
        markdown=markdown,
        trace=_trace(state, request, settings),
        model=settings.llm_model,
        language=request.get("language", "en"),
        bilingual=bool(request.get("bilingual", False)),
        subject=_subject(state, request),
    )
    _log_generation(user_id, request["doc_type"], meta["id"], llm_source=llm_source)
    return meta


def _inject_references(state: dict[str, Any], store: FileStore, request: dict[str, Any]) -> None:
    """把生成请求里勾选的用户参考文档加载并装入 state，供 outline/draft/verify 注入提示词。"""
    ref_ctx, ref_meta = build_reference_context(store, request.get("reference_doc_ids"))
    state["reference_context"] = ref_ctx
    state["reference_meta"] = ref_meta


def _inject_skills(state: dict[str, Any], store: FileStore, request: dict[str, Any]) -> None:
    """把勾选的写作技能装配成写法约束，注入大纲 / 初稿 / 简历 / 复审核节点。"""
    skill_ctx, skill_meta = build_skill_context(store, request.get("skill_ids"))
    state["skill_context"] = prompts.skill_block(skill_ctx, skill_meta) if skill_ctx else ""
    state["skill_meta"] = skill_meta


def _node_payload(node: str, update: dict[str, Any]) -> dict[str, Any]:
    events = update.get("events") or []
    critique = update.get("critique") or {}
    last_event = events[-1] if events else {}
    return {
        "node": node,
        "label": NODE_LABELS.get(node, node),
        "summary": last_event.get("summary", NODE_LABELS.get(node, node)),
        "warnings": update.get("warnings") or [],
        "outline": update.get("outline"),
        "issues": critique.get("issues") if node == "verify" else None,
        "passed": critique.get("passed") if node == "verify" else None,
        "verdict": critique.get("verdict") if node == "verify" else None,
        "hard_issue_count": critique.get("hard_issue_count") if node == "verify" else None,
        "soft_issue_count": critique.get("soft_issue_count") if node == "verify" else None,
        "score": critique.get("score") if node == "verify" else None,
        "dimensions": critique.get("dimensions") if node == "verify" else None,
        "knowledge": update.get("knowledge"),
        "word_count": critique.get("word_count") if node == "verify" else None,
        "word_limit": critique.get("word_limit") if node == "verify" else None,
        "placeholder_count": critique.get("placeholder_count") if node == "verify" else None,
        "placeholder_overflow": critique.get("placeholder_overflow") if node == "verify" else None,
        # 自检 / 自修复结构化明细：从节点事件直接透传，SSE 与归档 trace 共用同一套字段。
        "phase": last_event.get("phase"),
        "round": last_event.get("round"),
        "score_before": last_event.get("score_before"),
        "score_delta": last_event.get("score_delta"),
        "self_check": last_event.get("self_check"),
        "issue_total": last_event.get("issue_total"),
        "fixes": last_event.get("fixes"),
        "fix_count": last_event.get("fix_count"),
        "focus": last_event.get("focus"),
        "before_score": last_event.get("before_score"),
        "initial_score": last_event.get("initial_score"),
        "final_score": last_event.get("final_score"),
        "score_gain": last_event.get("score_gain"),
        "revision_count": last_event.get("revision_count"),
    }


@router.post("/stream")
async def generate_stream(
    payload: GenerateRequest,
    llm: LLMClient = Depends(get_llm),
    store: FileStore = Depends(get_user_store),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    check_quota(db, user, llm)
    profile = store.get_profile(payload.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="申请人档案不存在，请先保存档案")
    request = payload.model_dump()
    graph = build_graph(llm, settings)
    state = initial_state(profile, request)
    _inject_references(state, store, request)
    _inject_skills(state, store, request)

    async def event_stream():
        yield _sse("start", {"doc_type": request["doc_type"], "nodes": NODE_LABELS})
        try:
            async for chunk in graph.astream(state, config=GRAPH_CONFIG, stream_mode="updates"):
                for node, update in chunk.items():
                    merge_updates(state, update)
                    yield _sse("node", _node_payload(node, update))
            # 记录本次实际使用的模型（自带 Key 时是用户自己填的模型名）。
            meta = _persist(
                state, request, store, getattr(llm, "settings", settings), user.id,
                llm_source=_llm_source(llm),
            )
            yield _sse("done", {"document": meta})
        except Exception as exc:  # noqa: BLE001 - 把生成失败推送给前端
            _log_generation(
                user.id, request["doc_type"], status="error", error=str(exc),
                llm_source=_llm_source(llm),
            )
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("")
async def generate_sync(
    payload: GenerateRequest,
    llm: LLMClient = Depends(get_llm),
    store: FileStore = Depends(get_user_store),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    check_quota(db, user, llm)
    profile = store.get_profile(payload.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="申请人档案不存在，请先保存档案")
    request = payload.model_dump()
    graph = build_graph(llm, settings)
    state = initial_state(profile, request)
    _inject_references(state, store, request)
    _inject_skills(state, store, request)
    try:
        state = await graph.ainvoke(state, config=GRAPH_CONFIG)
        return _persist(
            state, request, store, getattr(llm, "settings", settings), user.id,
            llm_source=_llm_source(llm),
        )
    except Exception as exc:
        _log_generation(
            user.id, request["doc_type"], status="error", error=str(exc),
            llm_source=_llm_source(llm),
        )
        raise


def _build_evidence_legend(facts: dict[str, Any]) -> dict[str, str]:
    """把证据编号（E1 / ED1 / A1 …）映射成可读标签，便于用户确认大纲前知道每段会用到哪些事实。"""
    index = facts.get("index") or {}
    legend: dict[str, str] = {}
    for eid, item in index.items():
        if isinstance(item, dict):
            school = item.get("school") or item.get("org") or item.get("issuer") or item.get("title") or ""
            role = item.get("degree") or item.get("role") or item.get("name") or ""
            label = " · ".join(x for x in (school, role) if x).strip()
            legend[str(eid)] = label or str(eid)
        else:
            legend[str(eid)] = str(eid)
    return legend


@router.post("/plan", response_model=GeneratePlanResponse)
async def generate_plan(
    payload: GenerateRequest,
    llm: LLMClient = Depends(get_llm),
    store: FileStore = Depends(get_user_store),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """大纲预检：只做素材锁定 + 大纲规划，不消耗额度、不写审计、不归档。

    返回模型规划的结构与素材选取，以及证据图例，供用户在正式起草前确认或微调。
    用户确认后的 outline 再随 /generate/stream 提交，工作流据此跳过 outline 节点。
    """
    profile = store.get_profile(payload.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="申请人档案不存在，请先保存档案")
    request = payload.model_dump()
    # 规划阶段不扣额度：initial_state 仅用于装配 fact/reference/skill 容器。
    state = initial_state(profile, request)
    intake_update = await nodes.intake(state=state, settings=settings)
    state.update(intake_update)
    _inject_references(state, store, request)
    _inject_skills(state, store, request)
    outline_update = await nodes.outline(state=state, llm=llm)
    state.update(outline_update)
    outline = state.get("outline") or []
    evidence = _build_evidence_legend(state.get("facts") or {})
    warnings = (intake_update.get("warnings") or []) + (outline_update.get("warnings") or [])
    return GeneratePlanResponse(outline=outline, evidence=evidence, warnings=warnings)
