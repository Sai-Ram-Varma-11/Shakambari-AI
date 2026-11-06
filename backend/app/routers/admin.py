import re
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (AuditLog, Booking, ConsumptionRecord, Institution, InstitutionRequest, MealSchedule,
                      MenuItem, PreparationRecord, ScheduleDish, SurplusListing, User, WasteRecord)
from ..security import Ctx, hash_password, need, rate_limit
from ..util import DEFAULT_SETTINGS, audit, local_now, merged_settings

router = APIRouter(tags=["admin"])
Email = Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)]


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
        if any(not 0 <= float(s["meal_cutoff_hours"][m]) <= 72 for m in ("breakfast", "lunch", "snacks", "dinner")):
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
        if "booking_cutoff_hours" in b.settings and "meal_cutoff_hours" not in b.settings:
            merged["meal_cutoff_hours"] = {
                meal: b.settings["booking_cutoff_hours"] for meal in DEFAULT_SETTINGS["meal_cutoff_hours"]
            }
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


class InstitutionRequestIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    manager_name: str = Field(min_length=2, max_length=120)
    email: Email
    password: str = Field(min_length=8, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=30)


@router.post("/admin/institution-requests", status_code=201)
def request_institution(b: InstitutionRequestIn, request: Request, db: Session = Depends(get_db)):
    if not re.search(r"[A-Za-z]", b.password) or not re.search(r"\d", b.password):
        raise HTTPException(422, "Password must include a letter and a number")
    rate_limit(f"institution-request:{request.client.host if request.client else '-'}", 10, 300)
    code, email = b.code.strip().upper(), b.email.strip().lower()
    if db.query(Institution).filter(func.lower(Institution.code) == code.lower()).first():
        raise HTTPException(409, "That mess code is already registered")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(409, "That email is already registered")
    if db.query(InstitutionRequest).filter(
        (func.lower(InstitutionRequest.code) == code.lower()) | (func.lower(InstitutionRequest.email) == email),
        InstitutionRequest.status == "pending",
    ).first():
        raise HTTPException(409, "A pending request already uses that mess code or email")
    req = InstitutionRequest(name=b.name.strip(), code=code, manager_name=b.manager_name.strip(), email=email,
                             password_hash=hash_password(b.password), phone=b.phone)
    db.add(req)
    db.commit()
    return {"id": req.id, "message": "Request submitted. You can sign in after an administrator approves it."}


@router.get("/admin/institution-requests")
def institution_requests(ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    return [{"id": r.id, "name": r.name, "code": r.code, "manager_name": r.manager_name,
             "email": r.email, "phone": r.phone, "created_at": r.created_at, "status": r.status}
            for r in db.query(InstitutionRequest).filter_by(status="pending").order_by(InstitutionRequest.created_at)]


@router.post("/admin/institution-requests/{request_id}/approve")
def approve_institution_request(request_id: int, ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    req = db.get(InstitutionRequest, request_id)
    if not req or req.status != "pending":
        raise HTTPException(404, "Pending institution request not found")
    if db.query(Institution).filter(func.lower(Institution.code) == req.code.lower()).first():
        raise HTTPException(409, "That mess code is already registered")
    if db.query(User).filter(func.lower(User.email) == req.email.lower()).first():
        raise HTTPException(409, "That email is already registered")
    inst = Institution(name=req.name, code=req.code, data_mode="real", settings={})
    db.add(inst)
    db.flush()
    owner = User(institution_id=inst.id, email=req.email, name=req.manager_name,
                 password_hash=req.password_hash, role="mess_admin", phone=req.phone, is_approved=True)
    db.add(owner)
    req.status, req.reviewed_by, req.reviewed_at = "approved", ctx.user.id, local_now()
    audit(db, ctx.user, "approve_institution_request", "institution_request", req.id, req.name)
    db.commit()
    return {"institution_id": inst.id, "manager_id": owner.id}


@router.post("/admin/institution-requests/{request_id}/reject")
def reject_institution_request(request_id: int, ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    req = db.get(InstitutionRequest, request_id)
    if not req or req.status != "pending":
        raise HTTPException(404, "Pending institution request not found")
    req.status, req.reviewed_by, req.reviewed_at = "rejected", ctx.user.id, local_now()
    audit(db, ctx.user, "reject_institution_request", "institution_request", req.id, req.name)
    db.commit()
    return {"ok": True}


@router.get("/admin/institutions/{institution_id}/daily")
def institution_daily(institution_id: int, day: date, ctx: Ctx = Depends(need()), db: Session = Depends(get_db)):
    if ctx.user.role != "super_admin":
        raise HTTPException(403, "Super administrator only")
    inst = db.get(Institution, institution_id)
    if not inst:
        raise HTTPException(404, "Institution not found")
    schedules = db.query(MealSchedule).filter_by(institution_id=institution_id, date=day).order_by(MealSchedule.id).all()
    meals = []
    for schedule in schedules:
        bookings = db.query(func.count(Booking.id)).filter_by(schedule_id=schedule.id, status="booked").scalar()
        prep = {r.menu_item_id: r.prepared_qty for r in db.query(PreparationRecord).filter_by(schedule_id=schedule.id)}
        consumed = {r.menu_item_id: r.consumed_qty for r in db.query(ConsumptionRecord).filter_by(schedule_id=schedule.id)}
        waste = {mid: (left, edible, inedible) for mid, left, edible, inedible in
                 db.query(WasteRecord.menu_item_id, func.sum(WasteRecord.leftover_qty), func.sum(WasteRecord.edible_qty),
                          func.sum(WasteRecord.inedible_qty)).filter_by(schedule_id=schedule.id).group_by(WasteRecord.menu_item_id)}
        items = db.query(MenuItem).join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id).filter(
            ScheduleDish.schedule_id == schedule.id).order_by(MenuItem.name).all()
        dishes = []
        for item in items:
            leftover, edible, inedible = waste.get(item.id, (None, None, None))
            prepared_qty, consumed_qty = prep.get(item.id), consumed.get(item.id)
            if leftover is None and prepared_qty is not None and consumed_qty is not None:
                leftover = max(prepared_qty - consumed_qty, 0)
            dishes.append({"name": item.name, "prepared_kg": prepared_qty, "consumed_kg": consumed_qty,
                           "leftover_kg": leftover, "edible_kg": edible, "inedible_kg": inedible})
        meals.append({"schedule_id": schedule.id, "meal_type": schedule.meal_type, "bookings": bookings,
                      "headcount": schedule.headcount, "service_status": schedule.service_status,
                      "dishes": dishes})
    return {"institution": inst.name, "date": day.isoformat(), "meals": meals}


@router.get("/admin/audit")
def audit_log(limit: int = 100, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    q = db.query(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id)
    if ctx.user.role != "super_admin":
        q = q.filter(User.institution_id == ctx.inst_id)
    return [{"id": a.id, "user": e, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "detail": a.detail, "created_at": a.created_at}
            for a, e in q.order_by(AuditLog.id.desc()).limit(min(limit, 500))]
