"""编译 LangGraph 文书生成工作流。"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.config import Settings
from app.graph import nodes
from app.graph.state import GraphState
from app.llm.client import LLMClient

# GraphState 中使用 operator.add 归约器的字段（需要累加而非覆盖）。
REDUCED_KEYS = {"events", "warnings"}


def build_graph(llm: LLMClient, settings: Settings):
    builder = StateGraph(GraphState)
    builder.add_node("intake", partial(nodes.intake, settings=settings))
    builder.add_node("outline", partial(nodes.outline, llm=llm))
    builder.add_node("draft", partial(nodes.draft, llm=llm))
    builder.add_node("cv_render", partial(nodes.cv_render, llm=llm))
    builder.add_node("verify", partial(nodes.verify, llm=llm))
    builder.add_node("revise", partial(nodes.revise, llm=llm))
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "intake")
    builder.add_conditional_edges(
        "intake",
        nodes.route_by_doc_type,
        {"cv": "cv_render", "narrative": "outline"},
    )
    builder.add_edge("cv_render", "verify")
    builder.add_edge("outline", "draft")
    builder.add_edge("draft", "verify")
    builder.add_conditional_edges(
        "verify",
        partial(nodes.should_revise, settings=settings),
        {"revise": "revise", "finalize": "finalize"},
    )
    # 自我修复循环：修订后必须回到 verify 复检，修好了才定稿；
    # 复检仍有问题且未达 max_revisions 时继续自修复，超限则带着剩余意见交给人工复核。
    builder.add_edge("revise", "verify")
    builder.add_edge("finalize", END)
    return builder.compile()


def initial_state(profile: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": profile,
        "request": request,
        "facts": {},
        "facts_text": "",
        "system_prompt": "",
        "outline": [],
        "draft": "",
        "critique": {},
        "revision_count": 0,
        "previous_issues": [],
        "final": "",
        "knowledge_context": "",
        "knowledge_sources": [],
        "knowledge": {},
        "events": [],
        "warnings": [],
    }


def merge_updates(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """把 LangGraph 'updates' 流分片累加进普通状态字典。"""
    for key, value in update.items():
        if key in REDUCED_KEYS:
            state.setdefault(key, []).extend(value or [])
        else:
            state[key] = value
    return state
