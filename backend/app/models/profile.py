"""申请人档案：所有生成文书唯一的事实来源。

CV / PS / 推荐信中的每一句事实陈述都必须能追溯到本模型中的某个字段。
生成工作流被明确要求：不得编造这里没有记录的事实。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid4().hex[:12]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Basics(BaseModel):
    name_en: str = ""
    name_zh: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    personal_site: str = ""


class Education(BaseModel):
    id: str = Field(default_factory=new_id)
    school: str = ""
    degree: str = "Bachelor"
    major: str = ""
    gpa: str = ""
    gpa_scale: str = "4.0"
    # 港新院校普遍审核百分制均分；留空表示未提供，事实清单只在有值时展示。
    gpa_average: str = ""
    ranking: str = ""
    start_date: str = ""
    end_date: str = ""
    relevant_courses: list[str] = Field(default_factory=list)
    thesis: str = ""
    highlights: str = ""


class Experience(BaseModel):
    id: str = Field(default_factory=new_id)
    type: str = "project"  # research | internship | work | project | volunteer | competition
    org: str = ""
    role: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    related_recommender: str = ""


class Award(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str = ""
    issuer: str = ""
    date: str = ""
    detail: str = ""


class SkillGroup(BaseModel):
    id: str = Field(default_factory=new_id)
    category: str = ""
    items: list[str] = Field(default_factory=list)


class TestScore(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: str = ""  # IELTS | TOEFL | GRE | GMAT | other
    total: str = ""
    breakdown: str = ""
    date: str = ""


class TargetProgram(BaseModel):
    id: str = Field(default_factory=new_id)
    university: str = ""
    program: str = ""
    degree_type: str = "Taught Master"
    region: str = ""
    intake: str = ""
    deadline: str = ""  # user-supplied; always verify against the official page
    language_requirement: str = ""
    curriculum_notes: str = ""
    faculty_notes: str = ""
    why_fit: str = ""
    notes: str = ""


class Recommender(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str = ""
    title: str = ""
    affiliation: str = ""
    email: str = ""
    relation: str = ""  # how they know the applicant
    known_since: str = ""
    observed_strengths: list[str] = Field(default_factory=list)
    tone: str = "academic"  # academic | professional
    notes: str = ""


class ApplicantProfile(BaseModel):
    id: str = Field(default_factory=new_id)
    label: str = "我的申请档案"
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)

    basics: Basics = Field(default_factory=Basics)
    education: list[Education] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    test_scores: list[TestScore] = Field(default_factory=list)
    target_programs: list[TargetProgram] = Field(default_factory=list)
    recommenders: list[Recommender] = Field(default_factory=list)

    career_goal: str = ""
    additional_notes: str = ""
    writing_constraints: str = ""
