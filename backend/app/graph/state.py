"""LangGraph 状态定义，由所有文书生成节点共享。"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class GraphState(TypedDict, total=False):
    profile: dict[str, Any]
    request: dict[str, Any]
    facts: dict[str, Any]
    facts_text: str
    system_prompt: str
    outline: list[dict[str, Any]]
    draft: str
    critique: dict[str, Any]
    revision_count: int
    # 自修复版本择优：本轮评分最高的正文 / 校验快照；复检分低于它时回滚或托底，
    # 保证「自修复后分数不倒退」且交付的是评分最高的那一版。
    best_snapshot: dict[str, Any]
    regressed: bool
    score_history: list[int]
    previous_score: int | None
    final: str
    # 用户审核建议（按建议重新生成时由接口写入，revise 节点消费）。
    feedback: str
    issue_feedback: list[dict[str, Any]]
    # 上一轮校验意见（revise 写入修订前的问题清单，verify 复检时做"已解决/仍存在"对照）。
    previous_issues: list[dict[str, Any]]
    # RAG：注入提示词的项目官方资料与来源（由 intake 计算）。
    knowledge_context: str
    knowledge_sources: list[dict[str, str]]
    knowledge: dict[str, Any]
    # 用户参考文档：生成时勾选的本人上传材料，作为补充背景注入。
    reference_context: str
    reference_meta: list[dict[str, Any]]
    # 写作技能：Skill 市场勾选的方法论约束（不构成申请人事实）。
    skill_context: str
    skill_meta: list[dict[str, Any]]
    events: Annotated[list[dict[str, Any]], operator.add]
    warnings: Annotated[list[str], operator.add]
