"""选校评估：档案硬指标与知识库项目要求的规则比对（确定性，不调用 LLM）。

计费口径（与文书生成一致）：评估是显式扣费动作，必须由用户点击「开始评估」触发（POST，
GET 无副作用不扣费）。系统共享 Key 用户每次评估扣 1 次免费额度（写入 GenerationLog
doc_type='match'，与生成共用每日配额池）；管理员与自有 Key 用户不占用免费次数；
额度耗尽时返回 403。评估失败（status='error'）不计入配额。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import (
    billing_source,
    get_current_user,
    get_user_store,
    has_personal_key,
    quota_info,
    system_key_used,
)
from app.config import Settings, get_settings
from app.db.models import GenerationLog, User
from app.db.session import get_db
from app.matching.engine import evaluate_profile, load_index, load_requirements
from app.storage.filestore import FileStore

router = APIRouter(prefix="/match", tags=["match"])


@router.post("/{profile_id}")
def match_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    store: FileStore = Depends(get_user_store),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    profile = store.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="档案不存在")

    # 本地部署版（standalone）：单用户、用自己的 Key，不存在免费额度与计费，直接评估。
    if settings.standalone:
        result = evaluate_profile(
            profile,
            load_requirements(settings.knowledge_dir),
            load_index(settings.knowledge_dir),
        )
        return {**result, "billing_source": "personal", "quota": None}

    source = billing_source(user, settings, personal_key=has_personal_key(db, user.id, settings))
    if source == "system":
        # 免费额度口径与生成闸门（check_quota）一致：只数 llm_source='system' 的
        # 记录，上限为 settings.system_key_daily_limit（不是 user.daily_quota 总量护栏）。
        free_used = system_key_used(db, user.id)
        free_limit = max(0, settings.system_key_daily_limit)
        if free_used >= free_limit:
            raise HTTPException(
                status_code=403,
                detail="今日免费额度已用完：选校评估与文书生成共用免费次数；可配置自有 Key（不占免费额度）或明日再试。",
            )

    result = evaluate_profile(
        profile,
        load_requirements(settings.knowledge_dir),
        load_index(settings.knowledge_dir),
    )
    db.add(GenerationLog(user_id=user.id, doc_type="match", status="ok", llm_source=source))
    db.commit()
    quota = quota_info(db, user, settings=settings)
    return {**result, "billing_source": source, "quota": quota}