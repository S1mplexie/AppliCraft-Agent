# -*- coding: utf-8 -*-
"""AppliCraft 知识库本地检索 CLI（不依赖向量库，供未接 RAG 前取参考素材）。

示例：
  python knowledge/query.py --school HKU --field writing_hooks
  python knowledge/query.py --query "AI 伦理 计算机视觉" --writing-only
  python knowledge/query.py --id hkust-msc-ai --field curriculum
  python knowledge/query.py --list

输出为纯文本，可直接贴到生成面板的「补充说明」，或作为后续 RAG 接入时的召回基线。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHUNKS = ROOT / "chunks.jsonl"
INDEX = ROOT / "index.json"


def tokenize(text: str) -> list[str]:
    """轻量分词：英文按单词，中文按单字 + 相邻双字，便于无第三方依赖的关键词召回。"""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]{2,}", text)
    han = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in han:
        tokens.extend(list(seg))
        tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


def load_chunks() -> list[dict]:
    if not CHUNKS.exists():
        raise SystemExit("找不到 chunks.jsonl，请先运行 python knowledge/build.py")
    return [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]


def score(query: str, content: str) -> float:
    """加权关键词打分：英文词 / 中文双字词权重高，中文单字权重低。

    单字命中太容易（「的」「学」等），若不降权会把整库都召回；
    长文本另做长度惩罚，避免长块只因词多而胜出。
    """
    q_tokens = set(tokenize(query))
    if not q_tokens:
        return 0.0
    c_tokens = set(tokenize(content))
    total = 0.0
    for token in q_tokens:
        if token not in c_tokens:
            continue
        if re.fullmatch(r"[a-z0-9]{2,}", token):
            total += 2.0
        elif len(token) == 2 and all("\u4e00" <= ch <= "\u9fff" for ch in token):
            total += 1.5
        else:
            total += 0.25
    return total / (1 + 0.0012 * len(content))


def main() -> None:
    parser = argparse.ArgumentParser(description="检索 AppliCraft 项目知识库")
    parser.add_argument("--school", help="学校缩写，如 HKU / CUHK / HKUST / NUS / NTU")
    parser.add_argument("--field", help="字段组，如 writing_hooks / curriculum / highlights_career")
    parser.add_argument("--id", help="项目 ID，如 hkust-msc-ai")
    parser.add_argument("--query", help="关键词，如 'AI 伦理 计算机视觉'")
    parser.add_argument("--writing-only", action="store_true", help="只返回适合文书生成的分块")
    parser.add_argument("--limit", type=int, default=5, help="返回条数，默认 5")
    parser.add_argument("--list", action="store_true", help="列出全部项目 ID 与名称")
    args = parser.parse_args()

    if args.list:
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        for p in index["programs"]:
            print(f"{p['id']:45s} {p['school_id']:6s} {p['name_en']}")
        print(f"共 {len(index['programs'])} 个项目")
        return

    chunks = load_chunks()
    school = args.school.upper() if args.school else None
    candidates = [
        c for c in chunks
        if (not school or c["meta"]["school_id"].upper() == school)
        and (not args.field or c["meta"]["field"] == args.field)
        and (not args.id or c["meta"]["program_id"] == args.id)
        and (not args.writing_only or c["meta"]["suitable_for_writing"])
    ]

    if args.query:
        ranked = sorted(
            ((score(args.query, c["content"]), c) for c in candidates),
            key=lambda pair: pair[0], reverse=True,
        )
        candidates = [c for s, c in ranked if s >= 1.0]
    else:
        # 无关键词时按 学校 → 项目 → 字段组 稳定排序
        candidates.sort(key=lambda c: (
            c["meta"]["school_id"], c["meta"]["program_id"], c["meta"]["field"]
        ))

    if not candidates:
        print("没有命中。可用 --list 查看项目 ID，或用 --field 指定字段组。")
        return

    print(f"命中 {len(candidates)} 块，展示前 {min(args.limit, len(candidates))} 块：\n")
    for c in candidates[: args.limit]:
        meta = c["meta"]
        tags = f"[{meta['school_id']}] {meta['program_name_en'] or meta['program_id']} · {meta['field_label']}"
        if meta["suitable_for_writing"]:
            tags += " · 可用于文书"
        if meta["has_unverified"]:
            tags += " · 含待核实内容"
        print("=" * 78)
        print(tags)
        print("-" * 78)
        print(c["content"])
        print(f"来源：{c['source']}")
        print()
    remaining = len(candidates) - args.limit
    if remaining > 0:
        print(f"（还有 {remaining} 块未展示，可加大 --limit）")


if __name__ == "__main__":
    main()
