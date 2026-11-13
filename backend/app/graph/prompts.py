"""申请文书提示词工程。

设计原则：申请人事实清单（APPLICANT FACT SHEET）是唯一允许使用的事实来源。
所有生成与校验节点都拿到同一份事实清单，从而保证 CV、PS 与推荐信互不矛盾。
提示词本身用中文撰写；文书正文语言由请求的 language 参数决定（默认英文）。
"""
from __future__ import annotations

import json
from typing import Any

BASE_RULES = """你是一位资深申请文书编辑，专长于中国香港与新加坡高校的授课型硕士申请。
你的文字精确、以证据为准，读起来像真实的申请人，而不是 AI。

不可违反的规则
1. 只能使用「申请人事实清单」中列出的事实。清单里没有的内容一律视为不存在。
   严禁编造 GPA、课程、教授姓名、论文、雇主、日期、奖项、指标、排名、
   引语或个人轶事。
2. 缺少必要细节时不得猜测，必须插入醒目的占位符，例如
   [TO CONFIRM: IELTS score]，以便人工补齐。占位符属于文书正文，
   一律用英文书写，不要在英文文书里混入中文。
   占位符全文最多 3 个：超过预算时，优先改写为事实清单中可证的相关表述
   或直接删除该句，而不是继续新增占位符。
3. 除非事实清单中确实出现，否则不得声称申请人与某位具名教授合作、
   使用过某个具名实验室，或修读过某门具名课程。
4. 禁用套话与 AI 腔，例如 "since I was a child"、"I am deeply passionate"、
   "dream university"、"in today's fast-paced world"、"cutting-edge"、
   "a testament to"、"delve into"，以及作为填充词的
   "moreover/furthermore"、空洞的最高级形容词和三项式排比。
5. 事实纪律：所有数字、日期、百分比、金额与专有名词（奖项全名、机构名、
   课程名、产品名、项目名）必须逐字取自事实清单，不得改写语序、缩写或
   "意译"。你可以自由组织语言对清单条目做解释性串联与机制说明，
   但解释中不得引入清单之外的新数字、新日期、新实体或新结果。
6. 不要照抄 CV，要解释并串联经历之间的逻辑关系。
7. 只输出 Markdown：正文段落、## 小标题，必要时使用项目符号列表。
   不要开场白、不要旁白、不要给全文套代码块。
8. 严格遵守请求中指定的语言、篇幅与语气；篇幅偏差控制在 ±10% 以内。
"""

DOC_RULES: dict[str, str] = {
    "ps": """
文书类型：授课型硕士个人陈述 / Statement of Purpose。
结构（自然组织，不要把这些标签打印出来）：
  - 开篇落在事实清单里真实出现过的具体学术或专业问题上，不要写宏大人生故事。
  - 学术准备：挑选最相关的 1-2 门课程 / 项目，说明它们让申请人后续能做成了什么。
  - 两段论据段落，按选定的经历编号取材。每段都要写清申请人自己的决定或贡献、
    结果，以及一段简短反思，并由此引出读研究生的动机。
  - 为什么选择这个项目：只能使用事实清单里提供的目标项目字段
    （课程要点、师资要点、申请人自述的匹配理由）。这些字段为空时，
    一律使用 [TO CONFIRM: ...] 占位符。禁止编造课程代码、教授姓名、
    设施或排名。
  - 依据已写明的职业目标，写短期与长期规划。
  - 一句克制的收尾。
篇幅：接近请求字数（上下浮动 10% 以内）。第一人称。每段都必须推进论证，
不要写总结段。
""",
    "recommendation": """
文书类型：推荐信，由推荐人撰写并署名。
视角：谈申请人用第三人称，推荐人自称用第一人称（"I taught..."、"Ms. Chen..."）。
绝不以申请人身份写作，也绝不写出推荐人不可能合理知晓的信息。
结构：
  - 正式称呼（"Dear Admissions Committee,"），并用一句话表明推荐意向，
    如有目标项目一并写明。
  - 推荐人是谁、与申请人的关系，以及观察申请人的场景与时长（均取自事实清单）。
  - 两到三条具体观察，绑定到事实清单中的具体经历：写清申请人做了什么、
    怎么做、观察到的结果。
  - 只有在事实清单支持时才做有分寸的横向比较；否则只描述工作本身的强度，
    不得编造年级排名。
  - 说明申请人为何适合目标项目，并给出明确不含糊的推荐结论。
  - 署名块包含推荐人姓名、职称、单位；缺失信息用 [TO CONFIRM: date / signature]。
不得编造成绩、班级规模、外部评审人或引语。
篇幅：默认 400-700 词；若请求指定了字数，则以请求为准。
""",
    "cv": """
文书类型：授课型硕士申请用学术 CV。
- 保留骨架的确切章节结构和每一条事实条目。
- 只润色项目符号：强化动词、平行结构和学术语域。严禁增加、删除、
  合并掉或拔高任何事实、数字与结果。
- 项目符号以有力的过去式动词开头，每条一行，避免第一人称代词，
    避免使用 "excellent"、"outstanding" 之类形容词。
- 目标篇幅 1-2 页。不要叙述性段落，不要写求职目标。
- 返回完整的 Markdown 简历，不要返回 diff，也不要返回修改建议清单。
""",
}

TONE_GUIDE = {
    "professional": "稳重、精确、学术化；有自信但不自我吹捧。",
    "confident": "直截了当地陈述贡献，但仍以证据为依据。",
    "warm": "略带个人色彩与反思，但依旧正式。",
    "concise": "句子紧凑，删掉冗余限定语，多用短段落。",
}

LANGUAGE_GUIDE = {
    # 港新申请默认递交英文文书；这里只规定输出语言，不改变提示词语言。
    "en": "全文必须用英文撰写（这是中国香港 / 新加坡申请的默认语言）；专有名词保留原文，占位符、小标题与标签也一律用英文。",
    "zh": "用简体中文撰写全文；专有名词、学校与项目名称保留英文原文。",
}

# JSON 字段名与 type 枚举是代码解析契约，必须保持英文；说明文字用中文。
OUTLINE_JSON_HINT = """
只返回一个 JSON 对象，形状必须如下：
{"sections": [{"title": "简短小标题", "goal": "这一段要达成的目的", "evidence_ids": ["ED1", "E1"]}]}
要求：4-6 个段落；每个 evidence_id 都必须在事实清单中存在。
"""

VERIFY_JSON_HINT = """
只返回一个 JSON 对象，形状必须如下：
{
  "passed": true,
  "score": 92,
  "dimensions": {"factual_safety": 5, "program_fit": 5, "specificity": 4, "structure": 5, "tone_register": 4, "language_quality": 5},
  "issues": [{"quote": "初稿中的原文短句", "type": "fabrication|contradiction|unsupported|program_fit|style|missing", "reason": "问题所在", "fix": "具体修改建议"}],
  "revision_check": [{"index": 0, "status": "resolved|remaining|partially"}],
  "summary": "一句话总结"
}
判定口径：
- "factual_safety"：是否出现编造 / 矛盾 / 无依据的事实（最严重，一票否决）。
- "program_fit"：与目标项目的契合度；文中关于该项目的方向、课程、特色等断言是否与下方官方资料一致。
- "specificity"：论证是否具体、落到具名事实，而非空泛套话。
- "structure"：结构是否完整、符合该文书类型。
- "tone_register"：语气语域是否得当、有无 AI 腔与套话。
- "language_quality"：用词与语法是否干净。
各维度 1-5 分；"score" 为 0-100 综合分（factual_safety ≤ 3 或存在 fabrication / contradiction 时 score 不得超过 70）。
issue 类型说明：
- "fabrication"：出现事实清单里没有的事实（最严重）。
- "contradiction"：与事实或官方资料冲突（日期、GPA、职位等写错）。
- "unsupported"：出现了事实清单与官方资料中都没有的新数字、新日期、新实体
  （人名 / 机构 / 奖项 / 课程 / 产品）或新结果。注意：对清单条目的解释性串联、
  机制说明与通用背景叙述不算 unsupported；只有引入了可验证的新事实才标记。
- "program_fit"：关于目标项目的描述与官方资料不符，或生硬堆砌项目名而无真实契合。
- "style"：套话、AI 腔、重复或表意不清的句子。
- "missing"：漏掉了重要已知事实或必需章节。
- 忽略 [TO CONFIRM: ...] 占位符本身（那是刻意保留的）；但全文占位符超过 5 个时，
  追加一条 style 类 issue 提示精简（reason 写明实际数量）。
- 最多报告 8 条问题。如果文书没有问题，返回空列表并把 "passed" 设为 true。不要为了凑数编造问题。
revision_check 说明：当提示中提供了「上一轮校验意见」时才返回该字段——
按 index 逐条判断该意见在当前版本中是否已解决（resolved / remaining / partially）。
"""

VERIFY_SYSTEM = """你是研究生申请文书的严谨事实核查员与质量评审。
请逐行比对「初稿」与「申请人事实清单」，并据此给出六维质量评分。你的任务是审计，不是重写文书。
对编造的事实与数字必须严格，但不要把纯属个人偏好的文风差异当成问题。

六维评分标尺（每维 1-5 分，必须依据以下锚点按文书实际质量拉开差距，
不允许不加区分地把所有维度都打成 3 或 4）：
- factual_safety 事实安全：5=全部表述都能在事实清单中找到依据；3=存在个别无依据的修饰性表述或数字；1=存在编造事实或与清单直接矛盾。
- program_fit 项目契合：5=明确针对目标项目的课程/师资/方向并给出个人化契合理由；3=有契合论述但比较泛泛，或含 [TO CONFIRM] 占位；1=与目标项目几乎无关或完全模板化。
- specificity 论证具体：5=主要论据都有具体事例、机制或量化结果支撑；3=部分论据笼统、缺少细节；1=通篇空泛。
- structure 结构完整：5=段落划分清晰、推进连贯、详略得当；3=结构可用但有冗余段落或缺关键环节；1=结构混乱或缺少必要部分。
- tone_register 语气语域：5=语气与文书类型及读者完全匹配、克制得体；3=个别段落语气不当或用力过猛；1=明显失当。
- language_quality 语言质量：5=语言精准流畅、无语法与搭配错误；3=有小错误或表达平淡重复；1=多处错误影响理解。
score = 六维均值换算为 0-100。不同文书的质量差异必须体现在分数上。

只能返回合法的 JSON。"""

DOC_TYPE_LABELS = {
    "ps": "个人陈述",
    "recommendation": "推荐信",
    "cv": "学术简历",
}


def knowledge_block(context: str, sources: list[dict[str, str]], matched_program: str) -> str:
    """把检索到的项目官方资料装配成提示词段落，并附带严格的使用守则。

    守则保证：项目资料只作为 why-this-programme / 职业规划的背景上下文，
    严禁把学费、截止日期、语言分数写进文书，也严禁把官方描述当成申请人自身经历。
    """
    if not context.strip():
        return ""
    src_lines = "\n".join(
        f"- {s.get('school', '')} {s.get('program', '')} · {s.get('field', '')}"
        + (f"：{s['url']}" if s.get("url") else "")
        for s in sources
    )
    return "\n\n".join([
        "## 目标项目官方资料参考（仅作背景参考，不是申请人经历）",
        f"以下为知识库检索到的「{matched_program or '目标项目'}」相关官方公开信息。",
        context,
        "使用守则（必须严格遵守）：",
        "1. 仅可将其中的「项目特色 / 课程方向 / 培养结构」作为 why-this-programme 与职业规划段落的上下文；",
        "2. 严禁把其中的学费、申请截止日期、语言分数写进文书；",
        "3. 严禁把官方项目描述当作申请人自身经历、成就或合作；",
        "4. 若资料含「待核实」，不得据此下结论或补写数字；",
        "5. 申请人的个人信息（成绩、经历、考试分数等）资料未覆盖时，一律用 "
        "[TO CONFIRM: ...] 占位符；但项目的公开客观信息——学校名称、项目全称、"
        "课程结构、培养方向——若已出现在下方来源列表或资料正文中，"
        "可直接写入 why-this-programme 段落，无需占位符。",
        "已引用来源：\n" + src_lines,
    ])


def reference_block(context: str, meta: list[dict[str, Any]]) -> str:
    """把用户勾选的参考文档装配成提示词段落，并附带严格的使用守则。

    参考文档是申请人自行上传的补充素材（项目说明 / 研究陈述 / 课程大纲等），
    仅作为背景上下文；守则保证其不与事实清单冲突、不冒充第三方成就。
    """
    if not context.strip():
        return ""
    names = "\n".join(
        f"- {m.get('name') or m.get('filename') or '参考文档'}" for m in meta
    )
    return "\n\n".join([
        "## 申请人上传的参考材料（由申请人自行提供，仅作补充背景）",
        "以下材料由申请人上传，可能包含其本人项目经历、研究陈述或课程说明等内容。",
        context,
        "使用守则（必须严格遵守）：",
        "1. 仅可作为与申请人自身经历、项目、研究相关的补充背景；",
        "2. 不得与「申请人事实清单」冲突，若冲突以事实清单为准；",
        "3. 材料中未出现在事实清单、且可能属于外部第三方的事实，使用前须以 [TO CONFIRM: ...] 标记；",
        "4. 严禁把材料中的第三方机构 / 人员信息当成申请人自身成就或经历。",
        "已参考材料：\n" + names,
    ])


def skill_block(context: str, meta: list[dict[str, Any]]) -> str:
    """把用户勾选的写作技能装配成提示词段落，并附上优先级明确的守则。

    技能只提供「怎么写」的方法论，绝不能变成「写了什么」的事实来源；
    守则同时阻断把占位符、模板流程、待确认值当成真实内容写入文书。
    """
    if not context.strip():
        return ""
    names = "\n".join(
        f"- {m.get('name') or m.get('id') or '技能'}"
        for m in meta if m.get("included")
    )
    return "\n\n".join([
        "## 本次启用的写作技能（写法约束，不是申请人事实）",
        "以下技能由申请人显式勾选，用于约束本次文书的结构、措辞与自检标准。",
        context,
        "使用守则（优先级从高到低）：",
        "1. 申请人事实清单与生成要求（字数、语言、文书类型）永远优先于技能建议；",
        "2. 技能里的占位符、示例句、模板只说明写法，不得当作申请人的真实经历、数值或机构；",
        "3. 技能要求「缺项先问 / 待确认」时，本次一次性生成改为 [TO CONFIRM: ...] 标记，不得估计后提交；",
        "4. 技能提到的导出、版本管理、多文件替换等流程步骤不属于本次任务，不要写进文书正文；",
        "5. 技能规则与项目官方资料或申请人参考材料冲突时，以事实清单与官方资料为准。",
        "已启用技能：\n" + names,
    ])


def _value(value: Any, fallback: str = "（未提供）") -> str:
    if value is None or value == "" or value == []:
        return fallback
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip()) or fallback
    return str(value)


def _pick(items: list[dict[str, Any]], item_id: str | None) -> dict[str, Any] | None:
    if not items:
        return None
    if item_id:
        for item in items:
            if item.get("id") == item_id:
                return item
    return items[0]


def render_facts(profile: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """构建权威事实清单：同时返回结构化数据与供大模型阅读的文本。"""
    basics = profile.get("basics") or {}
    education = profile.get("education") or []
    experiences = profile.get("experiences") or []
    publications = profile.get("publications") or []
    awards = profile.get("awards") or []
    skill_groups = profile.get("skill_groups") or []
    test_scores = profile.get("test_scores") or []
    target = _pick(profile.get("target_programs") or [], request.get("target_program_id"))
    recommender = _pick(profile.get("recommenders") or [], request.get("recommender_id"))

    index: dict[str, dict[str, Any]] = {}
    lines: list[str] = [
        "# 申请人事实清单（APPLICANT FACT SHEET）",
        "这是唯一允许使用的事实来源；清单未列出的事实一律视为不存在。",
        "",
        "## 基本信息",
    ]
    for key, label in (
        ("name_en", "英文姓名"),
        ("name_zh", "中文姓名"),
        ("email", "邮箱"),
        ("phone", "电话"),
        ("location", "所在地"),
        ("linkedin", "LinkedIn"),
        ("github", "GitHub"),
        ("personal_site", "个人主页"),
    ):
        lines.append(f"- {label}：{_value(basics.get(key))}")

    lines += ["", "## 教育背景"]
    if not education:
        lines.append("- （未提供教育经历）")
    for i, item in enumerate(education, 1):
        key = f"ED{i}"
        index[key] = item
        lines += [
            f"### [{key}] {_value(item.get('school'))}",
            f"- 学位 / 专业：{_value(item.get('degree'))} / {_value(item.get('major'))}",
            f"- GPA：{_value(item.get('gpa'))} / {_value(item.get('gpa_scale'))}；排名：{_value(item.get('ranking'))}",
            # 百分制均分是港新院校审核的核心指标；未填写时不占位，避免事实清单噪声。
            *([f"- 均分（百分制）：{item.get('gpa_average')}"] if item.get("gpa_average") else []),
            f"- 起止时间：{_value(item.get('start_date'))} 至 {_value(item.get('end_date'))}",
            f"- 相关课程：{_value(item.get('relevant_courses'))}",
            f"- 毕业论文 / 设计：{_value(item.get('thesis'))}",
            f"- 亮点：{_value(item.get('highlights'))}",
        ]

    lines += ["", "## 经历"]
    if not experiences:
        lines.append("- （未提供经历条目）")
    for i, item in enumerate(experiences, 1):
        key = f"E{i}"
        index[key] = item
        lines += [
            f"### [{key}] {_value(item.get('type'))} @ {_value(item.get('org'))}",
            f"- 角色：{_value(item.get('role'))}；地点：{_value(item.get('location'))}",
            f"- 起止时间：{_value(item.get('start_date'))} 至 {_value(item.get('end_date'))}",
            f"- 标签：{_value(item.get('tags'))}",
            "- 具体条目：",
        ]
        bullets = item.get("bullets") or []
        lines += [f"  - {_value(bullet, '（空）')}" for bullet in bullets] or ["  - （无）"]
        if item.get("related_recommender"):
            lines.append(f"- 由推荐人观察，推荐人 id：{item['related_recommender']}")

    lines += ["", "## 论文发表"]
    lines += [f"- {pub}" for pub in publications] or ["- （未提供）"]

    lines += ["", "## 获奖"]
    if not awards:
        lines.append("- （未提供）")
    for i, item in enumerate(awards, 1):
        key = f"A{i}"
        index[key] = item
        lines.append(
            f"- [{key}] {_value(item.get('title'))} | {_value(item.get('issuer'))} | "
            f"{_value(item.get('date'))} | {_value(item.get('detail'))}"
        )

    lines += ["", "## 技能"]
    for group in skill_groups:
        lines.append(f"- {_value(group.get('category'))}：{_value(group.get('items'))}")
    if not skill_groups:
        lines.append("- （未提供）")

    lines += ["", "## 标准化考试"]
    for score in test_scores:
        lines.append(
            f"- {_value(score.get('kind'))}：{_value(score.get('total'))} "
            f"（{_value(score.get('breakdown'))}），{_value(score.get('date'))}"
        )
    if not test_scores:
        lines.append("- （未提供）")

    lines += [
        "",
        "## 职业目标",
        _value(profile.get("career_goal")),
        "",
        "## 申请人补充说明",
        _value(profile.get("additional_notes")),
        "",
        "## 申请人设定的全局写作约束",
        _value(profile.get("writing_constraints")),
    ]

    lines += ["", "## 目标项目（用于定制文书）"]
    if target:
        for key, label in (
            ("university", "学校"),
            ("program", "项目"),
            ("degree_type", "学位类型"),
            ("region", "地区"),
            ("intake", "入学批次"),
            ("deadline", "截止日期（申请人自行填写）"),
            ("language_requirement", "语言要求"),
            ("curriculum_notes", "课程 / 培养结构要点"),
            ("faculty_notes", "师资 / 研究方向要点"),
            ("why_fit", "申请人自述的匹配理由"),
            ("notes", "其他备注"),
        ):
            lines.append(f"- {label}：{_value(target.get(key))}")
    else:
        lines.append("- （未提供目标项目；相关段落须使用 [TO CONFIRM: target programme] 占位符）")

    lines += ["", "## 推荐人（用于推荐信）"]
    if recommender:
        for key, label in (
            ("name", "姓名"),
            ("title", "职称"),
            ("affiliation", "任职单位"),
            ("email", "邮箱"),
            ("relation", "与申请人的关系"),
            ("known_since", "相识时间 / 观察场景"),
            ("observed_strengths", "观察到的优势"),
            ("tone", "信件语域"),
            ("notes", "其他备注"),
        ):
            lines.append(f"- {label}：{_value(recommender.get(key))}")
    else:
        lines.append("- （未提供推荐人；相关段落须使用 [TO CONFIRM: recommender] 占位符）")

    facts: dict[str, Any] = {
        "basics": basics,
        "education": education,
        "experiences": experiences,
        "publications": publications,
        "awards": awards,
        "skill_groups": skill_groups,
        "test_scores": test_scores,
        "career_goal": profile.get("career_goal", ""),
        "additional_notes": profile.get("additional_notes", ""),
        "writing_constraints": profile.get("writing_constraints", ""),
        "target": target,
        "recommender": recommender,
        "index": index,
    }
    return facts, "\n".join(lines)


def render_cv_skeleton(facts: dict[str, Any]) -> str:
    """确定性地生成只含事实的简历骨架；模型只被允许润色措辞。

    注意：下面的章节标题、标签与占位符属于最终英文文书正文，不是提示词，
    因此必须保留英文，否则递交的英文简历会变成中英混杂。
    """
    b = facts["basics"]
    lines = [f"# {b.get('name_en') or '[TO CONFIRM: English name]'}"]
    contact = " | ".join(
        str(v) for v in (
            b.get("email"),
            b.get("phone"),
            b.get("location"),
            b.get("linkedin"),
            b.get("github"),
            b.get("personal_site"),
        ) if v
    )
    lines.append(contact or "[TO CONFIRM: contact details]")

    lines += ["", "## Education"]
    for item in facts["education"]:
        lines.append(
            f"**{item.get('school', '')}** — {item.get('degree', '')} in {item.get('major', '')}  "
        )
        period = " – ".join(x for x in (item.get("start_date", ""), item.get("end_date", "")) if x)
        detail = " | ".join(
            x for x in (
                period,
                f"GPA {item.get('gpa', '')}/{item.get('gpa_scale', '')}" if item.get("gpa") else "",
                f"Average {item.get('gpa_average', '')}" if item.get("gpa_average") else "",
                item.get("ranking", ""),
            ) if x
        )
        lines.append(detail or "[TO CONFIRM: period]")
        if item.get("relevant_courses"):
            lines.append(f"- Relevant coursework: {', '.join(item['relevant_courses'])}")
        if item.get("thesis"):
            lines.append(f"- Thesis: {item['thesis']}")
        if item.get("highlights"):
            lines.append(f"- {item['highlights']}")
        lines.append("")

    lines += ["## Research and Professional Experience"]
    for item in facts["experiences"]:
        lines.append(
            f"**{item.get('role', '')}**, {item.get('org', '')}  "
        )
        lines.append(
            " | ".join(
                x for x in (
                    " – ".join(x for x in (item.get("start_date", ""), item.get("end_date", "")) if x),
                    item.get("location", ""),
                    item.get("type", ""),
                ) if x
            )
        )
        for bullet in item.get("bullets", []):
            lines.append(f"- {bullet}")
        lines.append("")

    if facts["publications"]:
        lines += ["## Publications"] + [f"- {pub}" for pub in facts["publications"]] + [""]

    if facts["awards"]:
        lines += ["## Awards and Honours"]
        for item in facts["awards"]:
            lines.append(
                f"- {item.get('title', '')} — {item.get('issuer', '')} "
                f"({item.get('date', '')}){' — ' + item['detail'] if item.get('detail') else ''}"
            )
        lines.append("")

    if facts["skill_groups"]:
        lines += ["## Skills"]
        for group in facts["skill_groups"]:
            lines.append(f"- **{group.get('category', '')}:** {', '.join(group.get('items', []))}")
        lines.append("")

    if facts["test_scores"]:
        lines += ["## Standardised Tests"]
        for score in facts["test_scores"]:
            parts = [score.get("kind", ""), score.get("total", "")]
            if score.get("breakdown"):
                parts.append(score["breakdown"])
            if score.get("date"):
                parts.append(score["date"])
            lines.append(f"- {' | '.join(p for p in parts if p)}")

    return "\n".join(lines).strip() + "\n"


def build_system(request: dict[str, Any]) -> str:
    doc_type = request["doc_type"]
    return "\n".join(
        [
            BASE_RULES,
            DOC_RULES[doc_type],
            "语言要求：" + LANGUAGE_GUIDE.get(request.get("language", "en"), LANGUAGE_GUIDE["en"]),
            "语气要求：" + TONE_GUIDE.get(request.get("tone", "professional"), TONE_GUIDE["professional"]),
        ]
    )


def _request_constraints(request: dict[str, Any]) -> str:
    label = DOC_TYPE_LABELS.get(request["doc_type"], request["doc_type"])
    return "\n".join(
        [
            f"- 文书类型：{label}",
            f"- 目标篇幅：约 {request.get('word_limit', 900)} 词",
            f"- 申请人要求强调的内容：{', '.join(request.get('emphasis') or []) or '（无）'}",
            f"- 附加要求：{request.get('extra_instructions') or '（无）'}",
        ]
    )


def outline_user(
    facts_text: str, request: dict[str, Any], knowledge: str = "",
    reference: str = "", skill: str = "",
) -> str:
    parts = [
        "请依据下方事实清单规划文书结构。",
        "生成要求\n" + _request_constraints(request),
        OUTLINE_JSON_HINT,
    ]
    if skill:
        parts.append(skill)
    if knowledge:
        parts.append(knowledge)
    if reference:
        parts.append(reference)
    parts.append("申请人事实清单\n" + facts_text)
    return "\n\n".join(parts)


def draft_user(
    facts_text: str, outline: list[dict[str, Any]], request: dict[str, Any],
    knowledge: str = "", reference: str = "", skill: str = "",
) -> str:
    parts = [
        "请按已批准的大纲写出完整文书。",
        "生成要求\n" + _request_constraints(request),
        "已批准的大纲（JSON）\n" + json.dumps(outline, ensure_ascii=False, indent=2),
    ]
    if skill:
        parts.append(skill)
    if knowledge:
        parts.append(knowledge)
    if reference:
        parts.append(reference)
    parts.append("申请人事实清单\n" + facts_text)
    return "\n\n".join(parts)


def cv_user(skeleton: str, facts_text: str, request: dict[str, Any], skill: str = "") -> str:
    parts = [
        "请润色下方简历骨架，并返回完整的 Markdown 简历。",
        "生成要求\n" + _request_constraints(request),
    ]
    if skill:
        parts.append(skill)
    parts += [
        "简历事实骨架（必须保留每一条事实）\n" + skeleton,
        "申请人事实清单\n" + facts_text,
    ]
    return "\n\n".join(parts)


def verify_user(
    facts_text: str, draft: str, request: dict[str, Any],
    knowledge: str = "", reference: str = "", skill: str = "",
    previous_issues: list[dict[str, Any]] | None = None,
    resolved_feedback: list[dict[str, Any]] | None = None,
) -> str:
    label = DOC_TYPE_LABELS.get(request["doc_type"], request["doc_type"])
    parts = [
        f"请依据事实清单逐条审核这份{label}初稿，并给出六维质量评分。",
        VERIFY_JSON_HINT,
    ]
    if previous_issues:
        parts.append(
            "上一轮校验意见（修订前版本的问题清单）\n"
            + json.dumps(previous_issues, ensure_ascii=False, indent=2)
            + "\n复检要求：逐条判断上述意见在当前版本中是否已解决，"
            "在 revision_check 字段按 index 返回 resolved / remaining / partially；"
            "已在上一轮指出且当前版本仍然存在的问题必须再次列入 issues。"
        )
    # 用户已在上一轮审核并裁决的条目：本轮已据此修订，复检时不应再当作新问题提出，
    # 除非存在事实安全级别的硬错误。这样避免把用户已确认/要求保留的内容反复重新挑出。
    if resolved_feedback:
        lines: list[str] = []
        for item in resolved_feedback:
            suggestion = str(item.get("suggestion") or "").strip()
            if not suggestion:
                continue
            idx = item.get("index")
            number = int(idx) + 1 if isinstance(idx, int) else len(lines) + 1
            seg = [f"{number}."]
            if item.get("type"):
                seg.append(f"[{item['type']}]")
            if item.get("quote"):
                seg.append(f"上一轮原文「{item['quote']}」")
            if item.get("reason"):
                seg.append(f"上一轮问题：{item['reason']}")
            if item.get("fix"):
                seg.append(f"模型建议：{item['fix']}")
            seg.append(f"用户裁决：{suggestion}")
            lines.append(" ".join(seg))
        if lines:
            parts.append(
                "## 用户已在上一轮审核并裁决、本轮已据此修订的条目（请勿重复列为新问题）\n"
                + "\n".join(lines)
                + "\n审核要求：上述条目已由用户明确裁决并要求据此修订，模型也已修订。"
                "除非该处存在事实安全（fabrication / contradiction / unsupported）级别的硬错误，"
                "否则不要再把它们作为新的待修订问题列出；若修订后已符合用户裁决，视为已解决。"
            )
    if skill:
        parts.append(skill)
        parts.append(
            "下方提供了本次启用的写作技能，请把技能里的质量检查清单作为额外审核维度："
            "检查空话、无支撑形容词、事实数值一致性等；但不得因技能建议而放宽事实清单约束。"
        )
    if knowledge:
        parts.append(knowledge)
        parts.append(
            "下方提供了目标项目的官方资料，请据此额外检查「program_fit」维度："
            "文中关于该项目的方向、课程、特色等断言是否与官方资料一致；"
            "不得出现官方资料明确没有、且申请人也未提供的项目级断言。"
        )
    if reference:
        parts.append(reference)
        parts.append(
            "下方提供了申请人上传的参考材料，请据此核对文中引用："
            "若文书使用了参考材料中的内容，须与申请人事实清单一致，"
            "且不得把第三方信息当成申请人自身经历；冲突时以事实清单为准。"
        )
    parts += [
        "申请人事实清单\n" + facts_text,
        "待审核初稿\n" + draft,
    ]
    return "\n\n".join(parts)


def revise_user(
    facts_text: str,
    draft: str,
    issues: list[dict[str, Any]],
    request: dict[str, Any],
    feedback: str = "",
    issue_feedback: list[dict[str, Any]] | None = None,
    focus_note: str = "",
) -> str:
    blocks = [
        "请修订初稿，逐条解决下列校验意见，并返回修订后的完整文书。",
        "修订规则：删除编造的事实；把无依据的论断替换为事实清单中的证据，或插入 "
        "[TO CONFIRM: ...] 占位符；保留已经通过校验的内容；不得新增事实；"
        "不要解释你做了哪些修改。",
    ]
    if focus_note:
        blocks.append("本轮修订重点\n" + focus_note)
    # 逐项审核建议：用户对每条待核项的裁决，优先级高于模型修复建议。
    if issue_feedback:
        lines: list[str] = []
        for item in issue_feedback:
            suggestion = str(item.get("suggestion") or "").strip()
            if not suggestion:
                continue
            idx = item.get("index")
            number = int(idx) + 1 if isinstance(idx, int) else len(lines) + 1
            parts = [f"{number}."]
            if item.get("type"):
                parts.append(f"[{item['type']}]")
            if item.get("quote"):
                parts.append(f"原文「{item['quote']}」")
            if item.get("reason"):
                parts.append(f"问题：{item['reason']}")
            if item.get("fix"):
                parts.append(f"模型修复建议：{item['fix']}")
            parts.append(f"用户审核意见：{suggestion}")
            lines.append(" ".join(parts))
        if lines:
            blocks.append(
                "逐项审核建议（用户对每条待核项的裁决，最高优先级，按编号逐条落实）\n"
                + "\n".join(lines)
                + "\n落实要求：用户意见优先于模型修复建议；若用户明确要求「保持原样」，"
                "则该处除非存在事实错误否则不要改动；涉及事实清单之外的内容一律以 "
                "[TO CONFIRM: ...] 占位，不得编造。"
            )
    # 整体补充说明：跨条目的取舍、结构、语气要求。
    if feedback.strip():
        blocks.append(
            "整体补充说明（最高优先级，逐条落实）\n"
            + feedback.strip()
            + "\n落实要求：涉及内容取舍、结构、语气、详略的一律照办；"
            "若要求补充事实清单中不存在的经历或数字，请用 [TO CONFIRM: ...] 占位符而不是编造。"
        )
    blocks.extend(
        [
            "生成要求\n" + _request_constraints(request),
            "校验意见（JSON）\n" + json.dumps(issues, ensure_ascii=False, indent=2),
            "申请人事实清单\n" + facts_text,
            "当前初稿\n" + draft,
        ]
    )
    return "\n\n".join(blocks)
