"""Skill 市场：内置写作技能、用户导入与生成时的上下文装配。"""
from .service import (
    MAX_USER_SKILLS,
    SKILL_MAX_CHARS,
    SKILL_UPLOAD_MAX_BYTES,
    SkillError,
    build_skill_context,
    builtin_skills,
    get_skill_detail,
    parse_skill_upload,
    public_skill,
)

__all__ = [
    "MAX_USER_SKILLS",
    "SKILL_MAX_CHARS",
    "SKILL_UPLOAD_MAX_BYTES",
    "SkillError",
    "build_skill_context",
    "builtin_skills",
    "get_skill_detail",
    "parse_skill_upload",
    "public_skill",
]
