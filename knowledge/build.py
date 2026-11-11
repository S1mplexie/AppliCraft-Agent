# -*- coding: utf-8 -*-
"""把 _raw/ 下各校的原始调研 JSON 编译成 AppliCraft 初始知识库。

产出（全部落在 knowledge/ 目录）：
  programs/<学校>/<项目>.md   人读项目卡片，带 frontmatter 元数据
  index.json                   项目级索引，机器可读
  chunks.jsonl                 RAG 分块，每行一条；meta 与后端 knowledge_chunks 表对齐
  INDEX.md                     知识库总索引、数据纪律与后续接入说明

设计要点：
  1. 每个项目按「字段组」切成 7 个自包含分块，块首带学校/项目名，便于向量检索命中。
  2. meta.suitable_for_writing 标记该块是否适合直接喂给文书生成：
     课程、特色、文书要点 = true；学费/截止/待核实清单 = false。
     这样后续接 RAG 时可以只召回写作素材，避免把易过期的数字写进 PS。
  3. 官网未核实的信息统一保留「待核实」字样，不参与生成，也不做推测填充。

用法：python knowledge/build.py
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "_raw"
PROGRAM_DIR = ROOT / "programs"
INDEX_JSON = ROOT / "index.json"
CHUNKS_JSONL = ROOT / "chunks.jsonl"
INDEX_MD = ROOT / "INDEX.md"

# 字段组 → 是否适合作为文书生成的直接素材
FIELD_GROUPS = [
    ("overview", "项目概览", True),
    ("tuition_application", "学费与申请时间", False),
    ("admission", "录取要求", False),
    ("curriculum", "课程结构", True),
    ("highlights_career", "项目特色与就业", True),
    ("writing_hooks", "文书参考要点", True),
    ("verification_sources", "核实状态与来源", False),
]


# 官方域名后缀白名单：知识库事实字段只允许来自这些域名。
OFFICIAL_SUFFIXES = (
    "hku.hk", "cuhk.edu.hk", "hkust.edu.hk", "ust.hk",
    "nus.edu.sg", "ntu.edu.sg",
)

# 原始调研报告里带过内部来源编号（如「（U2）」「U1–U36」），
# 而最终卡片用 sources 表列 URL，这类悬空引用需在编译期清掉。
BRACKETED_REF = re.compile(
    r"[（(]\s*U\d+(?:\s*[/、,，–—-]\s*U?\d+)*\s*[）)]"
)
BARE_REF = re.compile(
    r"(?<![A-Za-z0-9])U\d+(?:\s*[/、,，–—-]\s*U?\d+)*(?![A-Za-z0-9])"
)


def clean(value):
    """递归清洗原始资料中的悬空内部引用编号，不影响事实字段本身。"""
    if isinstance(value, str):
        text = BRACKETED_REF.sub("", value)
        text = BARE_REF.sub("", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\s+([，。；、）])", r"\1", text)
        text = re.sub(r"（\s*[/、,，–—\-]*\s*）|\(\s*[/、,，–—\-]*\s*\)", "", text)
        return text.strip()
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    return value


def validate_sources(school: dict) -> list[str]:
    """校验该校所有来源 URL 是否属于官方域名，返回不合规 URL 列表。"""
    bad = []
    for p in school.get("programs", []):
        urls = as_list(p.get("official_urls"))
        urls += [
            s.get("url", "") for s in (p.get("sources") or [])
            if isinstance(s, dict)
        ]
        for url in urls:
            netloc = urlparse(url).netloc.lower()
            if not any(netloc == d or netloc.endswith("." + d) for d in OFFICIAL_SUFFIXES):
                bad.append(url)
    return bad


def as_list(value) -> list:
    """把可能是字符串 / 列表 / None 的字段统一成列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)]


def esc(value) -> str:
    """表格单元格转义：换行转 <br>，竖线转义，避免破坏 Markdown 表格。"""
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def bullets(values, empty: str = "暂无") -> str:
    items = as_list(values)
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def indented_bullets(values, empty: str = "无") -> str:
    """嵌套在上级列表项下的子列表，缩进两空格避免 Markdown 断行。"""
    text = bullets(values, empty=empty)
    return "\n".join("  " + line for line in text.splitlines())


def table(rows: list[tuple[str, object]]) -> str:
    out = ["| 字段 | 内容 |", "| --- | --- |"]
    for key, value in rows:
        out.append(f"| {esc(key)} | {esc(value)} |")
    return "\n".join(out)


def render_card(school: dict, p: dict) -> str:
    """渲染单个人读项目卡片（含 YAML frontmatter）。"""
    urls = as_list(p.get("official_urls"))
    fm = {
        "id": p.get("id", ""),
        "school_id": school.get("school_id", ""),
        "school_name_zh": school.get("school_name_zh", ""),
        "region": school.get("region", ""),
        "program_name_en": p.get("name_en", ""),
        "name_zh": p.get("name_zh", ""),
        "faculty": p.get("faculty", ""),
        "degree_type": p.get("degree_type", ""),
        "intake_target": school.get("intake_target", ""),
        "snapshot_date": school.get("snapshot_date", ""),
        "verification_status": (p.get("verification") or {}).get("status", ""),
        "official_urls": urls,
        "aliases": as_list(p.get("aliases")),
    }
    lines = ["---"]
    for key, value in fm.items():
        # JSON 是 YAML 的合法子集，用 dumps 保证引号与特殊字符安全
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines += ["---", ""]

    tuition = p.get("tuition") or {}
    application = p.get("application") or {}
    admission = p.get("admission") or {}
    curriculum = p.get("curriculum") or {}
    verification = p.get("verification") or {}

    lines += [
        f"# {p.get('name_en', '')}",
        "",
        f"> {p.get('name_zh', '')} ｜ {school.get('school_name_zh', '')}（{school.get('school_name_en', '')}）｜ {p.get('faculty', '')}",
        f"> 数据快照：{school.get('snapshot_date', '')} ｜ 目标入学季：{school.get('intake_target', '')} ｜ 核实状态：`{verification.get('status', '')}`",
        "",
        "## 基本信息",
        "",
        table([
            ("官方名称", p.get("name_en", "")),
            ("中文译名", p.get("name_zh", "")),
            ("学位类型", p.get("degree_type", "")),
            ("所属学院", p.get("faculty", "")),
            ("所属系 / 开办单位", p.get("department", "")),
            ("全日制学制", p.get("duration_ft", "")),
            ("兼读制学制", p.get("duration_pt", "")),
            ("学分结构", p.get("credits", "")),
            ("易混淆名称 / 旧名", "、".join(as_list(p.get("aliases"))) or "无"),
            ("官网", "、".join(urls)),
        ]),
        "",
        "## 学费与申请时间",
        "",
        table([
            ("学费", tuition.get("amount", "")),
            ("金额对应入学季", tuition.get("intake", "")),
            ("适用对象", tuition.get("applies_to", "")),
            ("补充说明", tuition.get("note", "")),
            ("申请开放", application.get("open", "")),
            ("截止 / 轮次", "；".join(as_list(application.get("deadlines")))),
            ("申请备注", application.get("note", "")),
        ]),
        "",
        "## 录取要求",
        "",
        table([
            ("语言要求", p.get("english", "")),
            ("本科背景", admission.get("background", "")),
            ("先修课 / 技能", admission.get("prerequisites", "")),
            ("GRE / GMAT", admission.get("gre_gmat", "")),
            ("工作经验", admission.get("work_experience", "")),
        ]),
        "",
        "## 课程结构",
        "",
        f"**结构说明**：{curriculum.get('structure', '')}",
        "",
        "**核心课程 / 必修**",
        "",
        bullets(curriculum.get("core")),
        "",
        "**选修课程 / 方向**",
        "",
        bullets(curriculum.get("electives")),
        "",
        "**Track / 专攻方向**",
        "",
        bullets(curriculum.get("tracks"), empty="官网未分设 track"),
        "",
        "## 项目特色与就业",
        "",
        "**项目特色**",
        "",
        bullets(p.get("highlights")),
        "",
        "**就业去向（仅官网明确表述）**",
        "",
        bullets(p.get("career")),
        "",
        "## 文书参考要点（PS / SOP）",
        "",
        bullets(p.get("writing_hooks")),
        "",
        "> 以上要点依据项目官网原文提炼，供撰写 why-this-programme / 职业规划段落时参考；"
        "不得直接照抄为个人经历，也不得把官网表述当作已核实的项目事实写入硬指标。",
        "",
        "## 核实状态与来源",
        "",
        f"- **核实状态**：`{verification.get('status', '')}`",
        "- **官网口径冲突**：",
        indented_bullets(verification.get("conflicts"), empty="无"),
        "- **待核实字段**：",
        indented_bullets(verification.get("unverified"), empty="无"),
        "",
        "**来源清单**",
        "",
        "| 官方 URL | 支撑字段 |",
        "| --- | --- |",
    ]
    sources = p.get("sources") or []
    if isinstance(sources, dict):
        sources = [sources]
    for src in sources:
        if not isinstance(src, dict):
            continue
        lines.append(f"| {esc(src.get('url', ''))} | {esc(src.get('supports', ''))} |")
    lines += [
        "",
        "> 学费、截止日期与语言分数会随入学季更新，提交申请前务必以官网实时页面为准。",
        "",
    ]
    return "\n".join(lines)


def chunk_text(school: dict, p: dict, field: str) -> str:
    """为单个字段组生成自包含的分块正文（块首带学校与项目名）。"""
    tuition = p.get("tuition") or {}
    application = p.get("application") or {}
    admission = p.get("admission") or {}
    curriculum = p.get("curriculum") or {}
    verification = p.get("verification") or {}
    header = (
        f"【{school.get('school_name_zh', '')} {school.get('school_id', '')}｜"
        f"{p.get('name_en', '')}｜{p.get('name_zh', '')}】\n"
    )

    if field == "overview":
        body = "\n".join([
            f"所属学院：{p.get('faculty', '')}；系 / 开办单位：{p.get('department', '')}。",
            f"学位类型：{p.get('degree_type', '')}。",
            f"学制：全日制 {p.get('duration_ft', '')}；兼读制 {p.get('duration_pt', '')}。学分结构：{p.get('credits', '')}。",
            f"目标入学季：{school.get('intake_target', '')}；数据快照：{school.get('snapshot_date', '')}。",
            "易混淆名称 / 旧名：" + ("、".join(as_list(p.get("aliases"))) or "无"),
            "官网：" + "、".join(as_list(p.get("official_urls"))),
        ])
    elif field == "tuition_application":
        body = "\n".join([
            f"学费：{tuition.get('amount', '')}（对应 {tuition.get('intake', '')}；{tuition.get('applies_to', '')}）。",
            f"费用补充：{tuition.get('note', '')}",
            f"申请开放：{application.get('open', '')}。",
            "截止 / 轮次：" + "；".join(as_list(application.get("deadlines"))),
            f"申请备注：{application.get('note', '')}",
        ])
    elif field == "admission":
        body = "\n".join([
            f"语言要求：{p.get('english', '')}",
            f"本科背景：{admission.get('background', '')}",
            f"先修课 / 技能：{admission.get('prerequisites', '')}",
            f"GRE / GMAT：{admission.get('gre_gmat', '')}",
            f"工作经验：{admission.get('work_experience', '')}",
        ])
    elif field == "curriculum":
        body = "\n".join([
            f"课程结构：{curriculum.get('structure', '')}",
            "核心 / 必修：" + ("；".join(as_list(curriculum.get("core"))) or "待核实"),
            "选修 / 方向：" + ("；".join(as_list(curriculum.get("electives"))) or "待核实"),
            "Track / 专攻：" + ("；".join(as_list(curriculum.get("tracks"))) or "官网未分设"),
        ])
    elif field == "highlights_career":
        body = "\n".join([
            "项目特色：\n" + bullets(p.get("highlights")),
            "就业去向：\n" + bullets(p.get("career")),
        ])
    elif field == "writing_hooks":
        body = "撰写 PS / SOP 时可参考的官方表述要点：\n" + bullets(p.get("writing_hooks"))
    else:  # verification_sources
        sources = p.get("sources") or []
        if isinstance(sources, dict):
            sources = [sources]
        source_lines = [
            f"- {s.get('url', '')}：{s.get('supports', '')}"
            for s in sources if isinstance(s, dict)
        ]
        body = "\n".join([
            f"核实状态：{verification.get('status', '')}；数据快照：{school.get('snapshot_date', '')}。",
            "官网口径冲突：" + ("；".join(as_list(verification.get("conflicts"))) or "无"),
            "待核实字段：" + ("；".join(as_list(verification.get("unverified"))) or "无"),
            "官方来源：\n" + ("\n".join(source_lines) or "无"),
        ])
    return header + body


def make_chunk(school: dict, p: dict, field: str, label: str, suitable: bool) -> dict:
    """生成一条分块记录，meta 字段与后端 knowledge_chunks 表对齐。"""
    content = chunk_text(school, p, field)
    verification = p.get("verification") or {}
    return {
        "id": f"{p.get('id', '')}::{field}",
        # 后端表字段：source / content / meta；embedding 与 user_id 在接入 RAG 时生成
        "source": f"knowledge/programs/{school.get('school_id', '').lower()}/{p.get('id', '')}.md",
        "content": content,
        "meta": {
            "chunk_id": f"{p.get('id', '')}::{field}",
            "field": field,
            "field_label": label,
            "school_id": school.get("school_id", ""),
            "school_name_zh": school.get("school_name_zh", ""),
            "region": school.get("region", ""),
            "program_id": p.get("id", ""),
            "program_name_en": p.get("name_en", ""),
            "program_name_zh": p.get("name_zh", ""),
            "faculty": p.get("faculty", ""),
            "intake": school.get("intake_target", ""),
            "snapshot_date": school.get("snapshot_date", ""),
            "verification_status": verification.get("status", ""),
            "suitable_for_writing": suitable,
            "has_unverified": "待核实" in content,
            "official_urls": as_list(p.get("official_urls")),
            "source_type": "official_university",
        },
    }


def render_index_md(schools: list[dict], stats: dict) -> str:
    lines = [
        "# AppliCraft 初始知识库 · 港新 CS / 数据科学 / AI 授课型硕士",
        "",
        f"- **数据快照**：{stats['snapshot_date']}",
        f"- **覆盖范围**：{stats['school_count']} 所学校 / {stats['program_count']} 个项目；"
        f"香港 3 所（HKU / CUHK / HKUST）+ 新加坡 2 所（NUS / NTU）",
        f"- **方向**：计算机科学、数据科学、人工智能、商业分析、金融科技等授课型硕士",
        f"- **分块数**：{stats['chunk_count']}（其中适合喂给文书生成的 {stats['writing_chunk_count']} 块）",
        f"- **编译时间**：{stats['generated_at']}",
        "",
        "> ⚠️ **免责声明**：本库全部事实字段来自各校官网公开页面，学费、申请截止日期、语言分数"
        "会随入学季滚动更新，且部分官网页面之间存在口径冲突（已在各卡片「核实状态与来源」列明）。"
        "字段值为「待核实」表示官网未列或页面访问受阻，**不得据此推断或补写数字**。"
        "提交申请前请以官网实时页面为最终准绳；生成文书时不得把本库内容当作个人经历。",
        "",
        "## 项目索引",
        "",
        "| 学校 | 项目 | 官方英文名 | 学院 | 核实状态 | 卡片 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for school in schools:
        for p in school["programs"]:
            status = (p.get("verification") or {}).get("status", "")
            card = f"programs/{school['school_id'].lower()}/{p['id']}.md"
            lines.append(
                f"| {school['school_name_zh']} | {esc(p.get('name_zh', ''))} | "
                f"{esc(p.get('name_en', ''))} | {esc(p.get('faculty', ''))} | `{status}` | "
                f"[{p['id']}]({card}) |"
            )
    lines += [
        "",
        "## 目录结构",
        "",
        "```",
        "knowledge/",
        "├── _raw/                  五校原始调研 JSON（含完整来源清单，保留原始口径）",
        "│   └── schema.example.json 字段规范",
        "├── programs/<学校>/        30 份项目卡片（人读，带 frontmatter）",
        "├── index.json             项目级索引（机器可读）",
        "├── chunks.jsonl           RAG 分块（每行一条 JSON）",
        "├── build.py               本库的编译脚本（改 _raw 后重跑即可）",
        "├── query.py               不依赖向量库的本地检索 CLI",
        "└── INDEX.md               本文件",
        "```",
        "",
        "## 数据纪律",
        "",
        "1. 只采信学校官方域名（`hku.hk` / `cuhk.edu.hk` / `ust.hk` / `nus.edu.sg` / `ntu.edu.sg`）页面与官方 PDF；"
        "第三方内容仅作线索，未写入任何事实字段。",
        "2. 学费必须带 `tuition.intake` 标签：NUS 部分项目是 AY2026/27 onwards，另一些是 AY2027/28，混用会全库数值错误。",
        "3. 命名消歧写在 `general.notes` 与 `aliases`：例如 NUS 不存在「MSc in Artificial Intelligence」，"
        "正确名称是 `Master of Computing in Artificial Intelligence`；HKUST 无「MSc in Data Science」授课硕士。",
        "4. 每个分块 `meta.has_unverified` 标记是否含「待核实」内容，"
        "`meta.suitable_for_writing` 标记是否适合直接喂给文书生成。",
        "",
        "## 后续接入 RAG 的接口约定",
        "",
        "`chunks.jsonl` 每行结构与后端 `backend/app/db/models.py` 的 `KnowledgeChunk` 表一一对应：",
        "",
        "| chunks.jsonl 字段 | KnowledgeChunk 列 | 说明 |",
        "| --- | --- | --- |",
        "| `source` | `source` | 相对路径，便于回溯卡片 |",
        "| `content` | `content` | 已自包含（块首带学校与项目名） |",
        "| `meta` | `meta` | 学校 / 项目 / 字段 / 入学季 / 核实状态 / 是否可写作 |",
        "| — | `embedding` | 接入时生成；表定义固定 1536 维，换模型需迁移列 |",
        "| — | `user_id` | **本库是公共项目资料，不是用户私有材料**；接入时需用一个系统级共享账号 ID，"
        "检索条件同时带 `user_id` 与向量相似度，并过滤 `suitable_for_writing=true` |",
        "",
        "接入建议（本轮未实现，按后续需要再做）：",
        "",
        "1. 在 `graph/nodes.py` 的 `outline` / `draft` 节点前加检索步骤，按档案里的目标项目名召回"
        "`curriculum` / `highlights_career` / `writing_hooks` 三类分块。",
        "2. 只把召回内容作为「项目官方表述参考」注入 Prompt，明确要求模型**不得**把其中的学费、"
        "截止日期、分数写进文书，也不得当作申请人自身经历。",
        "3. 低置信或 `has_unverified=true` 的分块降权；生成结果里若出现具体课程名，"
        "可在事实校验节点与召回片段做一次比对。",
        "4. 未接 RAG 前，可用 `python knowledge/query.py --school HKU --field writing_hooks` "
        "先按关键词取参考素材，人工贴进生成面板的「补充说明」。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    raw_files = sorted(
        f for f in RAW_DIR.glob("*.json") if f.name != "schema.example.json"
    )
    if not raw_files:
        raise SystemExit("未找到 _raw/ 下的学校 JSON，请先完成资料调研")

    schools: list[dict] = []
    chunks: list[dict] = []
    index_programs: list[dict] = []

    bad_urls: list[str] = []
    for raw_file in raw_files:
        school = clean(json.loads(raw_file.read_text(encoding="utf-8")))
        bad_urls.extend(validate_sources(school))
        sid = school.get("school_id", "")
        school_dir = PROGRAM_DIR / sid.lower()
        school_dir.mkdir(parents=True, exist_ok=True)

        for p in school.get("programs", []):
            pid = p.get("id", "")
            if not pid:
                raise SystemExit(f"{raw_file.name} 中存在缺少 id 的项目")
            card_path = school_dir / f"{pid}.md"
            card_path.write_text(render_card(school, p), encoding="utf-8")

            for field, label, suitable in FIELD_GROUPS:
                chunks.append(make_chunk(school, p, field, label, suitable))

            index_programs.append({
                "id": pid,
                "school_id": sid,
                "school_name_zh": school.get("school_name_zh", ""),
                "region": school.get("region", ""),
                "name_en": p.get("name_en", ""),
                "name_zh": p.get("name_zh", ""),
                "aliases": as_list(p.get("aliases")),
                "faculty": p.get("faculty", ""),
                "degree_type": p.get("degree_type", ""),
                "duration_ft": p.get("duration_ft", ""),
                "tuition_amount": (p.get("tuition") or {}).get("amount", ""),
                "tuition_intake": (p.get("tuition") or {}).get("intake", ""),
                "deadlines": as_list((p.get("application") or {}).get("deadlines")),
                "verification_status": (p.get("verification") or {}).get("status", ""),
                "official_urls": as_list(p.get("official_urls")),
                "card_path": f"programs/{sid.lower()}/{pid}.md",
            })

        # 学校级消歧说明也做成一个分块，供检索「某校有没有 MSc in AI」这类问题
        notes = as_list((school.get("general") or {}).get("notes"))
        if notes:
            chunks.append({
                "id": f"{sid.lower()}::school_notes",
                "source": f"knowledge/_raw/{raw_file.name}",
                "content": (
                    f"【{school.get('school_name_zh', '')} {sid}｜全校消歧与数据口径说明】\n"
                    + "\n".join(f"- {n}" for n in notes)
                ),
                "meta": {
                    "chunk_id": f"{sid.lower()}::school_notes",
                    "field": "school_notes",
                    "field_label": "全校消歧说明",
                    "school_id": sid,
                    "school_name_zh": school.get("school_name_zh", ""),
                    "region": school.get("region", ""),
                    "program_id": "",
                    "program_name_en": "",
                    "program_name_zh": "",
                    "faculty": "",
                    "intake": school.get("intake_target", ""),
                    "snapshot_date": school.get("snapshot_date", ""),
                    "verification_status": "verified",
                    "suitable_for_writing": False,
                    "has_unverified": any("待核实" in n for n in notes),
                    "official_urls": [],
                    "source_type": "official_university",
                },
            })

        schools.append(school)

    snapshot_dates = sorted({s.get("snapshot_date", "") for s in schools})
    stats = {
        "snapshot_date": " / ".join(snapshot_dates),
        "school_count": len(schools),
        "program_count": len(index_programs),
        "chunk_count": len(chunks),
        "writing_chunk_count": sum(1 for c in chunks if c["meta"]["suitable_for_writing"]),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    index_data = {
        "schema_version": "1.0",
        "generated_at": stats["generated_at"],
        "snapshot_date": stats["snapshot_date"],
        "scope": {
            "regions": ["HK", "SG"],
            "schools": [s.get("school_id", "") for s in schools],
            "discipline": "CS / 数据科学 / AI 及相关商业分析、金融科技授课型硕士",
            "degree_type": "taught / coursework-based master",
        },
        "disclaimer": (
            "全部事实字段来自各校官网公开页面；学费、截止日期、语言分数随入学季更新，"
            "官网页面之间存在口径冲突时已在各卡片列明。标注「待核实」的字段不得推断或补写数字，"
            "提交申请前以官网实时页面为准。"
        ),
        "schools": [
            {
                "school_id": s.get("school_id", ""),
                "school_name_zh": s.get("school_name_zh", ""),
                "school_name_en": s.get("school_name_en", ""),
                "region": s.get("region", ""),
                "intake_target": s.get("intake_target", ""),
                "program_count": len(s.get("programs", [])),
                "general": s.get("general", {}),
                "raw_file": f"_raw/{s.get('school_id', '').lower()}.json",
            }
            for s in schools
        ],
        "programs": index_programs,
        "stats": stats,
    }

    INDEX_JSON.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with CHUNKS_JSONL.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    INDEX_MD.write_text(render_index_md(schools, stats), encoding="utf-8")

    print(f"知识库编译完成：{stats['school_count']} 校 / {stats['program_count']} 项目 / {stats['chunk_count']} 分块")
    print(f"  适合文书生成的分块：{stats['writing_chunk_count']}")
    print(f"  含待核实内容的分块：{sum(1 for c in chunks if c['meta']['has_unverified'])}")
    print(f"  来源域名校验：{'全部为校方官方域名' if not bad_urls else f'{len(bad_urls)} 条非官方域名'}")
    for url in bad_urls[:5]:
        print(f"    ⚠ {url}")
    print(f"  产出：{INDEX_JSON.name} / {CHUNKS_JSONL.name} / {INDEX_MD.name} / programs/")


if __name__ == "__main__":
    main()
