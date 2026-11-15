"""中英对照译块（`> 译：...`）的确定性补全与剥离。

背景：模型在起草时会给正文段落写译块，却经常漏掉 `## 小标题`（尤其是 PS，
它把大纲 title 当作结构原样照搬），也可能漏译个别段落 / 列表项。前端的对照
视图只把「英文块 + 紧邻译块」配成左右双栏，缺译块的结构会整宽显示、没有中文。

这里在定稿时做一次确定性检查：找出所有「后面没有紧跟译块」的英文块，
用一次 LLM 调用批量翻译并插入译块，从而在机制上保证双语文书逐块有中文对照。
翻译失败时原样返回，绝不让对照译文影响正文或拖垮整次生成。
"""
from __future__ import annotations

import re
from typing import Any

ZH_LINE = re.compile(r"^\s*>\s*译[:：]")
QUOTE_LINE = re.compile(r"^\s*>")

TRANSLATE_SYSTEM = """你是研究生申请文书的中英对照译者。输入是若干条「尚未配中文对照」的英文片段，可能包含小标题、正文段落、列表项或署名块。请逐条翻译成简体中文。

规则：
- 忠实对应原文，不增删事实、不扩写、不评论、不总结；小标题译成简短中文标题，不要追加解释。
- 专有名词、学校 / 项目 / 课程 / 机构 / 工具名、数字、GPA、日期以及 [TO CONFIRM: ...] 占位符一律原样保留。
- 可保留原文的 `-` 列表符与 `**` 强调标记；不要输出 `##` 标题符、`>` 引用符或 `> 译：` 前缀。
- 译文写成单行纯文本，不要换行。
- 只返回一个 JSON 对象：键为输入编号的字符串（"1"、"2"…），值为该条的中文译文。不要返回数组、嵌套对象或任何解释文字。"""

TRANSLATE_SLUG = "把以下英文片段逐条译成中文，按编号返回 JSON：\n\n"


def split_blocks(md: str) -> list[str]:
    """按行扫描切块，口径与前端 DocumentViewer._splitBilingualBlocks 一致。

    译块以 `> 译：` 起始、可带 `> ` 多行续行；无论前后有没有空行都单独成块。
    这样既能处理规范排布，也能处理模型把译块紧贴英文行的紧凑写法。
    """
    blocks: list[str] = []
    buf: list[str] = []
    in_zh = False

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            blocks.append(text)
        buf.clear()

    for line in (md or "").replace("\r\n", "\n").split("\n"):
        if ZH_LINE.match(line):
            flush()
            in_zh = True
            buf.append(line)
        elif in_zh and QUOTE_LINE.match(line):
            buf.append(line)
        else:
            if in_zh:
                flush()
                in_zh = False
            if not line.strip():
                flush()
            else:
                buf.append(line)
    flush()
    return blocks


def is_zh_block(block: str) -> bool:
    return bool(ZH_LINE.match(block or ""))


def strip_translation_blocks(md: str) -> str:
    """移除所有译块（含 `> ` 多行续行），得到纯英文递交正文。"""
    out: list[str] = []
    skipping = False
    for line in (md or "").replace("\r\n", "\n").split("\n"):
        if ZH_LINE.match(line):
            skipping = True
            continue
        if skipping and QUOTE_LINE.match(line):
            continue
        skipping = False
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out).strip())


def _needs_translation(block: str) -> bool:
    """纯译块、分隔线、围栏等结构不需要配译块。"""
    if not block or is_zh_block(block):
        return False
    if re.fullmatch(r"[-*_=\s]{3,}", block):
        return False
    return True


def missing_translation_blocks(md: str) -> list[tuple[int, str]]:
    """返回 (块序号, 英文原文)，这些块后面没有紧跟译块。"""
    blocks = split_blocks(md)
    missing: list[tuple[int, str]] = []
    for i, block in enumerate(blocks):
        if not _needs_translation(block):
            continue
        nxt = blocks[i + 1] if i + 1 < len(blocks) else ""
        if is_zh_block(nxt):
            continue
        missing.append((i, block))
    return missing


def _clean_zh(text: str, original: str) -> str:
    """归一化模型返回的译文：去编号 / 去引用前缀 / 压成单行，并做基本合理性检查。"""
    zh = (text or "").strip()
    zh = re.sub(r"^\[?\d+\]?\s*", "", zh)
    zh = re.sub(r"^\s*>\s*译[:：]\s*", "", zh)
    zh = re.sub(r"^\s*>\s?", "", zh, flags=re.M)
    zh = re.sub(r"\s+", " ", zh).strip()
    # 不含汉字（模型直接复述英文）、或异常冗长（复述整篇）都视为无效，宁可留空。
    if not zh or not re.search(r"[\u4e00-\u9fff]", zh):
        return ""
    if len(zh) > max(240, len(original)):
        return ""
    return zh


def _parse_translations(data: Any, count: int) -> dict[int, str]:
    """宽容解析：支持 {"1": "…"} / {"translations": {...}} / ["…"] / [{"zh": "…"}]。"""
    obj = data
    if isinstance(obj, dict):
        for key in ("translations", "items", "results"):
            if isinstance(obj.get(key), (dict, list)):
                obj = obj[key]
                break
    result: dict[int, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            token = str(key).strip().strip("[]")
            if not token.isdigit() or not isinstance(value, str):
                continue
            idx = int(token) - 1
            if 0 <= idx < count:
                result[idx] = value
    elif isinstance(obj, list):
        for i, value in enumerate(obj[:count]):
            if isinstance(value, str):
                result[i] = value
            elif isinstance(value, dict):
                for key in ("zh", "translation", "text", "译文"):
                    if isinstance(value.get(key), str):
                        result[i] = value[key]
                        break
    return result


async def ensure_translation_blocks(md: str, llm: Any) -> tuple[str, dict[str, Any]]:
    """为每个缺译块的英文块补上 `> 译：...`。

    返回 (新正文, 统计信息)。任何异常都吞掉并原样返回：对照译文是辅助内容，
    绝不能因为补译失败导致文书生成失败或正文被破坏。
    """
    missing = missing_translation_blocks(md)
    if not missing:
        return md, {"added": 0, "failed": False, "missing": 0}
    if llm is None:
        return md, {"added": 0, "failed": True, "missing": len(missing)}
    numbered = "\n\n".join(f"[{i}] {text}" for i, (_, text) in enumerate(missing, 1))
    try:
        data = await llm.complete_json(
            task="bilingual_fill",
            system=TRANSLATE_SYSTEM,
            user=TRANSLATE_SLUG + numbered,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001 - 补译失败不影响交付
        return md, {"added": 0, "failed": True, "missing": len(missing)}
    parsed = _parse_translations(data, len(missing))
    filled: dict[int, str] = {}
    for seq, (block_index, original) in enumerate(missing):
        zh = _clean_zh(parsed.get(seq, ""), original)
        if zh:
            filled[block_index] = zh
    if not filled:
        return md, {"added": 0, "failed": True, "missing": len(missing)}
    blocks = split_blocks(md)
    out: list[str] = []
    for i, block in enumerate(blocks):
        out.append(block)
        if i in filled:
            out.append(f"> 译：{filled[i]}")
    return "\n\n".join(out) + "\n", {
        "added": len(filled), "failed": False, "missing": len(missing),
    }
