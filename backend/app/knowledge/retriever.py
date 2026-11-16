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
   目标项目不在覆盖范围内时安全降级为空，绝不注入无关项目资料。
3. 命中分块优先按与目标查询的相关度排序，再用字符预算截断，避免提示词过长。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings

# 学校缩写 → 中英文校名 / 简称关键词。
# 注意：系统项目库与选校评估导入档案时，university 写的是「香港科技大学」这类中文名，
# 早期只认英文缩写，学校识别会直接失败：轻则报「不在覆盖范围内」，重则把同名项目
# 的其它学校资料串味注入。CITYU / POLYU 也在知识库内，必须一并识别。
SCHOOL_KEYWORDS: dict[str, list[str]] = {
    "HKUST": ["hong kong university of science", "hkust", "香港科技大学", "香港科大", "港科大"],
    "CUHK": ["chinese university of hong kong", "cuhk", "香港中文大学", "香港中大", "港中文", "中大"],
    "HKU": ["university of hong kong", "hku", "香港大学", "港大"],
    "CITYU": ["city university of hong kong", "cityu", "香港城市大学", "香港城大", "港城大", "城大"],
    "POLYU": ["hong kong polytechnic university", "polyu", "香港理工大学", "香港理工", "港理工"],
    "NUS": ["national university of singapore", "nus", "新加坡国立大学", "新国大"],
    "NTU": ["nanyang technological university", "ntu", "南洋理工大学", "南洋理工"],
    "IMPERIAL": ["imperial college london", "imperial college", "帝国理工学院", "帝国理工"],
    "UCL": ["university college london", "ucl", "伦敦大学学院", "ucl 学院"],
    "EDIN": ["university of edinburgh", "edinburgh", "爱丁堡大学", "爱丁堡"],
    "MELBOURNE": ["university of melbourne", "melbourne", "墨尔本大学", "墨尔本"],
    "UNSW": ["unsw sydney", "new south wales", "unsw", "新南威尔士大学", "新南威尔士"],
    "SYDNEY": ["university of sydney", "sydney", "悉尼大学", "悉尼"],
}

# 学校判定按「关键词长度降序」全局匹配：不能再按学校顺序逐个试，
# 否则 "Hong Kong Polytechnic University" 会先被 HKU 的 "hong kong" 抢走，
# "hkust" 也会被 "hku" 抢走。
_SCHOOL_PATTERNS: list[tuple[str, str]] = sorted(
    ((kw, sid) for sid, kws in SCHOOL_KEYWORDS.items() for kw in kws),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


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


# 中文项目名清洗：官方中文名带「（非官方译名）」这类校验注记，
# 而档案里 project 字段已去掉该注记；双向字面包含会因此永远不相等。
_ZH_NOISE = re.compile(r"[（(][^）)]*[）)]|\s+|[·・,，、/\\\-—_:：;；.。]")
_ZH_CHAR = re.compile(r"[\u4e00-\u9fff]")


def _clean_zh_name(text: str) -> str:
    return _ZH_NOISE.sub("", (text or "").lower())


def _name_match(c: dict[str, Any], program_name: str) -> bool:
    """项目匹配：中英文字面双向包含，或学科归一化后互相包含。

    支持三种写法：官方英文长名、申请人英文简写、系统项目库导入的中文名
    （如「人工智能理学硕士 香港科技大学」）。
    """
    meta = c.get("meta") or {}
    pn = program_name.lower()
    if not pn:
        return False
    pn_disc = _normalize_discipline(pn)
    pn_zh = _clean_zh_name(program_name) if _ZH_CHAR.search(program_name) else ""
    for name in (meta.get("program_name_en", ""), meta.get("program_name_zh", "")):
        if not name:
            continue
        nl = name.lower()
        if nl in pn or pn in nl:
            return True
        nl_disc = _normalize_discipline(nl)
        if pn_disc and nl_disc and (pn_disc in nl_disc or nl_disc in pn_disc):
            return True
        # 中文名：去掉括号注记 / 标点 / 空白后双向包含。
        # 限长 4 字以上，避免「AI」「CS」之类极短片段误命中。
        if pn_zh and _ZH_CHAR.search(nl):
            nl_zh = _clean_zh_name(nl)
            if len(nl_zh) >= 4 and (nl_zh in pn_zh or pn_zh in nl_zh):
                return True
    return False


def _detect_school(text: str) -> str:
    """从查询文本里识别学校缩写（支持中英文校名与简称）。

    按关键词长度降序全局匹配：长而具体的校名优先，避免
    「香港中文大学」被「港大」类短词、或 "Polytechnic" 被 "hong kong" 抢先误判。
    识别不到时返回空串。
    """
    text = (text or "").lower()
    if not text:
        return ""
    for kw, sid in _SCHOOL_PATTERNS:
        if kw in text:
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

        # 从系统项目库 / 选校评估导入的条目带知识库 program_id，优先精确命中：
        # 不受申请人把项目名写成中文、简写或改了校名写法的影响。
        source_id = str(target.get("source_program_id") or "").strip()
        exact_hits = [
            c
            for c in writing
            if source_id and (c.get("meta") or {}).get("program_id") == source_id
        ]
        exact_used = bool(exact_hits) and (
            not target_school or all(_chunk_school(c) == target_school for c in exact_hits)
        )
        if exact_used:
            program_hits = exact_hits
        else:
            program_hits = [
                c
                for c in writing
                if _name_match(c, program_name)
                and (not target_school or _chunk_school(c) == target_school)
            ]

        # 名称命中多所学校的同名项目、又无法判定目标学校时，宁可不注入：
        # 不能把港大 / 中大 / NUS 的课程资料混进同一篇 PS。
        hit_schools = {_chunk_school(c) for c in program_hits if _chunk_school(c)}
        if not exact_used and not target_school and len(hit_schools) > 1:
            return KnowledgeRef(
                enabled=True,
                note=(
                    f"「{program_name or '未命名项目'}」在知识库中对应多所学校的同名项目，未注入官方资料；"
                    "请在档案的目标项目里补充学校名称，或从参考文档库重新导入该项目"
                ),
            )

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
