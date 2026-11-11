"""API 请求与响应数据模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

DocType = Literal["cv", "ps", "recommendation"]

DOC_TYPE_LABELS: dict[str, str] = {
    "cv": "学术 CV",
    "ps": "个人陈述 PS / SOP",
    "recommendation": "推荐信",
}

NODE_LABELS: dict[str, str] = {
    "intake": "整理申请人事实清单",
    "outline": "规划结构与素材选取",
    "draft": "起草正文",
    "cv_render": "渲染简历并润色bullet",
    "verify": "事实一致性与文书质量校验",
    "revise": "按校验意见修订",
    "finalize": "定稿与归档",
    "regenerate": "应用用户审核建议",
}


class GenerateRequest(BaseModel):
    profile_id: str
    doc_type: DocType
    target_program_id: str | None = None
    recommender_id: str | None = None
    language: Literal["en", "zh"] = "en"
    word_limit: int = Field(default=900, ge=150, le=3000)
    tone: str = "professional"  # professional | confident | warm | concise
    emphasis: list[str] = Field(default_factory=list)
    extra_instructions: str = ""
    # 生成时勾选使用的用户参考文档 id（来自参考文档库），为空则不注入。
    reference_doc_ids: list[str] = Field(default_factory=list)
    # 生成时启用的写作技能 id（builtin:xxx / user:xxx），为空则不注入。
    skill_ids: list[str] = Field(default_factory=list)


# ------------------------------------------------- 导入后补充元数据（弹窗填写）
class ReferenceDocUpdate(BaseModel):
    """导入参考文档后补充标题；留空则回退到原始文件名。"""

    name: str = Field(default="", max_length=120)


class SkillUpdate(BaseModel):
    """导入技能后补充名称与简介；名称留空则回退到文件名，简介可留空。"""

    name: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=300)


class ApplicationProjectCreate(BaseModel):
    """新建申请项目：system_program_id 给定时从知识库导入官方数据快照，否则按自定义字段创建。"""

    name: str = Field(min_length=1, max_length=120)
    system_program_id: str = Field(default="", max_length=120)
    university: str = Field(default="", max_length=120)
    program: str = Field(default="", max_length=120)
    degree_type: str = Field(default="", max_length=60)
    region: str = Field(default="", max_length=60)
    intake: str = Field(default="", max_length=60)
    notes: str = Field(default="", max_length=500)


class ApplicationProjectPatch(BaseModel):
    """修改申请项目的名称与备注；留空字段不修改。"""

    name: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=500)


class DocumentAssign(BaseModel):
    """文书归组请求：把一篇已生成的文书归入某个申请项目。"""

    doc_id: str = Field(min_length=1, max_length=80)


class DocumentMeta(BaseModel):
    id: str
    profile_id: str
    doc_type: str
    doc_type_label: str
    title: str
    created_at: str
    updated_at: str
    version: int
    model: str
    language: str
    word_count: int
    passed_verification: bool
    issue_count: int
    project_id: str | None = None


class DocumentDetail(BaseModel):
    meta: DocumentMeta
    markdown: str
    trace: dict[str, Any] = Field(default_factory=dict)
    versions: list[dict[str, Any]] = Field(default_factory=list)


class DocumentUpdate(BaseModel):
    markdown: str


class IssueSuggestion(BaseModel):
    """针对单条待核项的审核建议：index 对应校验意见在列表中的序号（从 0 开始）。"""

    index: int = Field(ge=0, le=50)
    suggestion: str = Field(min_length=1, max_length=1000)

    @field_validator("suggestion")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("该项审核建议不能为空")
        return value


class RegenerateRequest(BaseModel):
    """按审核建议重新生成：逐项建议优先，可另附整体补充说明。

    `issue_feedback` 同时接受 camelCase `issueFeedback`：前端历史上按 JS 习惯
    发送驼峰字段，后端若只认下划线会静默丢字段，导致「只填逐项建议」被判为空
    并返回 422。兼容两种写法避免旧页面缓存再次踩坑。
    """

    model_config = ConfigDict(populate_by_name=True)

    feedback: str = Field(default="", max_length=4000)
    issue_feedback: list[IssueSuggestion] = Field(
        default_factory=list,
        validation_alias=AliasChoices("issue_feedback", "issueFeedback"),
    )

    @field_validator("feedback")
    @classmethod
    def _strip_feedback(cls, value: str) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def _require_any(self):
        if not self.feedback and not self.issue_feedback:
            raise ValueError("请至少为一个待核项填写审核建议")
        return self


class TokenSession(BaseModel):
    """小程序登录结果：明文 token 仅返回一次，服务端只保存哈希。"""

    token: str
    user: dict[str, Any]
    # 含 used/limit/remaining 旧字段与计费来源、系统 Key 免费额度等新字段。
    quota: dict[str, Any]


class UserLLMConfigIn(BaseModel):
    """保存个人模型配置。api_key 留空表示沿用已保存的 Key（便于只改地址或模型名）。"""

    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=120)
    api_key: str = Field(default="", max_length=300)


class UserLLMConfigOut(BaseModel):
    """脱敏后的个人配置 + 当前真正生效的来源，供设置页展示。"""

    has_key: bool = False
    api_key_hint: str = ""
    base_url: str = ""
    model: str = ""
    updated_at: str = ""
    effective_source: Literal["personal", "system", "none"] = "none"
    effective_model: str = ""
    effective_base_url: str = ""
    allow_personal_llm_keys: bool = True
    require_personal_llm_key: bool = False
    system_llm_configured: bool = False
    # 当前账号的计费口径：管理员 / 自带 Key 不限次数；其余账号有免费次数上限。
    is_admin: bool = False
    unlimited: bool = False
    system_key_daily_limit: int = 3
    system_key_remaining: int = 0


class UserLLMTestIn(BaseModel):
    """连通性测试：不传 api_key 时用已保存的配置；传了则临时测试表单里的值。"""

    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=120)
    api_key: str = Field(default="", max_length=300)


class UserLLMTestOut(BaseModel):
    ok: bool
    message: str
    model: str = ""


class ConfigResponse(BaseModel):
    version: str
    llm_configured: bool
    llm_model: str
    llm_base_url: str
    api_key_hint: str
    doc_types: dict[str, str]
    max_revisions: int
    message: str = ""
    allow_registration: bool = True
    daily_quota: int = 20
    # 本地部署版（免登录、单用户、用自己的 Key）标记为 true；前端据此跳过登录页与计费 UI。
    standalone: bool = False
    # 小程序据此决定是否显示「微信一键登录」按钮；未配置凭证时为 false。
    wechat_login_enabled: bool = False
    # 是否允许用户自带大模型 Key，以及是否强制自带（关闭系统 Key 兜底）。
    allow_personal_llm_keys: bool = True
    require_personal_llm_key: bool = False
    # 非管理员每天可免费使用系统默认 Key 的次数；管理员与自带 Key 用户不受限。
    system_key_daily_limit: int = 3
