# -*- coding: utf-8 -*-
"""AppliCraft 知识库检索器（RAG 召回层）。

设计取舍
--------
DeepSeek 不提供 embedding 端点，本阶段用「轻量词法召回 + 项目 / 学校强匹配」
作为 RAG 的检索实现：零额外依赖、可离线运行，且对「港大 CS」「NUS 数据科学」
这类短项目名查询效果稳定。后续若接入任意 OpenAI 兼容 embedding 服务，只需把
retrieve() 内的排序替换为向量相似度，外层（提示词注入、审核比对）无需改动。

行为约束
--------
1. 只召回 meta.suitable_for_writing = true 的分块（课程 / 特色 / 文书要点 / 概览），
   绝不把学费、截止日期、语言分数等易过期数字喂给文书生成。
2. 只有明确指定了「目标项目」且能在库中匹配到学校 / 项目时，才注入资料；
   目标项目不在覆盖范围内（如英美项目）时安全降级为空，绝不注入无关项目资料。
3. 命中分块优先按与目标查询的相关度排序，再用字符预算截断，避免提示词过长。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings

# 学校缩写 → 可用于英文查询命中的关键词（覆盖申请人自由填写的校名写法）。
SCHOOL_KEYWORDS: dict[str, list[str]] = {
    "HKU": ["hong kong", "hku", "hk"],
    "CUHK": ["chinese university", "cuhk"],
    "HKUST": ["hong kong university of science", "hkust"],
    "NUS": ["national university of singapore", "nus"],
    "NTU": ["nanyang", "ntu"],
}


# 学位 / 套话前缀（最长优先剥离），用于把「Master of Science in Computer Science (MSc(CompSc))」
# 与申请人填写的「MSc in Computer Science」归一化到同一学科核心「computer science」。
_DEGREE_PREFIXES = [
    "master of science in",
    "master of science",
    "master of",
    "msc in",
    "m.sc in",
    "msc",
    "m.sc",
    "meng",
    "mcomp",
    "mstat",
    "mdasc",
    "msba",
    "mfe",
]
_DISCIPLINE_STOP = {
    "in",
    "of",
    "and",
    "the",
    "with",
    "a",
    "an",
    "for",
    "stream",
    "streams",
    "general",
    "track",
    "tracks",
    "specialisation",
    "specialization",
    "concentration",
    "concentrations",
    "program",
    "programme",
    "degree",
    "graduate",
    "postgraduate",
}


def _normalize_discipline(text: str) -> str:
    """剥离学位前缀与套话，得到学科核心词串，如「computer science」「artificial intelligence」。

    用于桥接「官方长名」与「申请人简写」：两者归一化后若互相包含即视为同一项目。
    """
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"\([^)]*\)", " ", t)  # 去掉括号及括号内（如 MSc(CompSc)）
    for p in sorted(_DEGREE_PREFIXES, key=len, reverse=True):
        if t.startswith(p):
            t = t[len(p):]
            break
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    toks = [w for w in t.split() if w not in _DISCIPLINE_STOP and len(w) > 1]
    return " ".join(toks)


def _name_match(c: dict[str, Any], program_name: str) -> bool:
    """项目匹配：字面双向包含，或学科归一化后互相包含（桥接官方长名与申请人简写）。"""
    meta = c.get("meta") or {}
    pn = program_name.lower()
    if not pn:
        return False
    pn_disc = _normalize_discipline(pn)
    for name in (meta.get("program_name_en", ""), meta.get("program_name_zh", "")):
        if not name:
            continue
        nl = name.lower()
        if nl in pn or pn in nl:
            return True
        nl_disc = _normalize_discipline(nl)
        if pn_disc and nl_disc and (pn_disc in nl_disc or nl_disc in pn_disc):
            return True
    return False


def _detect_school(text: str) -> str:
    """从查询文本里识别学校缩写（HKUST/NTU/HKU/CUHK/NUS）。

    优先匹配更具体的缩写，避免「hk」误命中「hkust」这类子串包含导致的串校。
    识别不到时返回空串（交由名称匹配跨校回退）。
    """
    text = (text or "").lower()
    if not text:
        return ""
    # 把更具体的学校放在前面，先匹配长缩写 / 专有词，减少歧义：
    # 例如「香港中文大学」全名含「hong kong」，须在 HKU 之前用「chinese university」判定为 CUHK，
    # 否则会被 HKU 的「hong kong」误命中。
    for sid in ("HKUST", "CUHK", "HKU", "NTU", "NUS"):
        if any(kw in text for kw in SCHOOL_KEYWORDS.get(sid, [])):
            return sid
    return ""


@dataclass
class KnowledgeRef:
    """一次检索的结构化结果，供提示词注入与前端展示复用。"""

    context: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)
    matched_program: str = ""
    context_chars: int = 0
    enabled: bool = False
    note: str = ""


def _tokenize(text: str) -> set[str]:
    """轻量分词：英文按单词，中文按单字 + 相邻双字，无第三方依赖。"""
    text = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", text))
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.update(seg)
        tokens.update(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


def _score(query_tokens: set[str], content: str) -> float:
    """加权关键词打分：英文词 / 中文双字词权重高，中文单字权重低，长文本做长度惩罚。"""
    if not query_tokens:
        return 0.0
    c_tokens = _tokenize(content)
    total = 0.0
    for token in query_tokens:
        if token not in c_tokens:
            continue
        if re.fullmatch(r"[a-z0-9]{2,}", token):
            total += 2.0
        elif len(token) == 2 and all("\u4e00" <= ch <= "\u9fff" for ch in token):
            total += 1.5
        else:
            total += 0.25
    return total / (1 + 0.0012 * len(content))


class KnowledgeRetriever:
    def __init__(
        self,
        knowledge_dir: Path,
        enabled: bool = True,
        top_k: int = 6,
        max_chars: int = 2600,
    ) -> None:
        self.knowledge_dir = Path(knowledge_dir)
        self.enabled = enabled
        self.top_k = top_k
        self.max_chars = max_chars
        self._chunks: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        if self._chunks is not None:
            return self._chunks
        path = self.knowledge_dir / "chunks.jsonl"
        chunks: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._chunks = chunks
        return chunks

    def available(self) -> bool:
        return self.enabled and len(self._load()) > 0

    def retrieve(
        self,
        target: dict[str, Any] | None,
        request: dict[str, Any],
        career_goal: str = "",
    ) -> KnowledgeRef:
        if not self.enabled:
            return KnowledgeRef(enabled=False, note="RAG 未启用")

        chunks = self._load()
        if not chunks:
            return KnowledgeRef(enabled=False, note="知识库文件缺失，未注入官方资料")

        # 只召回适合文书生成的写作素材分块。
        writing = [c for c in chunks if (c.get("meta") or {}).get("suitable_for_writing")]
        if not writing:
            return KnowledgeRef(enabled=True, note="知识库无可写作分块")

        # 未指定目标项目时不注入，避免无关项目资料误导生成。
        if not target:
            return KnowledgeRef(enabled=True, note="未指定目标项目，未注入官方资料")

        program_name = " ".join(
            str(target.get(k, "")) for k in ("program", "university", "degree_type")
        ).strip()
        emphasis = " ".join(request.get("emphasis") or [])
        query = " ".join(x for x in (program_name, emphasis, career_goal) if x).strip()
        q_tokens = _tokenize(query)

        target_school = _detect_school(program_name)

        def _chunk_school(c: dict[str, Any]) -> str:
            return (c.get("meta") or {}).get("school_id", "").upper()

        program_hits = [
            c
            for c in writing
            if _name_match(c, program_name)
            and (not target_school or _chunk_school(c) == target_school)
        ]
        # 仅当能识别到具体学校、且项目名称未命中时，才退到学校级匹配（同校其它项目），
        # 避免把其它学校的同名项目（如港大 / 中文大学的 MSc in Computer Science）串味注入。
        school_hits = [
            c
            for c in writing
            if not _name_match(c, program_name) and target_school and _chunk_school(c) == target_school
        ]
        matched = program_hits or school_hits
        if not matched:
            return KnowledgeRef(
                enabled=True,
                note=f"目标项目不在知识库覆盖范围内（{program_name or '未命名项目'}），未注入官方资料",
            )

        # 在命中分块内按与目标查询的相关度排序，取前 top_k。
        matched.sort(key=lambda c: _score(q_tokens, c.get("content", "")), reverse=True)
        selected = matched[: self.top_k]

        # 字符预算：优先保留相关度更高的分块，截断到 max_chars。
        kept: list[dict[str, Any]] = []
        used = 0
        for c in selected:
            content = c.get("content", "")
            if used and used + len(content) > self.max_chars:
                continue
            kept.append(c)
            used += len(content)
        if not kept:
            kept = selected[:1]

        context_parts: list[str] = []
        seen_sources: list[dict[str, str]] = []
        for c in kept:
            meta = c.get("meta") or {}
            context_parts.append(c.get("content", ""))
            urls = meta.get("official_urls") or []
            src = {
                "school": meta.get("school_name_zh") or meta.get("school_id") or "",
                "program": meta.get("program_name_en") or meta.get("program_name_zh") or "",
                "field": meta.get("field_label") or meta.get("field") or "",
                "url": urls[0] if urls else "",
            }
            if not any(s["url"] == src["url"] and s["program"] == src["program"] for s in seen_sources):
                seen_sources.append(src)

        context = "\n\n".join(context_parts)
        matched_program = (
            (kept[0].get("meta") or {}).get("program_name_en")
            if program_hits
            else ((kept[0].get("meta") or {}).get("school_name_zh") or program_name or "")
        )
        return KnowledgeRef(
            context=context,
            sources=seen_sources,
            matched_program=matched_program,
            context_chars=len(context),
            enabled=True,
            note="",
        )


_RETRIEVER: "KnowledgeRetriever | None" = None


def get_retriever(settings: Settings) -> KnowledgeRetriever:
    """进程内复用单例；配置在启动时即固定，无需每次重建。"""
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = KnowledgeRetriever(
            knowledge_dir=settings.knowledge_dir,
            enabled=settings.rag_enabled,
            top_k=settings.rag_top_k,
            max_chars=settings.rag_max_chars,
        )
    return _RETRIEVER
