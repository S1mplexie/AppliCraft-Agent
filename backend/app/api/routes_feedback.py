"""用户反馈建议：登录用户可提交，仅管理员可查看。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Feedback, User
from app.db.session import get_db

router = APIRouter(prefix="/feedback", tags=["feedback"])

MAX_CONTENT_CHARS = 2000
MAX_ITEMS = 200


class FeedbackCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


@router.post("", status_code=201)
def submit_feedback(
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """提交反馈建议；归属提交者本人，长度截断到上限，不回传给其他用户。

    本地部署版（standalone）没有数据库：直接确认接收、不落库（本地单用户无需汇聚反馈）。
    """
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="反馈内容不能为空")
    if get_settings().standalone:
        return {"id": 0, "content": content[:MAX_CONTENT_CHARS], "created_at": ""}
    item = Feedback(user_id=user.id, content=content[:MAX_CONTENT_CHARS])
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "content": item.content,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }


@router.get("")
def list_feedback(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """管理员查看全部反馈（最新在前，上限 200 条），附带提交者邮箱与显示名。

    本地部署版（standalone）无管理员概念，直接返回空列表。
    """
    if get_settings().standalone:
        return {"items": []}
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="仅管理员可查看用户反馈")
    rows = db.execute(
        select(Feedback, User)
        .join(User, Feedback.user_id == User.id)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .limit(MAX_ITEMS)
    ).all()
    items = [
        {
            "id": fb.id,
            "content": fb.content,
            "created_at": fb.created_at.isoformat() if fb.created_at else "",
            "user_email": u.email,
            "user_name": u.display_name or "",
        }
        for fb, u in rows
    ]
    return {"items": items}