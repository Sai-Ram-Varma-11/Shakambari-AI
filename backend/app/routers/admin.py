import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    AuditLog,
    Booking,
    ConsumptionRecord,
    Institution,
    InstitutionRequest,
    MealSchedule,
    MenuItem,
    PreparationRecord,
    SurplusListing,
    User,
    WasteRecord,
)
from ..security import Ctx, need
from ..util import DEFAULT_SETTINGS, audit, local_now, merged_settings

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


@router.get("/admin/institution-requests")
def institution_requests(ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    rows = db.query(InstitutionRequest).order_by(InstitutionRequest.created_at.desc()).limit(200)
    return [{
        "id": r.id,
        "name": r.name,
        "code": r.code,
        "requester_name": r.requester_name,
        "email": r.email,
        "phone": r.phone,
        "message": r.message,
        "status": r.status,
        "created_at": r.created_at,
    } for r in rows]


class InstitutionRequestDecision(BaseModel):
    approve: bool


@router.post("/admin/institution-requests/{request_id}/decision")
def decide_institution_request(
    request_id: int,
    b: InstitutionRequestDecision,
    ctx: Ctx = Depends(need()),
    db: Session = Depends(get_db),
):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    request = db.get(InstitutionRequest, request_id)
    if not request:
        raise HTTPException(404, "Mess registration request not found")
    if request.status != "pending":
        raise HTTPException(409, "This request has already been reviewed")

    if not b.approve:
        request.status = "rejected"
        request.reviewed_by = ctx.user.id
        request.reviewed_at = local_now()
        audit(db, ctx.user, "reject_institution_request", "institution_request", request.id, request.name)
        db.commit()
        return {"status": request.status}

    if db.query(Institution).filter(func.lower(Institution.code) == request.code.lower()).first():
        raise HTTPException(409, "A mess with this code has already been registered")
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(409, "An account with the request email already exists")

    institution = Institution(name=request.name, code=request.code, data_mode="real", settings={})
    db.add(institution)
    db.flush()
    owner = User(
        institution_id=institution.id,
        email=request.email,
        name=request.requester_name,
        password_hash=request.password_hash,
        role="mess_admin",
        phone=request.phone,
        is_active=True,
        is_approved=True,
        email_verified=True,
        token_version=1,
    )
    db.add(owner)
    request.status = "approved"
    request.institution_id = institution.id
    request.reviewed_by = ctx.user.id
    request.reviewed_at = local_now()
    audit(db, ctx.user, "approve_institution_request", "institution", institution.id, request.name)
    db.commit()
    return {"status": request.status, "institution_id": institution.id}


@router.get("/admin/institutions/{institution_id}/daily")
def institution_daily_records(
    institution_id: int,
    on: date,
    ctx: Ctx = Depends(need()),
    db: Session = Depends(get_db),
):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    institution = db.get(Institution, institution_id)
    if not institution:
        raise HTTPException(404, "Institution not found")

    schedules = (
        db.query(MealSchedule)
        .filter(MealSchedule.institution_id == institution_id, MealSchedule.date == on)
        .order_by(MealSchedule.meal_type)
        .all()
    )
    result = []
    for schedule in schedules:
        booking_count = db.query(Booking).filter_by(schedule_id=schedule.id, status="booked").count()
        dishes = (
            db.query(MenuItem, PreparationRecord, ConsumptionRecord)
            .join(
                PreparationRecord,
                (PreparationRecord.menu_item_id == MenuItem.id)
                & (PreparationRecord.schedule_id == schedule.id),
            )
            .outerjoin(
                ConsumptionRecord,
                (ConsumptionRecord.menu_item_id == MenuItem.id)
                & (ConsumptionRecord.schedule_id == schedule.id),
            )
            .filter(MenuItem.institution_id == institution_id)
            .all()
        )
        dish_records = []
        for item, preparation, consumption in dishes:
            waste = (
                db.query(func.sum(WasteRecord.leftover_qty), func.sum(WasteRecord.edible_qty), func.sum(WasteRecord.inedible_qty))
                .filter(WasteRecord.schedule_id == schedule.id, WasteRecord.menu_item_id == item.id)
                .first()
            )
            leftover = waste[0] if waste and waste[0] is not None else max(
                preparation.prepared_qty - (consumption.consumed_qty if consumption else 0), 0
            )
            dish_records.append({
                "dish": item.name,
                "prepared_kg": preparation.prepared_qty,
                "consumed_kg": consumption.consumed_qty if consumption else None,
                "leftover_kg": round(leftover, 2),
                "edible_kg": waste[1] or 0 if waste else 0,
                "inedible_kg": waste[2] or 0 if waste else 0,
            })
        result.append({
            "schedule_id": schedule.id,
            "meal_type": schedule.meal_type,
            "service_status": schedule.service_status,
            "bookings": booking_count,
            "headcount": schedule.headcount,
            "dishes": dish_records,
        })

    return {"institution": institution.name, "date": on.isoformat(), "meals": result}


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
    db.add(i)
    db.flush()
    audit(db, ctx.user, "create_institution", "institution", i.id, b.name)
    db.commit()
    return {"id": i.id}


@router.get("/admin/audit")
def audit_log(limit: int = 100, offset: int = 0, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    q = db.query(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id)
    if ctx.user.role != "super_admin":
        q = q.filter(User.institution_id == ctx.inst_id)
    return [{"id": a.id, "user": e, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "detail": a.detail, "created_at": a.created_at}
            for a, e in q.order_by(AuditLog.id.desc()).offset(offset).limit(min(limit, 500))]
