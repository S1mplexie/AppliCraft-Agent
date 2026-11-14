"""生成文书的查询、版本管理与导出。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import check_quota, get_current_user, get_db, get_llm, get_user_store
from app.config import Settings, get_settings
from app.db.models import User
from app.exporters.docx import markdown_to_docx
from app.graph import nodes, prompts
from app.graph.workflow import merge_updates
from app.knowledge.retriever import get_retriever
from app.llm.client import LLMClient
from app.models.schemas import DocumentUpdate, NODE_LABELS, RegenerateRequest
from app.storage.filestore import FileStore, StorageError, _strip_zh_blocks

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


@router.get("")
def list_documents(
    profile_id: str | None = None,
    project_id: str | None = None,
    store: FileStore = Depends(get_user_store),
):
    """文书列表：profile_id 按档案分域；project_id 再按申请项目过滤（项目管理 tab 用）。"""
    return {"items": store.list_documents(profile_id, project_id=project_id)}


@router.get("/{doc_id}")
def read_document(doc_id: str, store: FileStore = Depends(get_user_store)):
    data = store.get_document(doc_id)
    if not data:
        raise HTTPException(status_code=404, detail="文档不存在")
    return data


@router.put("/{doc_id}")
def update_document(doc_id: str, payload: DocumentUpdate, store: FileStore = Depends(get_user_store)):
    meta = store.update_document(doc_id, payload.markdown)
    if not meta:
        raise HTTPException(status_code=404, detail="文档不存在")
    return meta


@router.delete("/{doc_id}")
def delete_document(doc_id: str, store: FileStore = Depends(get_user_store)):
    if not store.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"deleted": True}


@router.get("/{doc_id}/download")
def download_document(
    doc_id: str,
    format: str = Query(default="md", pattern="^(md|docx)$"),
    version: str | None = None,
    # 中英对照文档导出时默认剥离中文译块，得到纯英文递交版；传 false 可保留对照。
    strip_zh: bool = Query(default=True),
    store: FileStore = Depends(get_user_store),
):
    try:
        markdown = store.document_markdown(doc_id, version)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if markdown is None:
        raise HTTPException(status_code=404, detail="文档或版本不存在")
    if strip_zh:
        markdown = _strip_zh_blocks(markdown)

    suffix = version or "current"
    if format == "docx":
        path = store.export_dir() / f"{doc_id}_{suffix}.docx"
        markdown_to_docx(markdown, path)
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"AppliCraft_{doc_id}.docx",
        )
    path = store.export_dir() / f"{doc_id}_{suffix}.md"
    path.write_text(markdown, encoding="utf-8")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"AppliCraft_{doc_id}.md")


# --------------------------------------------------------------- 按审核建议重新生成


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _log_generation(user_id: str, doc_type: str, document_id: str | None = None,
                    status: str = "ok", error: str | None = None,
                    llm_source: str = "system") -> None:
    """写审计日志；日志失败不能影响用户拿到的文书。"""
    from app.api.routes_generate import _log_generation as _log

    _log(user_id, doc_type, document_id=document_id, status=status, error=error,
         llm_source=llm_source)


def _restore_state(
    data: dict, store: FileStore, settings: Settings,
) -> tuple[dict, dict]:
    """从已存文档还原生成状态：优先用 trace 里的事实快照，旧文档回退到当前档案。"""
    from app.api.routes_generate import _inject_references, _inject_skills, _subject

    meta = data["meta"]
    trace = data.get("trace") or {}
    request = trace.get("request")
    if not isinstance(request, dict) or not request.get("doc_type"):
        raise HTTPException(
            status_code=400,
            detail="该文档缺少生成参数（较早期版本），无法按建议重新生成，请基于当前档案重新生成一份。",
        )

    facts = trace.get("facts") or {}
    facts_text = trace.get("facts_text") or ""
    profile: dict = store.get_profile(meta.get("profile_id", "")) or {}
    if not facts_text:
        # 旧文档没有事实快照：用当前档案重新锁定素材（档案被删则无法继续）。
        if not profile:
            raise HTTPException(
                status_code=400,
                detail="该文档缺少事实快照且所属档案已删除，无法重新生成。",
            )
        facts, facts_text = prompts.render_facts(profile, request)

    # RAG 背景与系统提示按生成时的参数重建（词法检索是确定性的）。
    career_goal = profile.get("career_goal", "")
    ref = get_retriever(settings).retrieve(facts.get("target"), request, career_goal)
    state = {
        "profile": profile,
        "request": request,
        "facts": facts,
        "facts_text": facts_text,
        "system_prompt": prompts.build_system(request),
        "outline": trace.get("outline") or [],
        "draft": data.get("markdown") or "",
        "critique": trace.get("critique") or {},
        "revision_count": int(trace.get("revision_count") or 0),
        "score_history": [],
        "best_snapshot": {},
        "regressed": False,
        # 上一版质量分：重生成后用于展示「较上轮 +N / -N」。
        "previous_score": (trace.get("critique") or {}).get("score"),
        # 复检对照的初始意见：以本文档生成时的校验结果为上一轮基准（revise 会覆盖）。
        "previous_issues": (trace.get("critique") or {}).get("issues") or [],
        "final": "",
        "knowledge_context": prompts.knowledge_block(ref.context, ref.sources, ref.matched_program),
        "knowledge_sources": ref.sources,
        "knowledge": {
            "sources": ref.sources,
            "matched_program": ref.matched_program,
            "context_chars": ref.context_chars,
            "enabled": ref.enabled,
            "note": ref.note,
        },
        # 按建议重生成时也还原勾选的参考文档，保持素材上下文一致。
        "reference_context": "",
        "reference_meta": [],
        # 技能与参考文档一样按生成时的勾选还原，保持重生成的写法约束一致。
        "skill_context": "",
        "skill_meta": [],
        "events": list(trace.get("events") or []),
        "warnings": list(trace.get("warnings") or []),
    }
    _inject_references(state, store, request)
    _inject_skills(state, store, request)
    return state, _subject({"facts": facts}, request)


@router.post("/{doc_id}/regenerate")
async def regenerate_document(
    doc_id: str,
    payload: RegenerateRequest,
    llm: LLMClient = Depends(get_llm),
    store: FileStore = Depends(get_user_store),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """按用户审核建议重新生成：修订 → 复审 → 定稿，保存为同一文档的新版本。

    事实边界：只允许使用生成时锁定的素材（trace 快照或当前档案），用户建议里
    超出事实清单的表述以 [TO CONFIRM] 占位，绝不编造。
    """
    from app.api.routes_generate import _llm_source, _node_payload, _trace

    billing = _llm_source(llm)
    check_quota(db, user, llm)
    data = store.get_document(doc_id)
    if not data:
        raise HTTPException(status_code=404, detail="文档不存在")

    state, subject = _restore_state(data, store, settings)
    feedback = payload.feedback.strip()
    # 逐项建议富化：把序号对应回校验意见的类型/引用/修复建议，模型才能逐条落实。
    issues = (state.get("critique") or {}).get("issues") or []
    issue_feedback: list[dict] = []
    for item in payload.issue_feedback:
        index = item.index
        base = issues[index] if 0 <= index < len(issues) else {}
        issue_feedback.append(
            {
                "index": index,
                "suggestion": item.suggestion,
                "type": base.get("type", ""),
                "quote": base.get("quote", ""),
                "reason": base.get("reason", ""),
                "fix": base.get("fix", ""),
            }
        )
    state["feedback"] = feedback
    state["issue_feedback"] = issue_feedback
    doc_type = state["request"]["doc_type"]

    async def event_stream():
        yield _sse(
            "start",
            {
                "doc_type": doc_type,
                "document_id": doc_id,
                "version": data["meta"].get("version", 1),
                "nodes": NODE_LABELS,
            },
        )
        try:
            # 应用建议的起点事件：让用户在轨迹里看到这一轮改了什么、为什么改。
            advised = len(issue_feedback)
            detail = f"{advised} 条待核项已给出逐项建议"
            if feedback:
                detail += "，另附整体补充说明"
            start_event = {
                "node": "regenerate",
                "summary": f"已接收用户审核建议（{detail}），开始修订当前版本",
                "at": nodes._now(),
            }
            state["events"] = state["events"] + [start_event]
            yield _sse("node", _node_payload("regenerate", {"events": [start_event]}))

            # 用户已驱动修订：按建议修一轮后只复检一次并呈现剩余问题，不再自动多轮修订，
            # 避免把用户已裁决的条目反复重新提出；事实安全级别的硬错误仍由复检照常报出。
            # （无用户反馈的纯自修复走下方 while 循环，与初生成保持一致。）
            state["revision_count"] = 0
            update = await nodes.revise(state, llm=llm)
            merge_updates(state, update)
            yield _sse("node", _node_payload(nodes.revise.__name__, update))
            has_user_feedback = bool(feedback.strip()) or any(
                str(item.get("suggestion") or "").strip() for item in issue_feedback
            )
            if has_user_feedback:
                update = await nodes.verify(state, llm=llm)
                merge_updates(state, update)
                yield _sse("node", _node_payload(nodes.verify.__name__, update))
            else:
                while True:
                    update = await nodes.verify(state, llm=llm)
                    merge_updates(state, update)
                    yield _sse("node", _node_payload(nodes.verify.__name__, update))
                    if nodes.should_revise(state, settings=settings) != "revise":
                        break
                    update = await nodes.revise(state, llm=llm)
                    merge_updates(state, update)
                    yield _sse("node", _node_payload(nodes.revise.__name__, update))
            update = await nodes.finalize(state)
            merge_updates(state, update)
            yield _sse("node", _node_payload(nodes.finalize.__name__, update))

            final = state.get("final") or ""
            if not final.strip():
                raise RuntimeError("重新生成结果为空，未保存")

            trace = _trace(state, state["request"], getattr(llm, "settings", settings))
            trace["subject"] = subject
            trace["feedback"] = feedback
            trace["issue_feedback"] = issue_feedback
            # 评分变化：让用户一眼看到这一轮按建议修订后质量是升是降。
            new_score = (state.get("critique") or {}).get("score")
            old_score = state.get("previous_score")
            trace["previous_score"] = old_score
            trace["score_delta"] = (
                max(0, int(new_score) - int(old_score))
                if isinstance(new_score, (int, float)) and isinstance(old_score, (int, float))
                else None
            )
            meta = store.update_document(doc_id, final, trace=trace)
            _log_generation(user.id, doc_type, document_id=doc_id, llm_source=billing)
            yield _sse("done", {"document": meta})
        except Exception as exc:  # noqa: BLE001 - 把失败推送给前端
            _log_generation(
                user.id, doc_type, document_id=doc_id, status="error", error=str(exc),
                llm_source=billing,
            )
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
