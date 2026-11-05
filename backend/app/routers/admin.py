import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, Booking, Institution, MealSchedule, SurplusListing, User
from ..security import Ctx, need
from ..util import DEFAULT_SETTINGS, audit, merged_settings

router = APIRouter(tags=["admin"])


@router.get("/institution")
def get_inst(ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    i = db.get(Institution, ctx.inst_id)
    return {"id": i.id, "name": i.name, "code": i.code, "data_mode": i.data_mode, "settings": merged_settings(i)}


class InstIn(BaseModel):
    name: Optional[str] = None
    settings: Optional[dict] = None


def _validate(s: dict):
    try:
        if not 0 <= float(s["booking_cutoff_hours"]) <= 72 or not 0 <= float(s["waste_alert_pct"]) <= 100 or not 0 <= float(s["prep_buffer_pct"]) <= 50:
            raise ValueError
        for m, t in s["meal_times"].items():
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
                raise ValueError
        e = s["eligibility"]
        if not 0 < float(e["max_hours_since_prep"]) <= 48 or not isinstance(e["allowed_categories"], list):
            raise ValueError
    except Exception:
        raise HTTPException(422, "Invalid settings values")


@router.put("/institution")
def put_inst(b: InstIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    i = db.get(Institution, ctx.inst_id)
    if b.name:
        i.name = b.name.strip()[:200]
    if b.settings is not None:
        merged = {**merged_settings(i)}
        for k, v in b.settings.items():
            if k in DEFAULT_SETTINGS:
                merged[k] = {**merged[k], **v} if isinstance(v, dict) else v
        _validate(merged)
        i.settings = merged
    audit(db, ctx.user, "update_institution", "institution", i.id); db.commit()
    return get_inst(ctx, db)


@router.get("/admin/overview")
def overview(ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    roles = dict(db.query(User.role, func.count()).group_by(User.role).all())
    return {"institutions": db.query(Institution).count(), "users_by_role": roles, "meal_schedules": db.query(MealSchedule).count(),
            "bookings": db.query(Booking).count(), "surplus_listings": db.query(SurplusListing).count(),
            "pending_partners": db.query(User).filter_by(role="ngo", is_approved=False).count()}


@router.get("/admin/institutions")
def institutions(ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    return [{"id": i.id, "name": i.name, "code": i.code, "data_mode": i.data_mode, "users": db.query(User).filter_by(institution_id=i.id).count()} for i in db.query(Institution)]


class NewInst(BaseModel):
    name: str
    code: str


@router.post("/admin/institutions", status_code=201)
def new_inst(b: NewInst, ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    if db.query(Institution).filter_by(code=b.code).first():
        raise HTTPException(409, "Code already exists")
    i = Institution(name=b.name, code=b.code, data_mode="real", settings={})
    db.add(i); audit(db, ctx.user, "create_institution", "institution", None, b.name); db.commit()
    return {"id": i.id}


@router.get("/admin/audit")
def audit_log(limit: int = 100, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    q = db.query(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id)
    if ctx.user.role != "super_admin":
        q = q.filter(User.institution_id == ctx.inst_id)
    return [{"id": a.id, "user": e, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "detail": a.detail, "created_at": a.created_at}
            for a, e in q.order_by(AuditLog.id.desc()).limit(min(limit, 500))]
