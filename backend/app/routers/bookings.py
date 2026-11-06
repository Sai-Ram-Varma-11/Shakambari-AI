from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..food_policy import is_eligible_menu_item
from ..models import (
    Attendance,
    Booking,
    BookingCancellation,
    DishPreference,
    Institution,
    MealSchedule,
    MenuItem,
    Rating,
    ScheduleDish,
    StudentProfile,
    User,
)
from ..security import (
    Ctx,
    get_ctx,
    make_meal_pass,
    need,
    read_meal_pass,
)
from ..util import audit, local_now, meal_start, merged_settings, notify

router = APIRouter(tags=["student-demand"])


def _sched(db: Session, sid: int, ctx: Ctx) -> MealSchedule:
    s = db.get(MealSchedule, sid)
    if not s or s.institution_id != ctx.inst_id:
        raise HTTPException(404, "Meal schedule not found")
    return s


class BookIn(BaseModel):
    schedule_id: int


@router.post("/bookings", status_code=201)
def book(b: BookIn, ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    s = _sched(db, b.schedule_id, ctx)
    if s.date >= local_now().date():
        dishes = (
            db.query(MenuItem)
            .join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id)
            .filter(ScheduleDish.schedule_id == s.id)
            .all()
        )
        if not dishes or any(not is_eligible_menu_item(item) for item in dishes):
            raise HTTPException(409, "This meal does not have a verified vegetarian menu")
    if s.is_holiday:
        raise HTTPException(400, "No meal service on this day")
    if local_now() >= s.cutoff_at:
        raise HTTPException(400, "Booking cutoff has passed for this meal")

    bk = db.query(Booking).filter_by(schedule_id=s.id, student_id=ctx.user.id).first()
    if bk and bk.status == "booked":
        raise HTTPException(409, "You have already booked this meal")
    if bk:
        bk.status, bk.updated_at = "booked", local_now()
    else:
        bk = Booking(schedule_id=s.id, student_id=ctx.user.id)
        db.add(bk)
    audit(db, ctx.user, "book_meal", "meal_schedule", s.id)
    notify(db, [ctx.user.id], "Meal booked", f"{s.meal_type.title()} on {s.date} is confirmed.", "/history")
    db.commit()
    return {"schedule_id": s.id, "status": "booked"}


class CancelIn(BaseModel):
    reason: Optional[Annotated[str, StringConstraints(max_length=200, strip_whitespace=True)]] = None


@router.delete("/bookings/{sid}")
def cancel(sid: int, b: CancelIn = CancelIn(), ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    s = _sched(db, sid, ctx)
    bk = db.query(Booking).filter_by(schedule_id=sid, student_id=ctx.user.id, status="booked").first()
    if not bk:
        raise HTTPException(404, "No active booking for this meal")
    if local_now() >= s.cutoff_at:
        raise HTTPException(400, "Cancellation cutoff has passed for this meal")
    bk.status, bk.updated_at = "cancelled", local_now()
    db.add(BookingCancellation(booking_id=bk.id, reason=(b.reason or "")[:200]))
    audit(db, ctx.user, "cancel_meal", "meal_schedule", sid)
    notify(db, [ctx.user.id], "Booking cancelled", f"{s.meal_type.title()} on {s.date} was cancelled.", "/history")
    db.commit()
    return {"schedule_id": sid, "status": "cancelled"}


@router.get("/bookings/{sid}/pass")
def get_meal_pass(sid: int, ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    """Issues a signed, short-lived QR meal pass token for a booked meal."""
    s = _sched(db, sid, ctx)
    bk = db.query(Booking).filter_by(schedule_id=sid, student_id=ctx.user.id, status="booked").first()
    if not bk:
        raise HTTPException(404, "You do not have an active booking for this meal")

    inst = db.get(Institution, s.institution_id)
    cfg = merged_settings(inst)
    m_start = meal_start(s.date, s.meal_type, cfg)
    # Expiry at meal end: 3 hours after scheduled start time
    exp_dt = m_start + timedelta(hours=3)

    now_dt = local_now()
    if now_dt > exp_dt:
        raise HTTPException(400, "This meal service has already concluded")

    token = make_meal_pass(ctx.user.id, s.id, bk.id, exp_dt)
    return {
        "pass_token": token,
        "expires_at": exp_dt.isoformat(),
        "date": s.date.isoformat(),
        "meal_type": s.meal_type,
        "student_name": ctx.user.name,
    }


@router.get("/bookings/mine")
def my_bookings(
    limit: int = Query(default=60, ge=1, le=200),
    ctx: Ctx = Depends(need("student")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Booking, MealSchedule)
        .join(MealSchedule, MealSchedule.id == Booking.schedule_id)
        .filter(Booking.student_id == ctx.user.id)
        .order_by(MealSchedule.date.desc())
        .limit(min(limit, 200))
        .all()
    )
    if not rows:
        return []

    sids = [s.id for _, s in rows]

    # Performance: Avoid N+1 by batch loading dishes, attendance, and ratings
    dishes_query = (
        db.query(ScheduleDish.schedule_id, MenuItem)
        .join(MenuItem, MenuItem.id == ScheduleDish.menu_item_id)
        .filter(ScheduleDish.schedule_id.in_(sids))
        .all()
    )
    schedule_dishes = defaultdict(list)
    for sid, dish in dishes_query:
        schedule_dishes[sid].append(dish)

    att = {sid for (sid,) in db.query(Attendance.schedule_id).filter(Attendance.student_id == ctx.user.id, Attendance.schedule_id.in_(sids))}
    rated = {
        (m, sid)
        for m, sid in db.query(Rating.menu_item_id, Rating.schedule_id).filter(
            Rating.student_id == ctx.user.id, Rating.schedule_id.in_(sids)
        )
    }

    out = []
    for b, s in rows:
        dishes = schedule_dishes.get(s.id, [])
        out.append({
            "schedule_id": s.id,
            "date": s.date.isoformat(),
            "meal_type": s.meal_type,
            "status": b.status,
            "attended": s.id in att,
            "dishes": [
                {"id": d.id, "name": d.name, "diet": d.diet, "rated": (d.id, s.id) in rated}
                for d in dishes
            ],
        })
    return out


@router.get("/bookings/stats/mine")
def my_stats(ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    uid = ctx.user.id
    booked = db.query(Booking).filter_by(student_id=uid, status="booked").count()
    cancelled = db.query(Booking).filter_by(student_id=uid, status="cancelled").count()
    attended = db.query(Attendance).filter_by(student_id=uid).count()
    attended_booked = db.query(Attendance).filter_by(student_id=uid, was_booked=True).count()
    return {
        "booked": booked,
        "cancelled": cancelled,
        "attended": attended,
        "no_shows": max(booked - attended_booked, 0),
        "attendance_rate": round(attended_booked / booked * 100, 1) if booked else None,
    }


class RateIn(BaseModel):
    menu_item_id: int
    schedule_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]] = None


@router.post("/bookings/rate", status_code=201)
def rate(b: RateIn, ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    item = db.get(MenuItem, b.menu_item_id)
    if not item or item.institution_id != ctx.inst_id:
        raise HTTPException(404, "Dish not found")
    if not is_eligible_menu_item(item):
        raise HTTPException(409, "Only active vegetarian dishes can be rated")
    if b.schedule_id:
        s = _sched(db, b.schedule_id, ctx)
        if not db.query(Attendance).filter_by(schedule_id=s.id, student_id=ctx.user.id).first():
            raise HTTPException(400, "You can only rate a dish from a meal you attended")
    r = db.query(Rating).filter_by(student_id=ctx.user.id, menu_item_id=b.menu_item_id, schedule_id=b.schedule_id).first()
    if r:
        r.rating, r.comment = b.rating, b.comment
    else:
        db.add(Rating(student_id=ctx.user.id, menu_item_id=b.menu_item_id, schedule_id=b.schedule_id, rating=b.rating, comment=b.comment))
    db.commit()
    return {"ok": True}


class PrefIn(BaseModel):
    menu_item_id: int
    preference: Optional[Literal["like", "dislike"]] = None


@router.put("/bookings/preferences")
def set_pref(b: PrefIn, ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    item = db.get(MenuItem, b.menu_item_id)
    if not item or item.institution_id != ctx.inst_id:
        raise HTTPException(404, "Dish not found")
    if not is_eligible_menu_item(item):
        raise HTTPException(409, "Only active vegetarian dishes can have preferences")
    p = db.query(DishPreference).filter_by(student_id=ctx.user.id, menu_item_id=b.menu_item_id).first()
    if b.preference is None:
        if p:
            db.delete(p)
    elif p:
        p.preference = b.preference
    else:
        db.add(DishPreference(student_id=ctx.user.id, menu_item_id=b.menu_item_id, preference=b.preference))
    db.commit()
    return {"ok": True}


@router.get("/bookings/preferences")
def get_prefs(ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    rows = (
        db.query(DishPreference.menu_item_id, DishPreference.preference, MenuItem)
        .join(MenuItem, MenuItem.id == DishPreference.menu_item_id)
        .filter(DishPreference.student_id == ctx.user.id)
        .all()
    )
    return {mid: preference for mid, preference, item in rows if is_eligible_menu_item(item)}


@router.get("/bookings/schedule/{sid}/summary")
def summary(sid: int, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, sid, ctx)
    c = dict(db.query(Booking.status, func.count()).filter_by(schedule_id=sid).group_by(Booking.status).all())
    a = db.query(Attendance).filter_by(schedule_id=sid).count()
    ab = db.query(Attendance).filter_by(schedule_id=sid, was_booked=True).count()
    active = c.get("booked", 0)
    return {
        "schedule_id": sid,
        "total_bookings": sum(c.values()),
        "active_bookings": active,
        "cancellations": c.get("cancelled", 0),
        "marked_attendance": a,
        "headcount": s.headcount,
        "booked_and_attended": ab,
        "no_shows": max(active - ab, 0) if a else None,
        "unbooked_attended": a - ab,
    }


@router.get("/bookings/participation")
def participation(days: int = 30, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    since = local_now().date() - timedelta(days=min(days, 365))
    out = []
    for s in db.query(MealSchedule).filter(MealSchedule.institution_id == ctx.inst_id, MealSchedule.date >= since, MealSchedule.headcount != None).all():  # noqa
        n = db.query(Booking).filter_by(schedule_id=s.id, status="booked").count()
        out.append((s.meal_type, n, s.headcount))
    agg = {}
    for m, n, h in out:
        a = agg.setdefault(m, [0, 0, 0])
        a[0] += n
        a[1] += h
        a[2] += 1
    return [
        {
            "meal_type": m,
            "meals": v[2],
            "avg_active_bookings": round(v[0] / v[2], 1),
            "avg_attendance": round(v[1] / v[2], 1),
            "attendance_per_booking": round(v[1] / v[0], 2) if v[0] else None,
        }
        for m, v in agg.items()
    ]


class ScanIn(BaseModel):
    token: str


@router.post("/attendance/{sid}/scan", status_code=201)
def scan_meal_pass(
    sid: int,
    b: ScanIn,
    ctx: Ctx = Depends(need("mess_admin", "kitchen")),
    db: Session = Depends(get_db),
):
    """Kitchen scanner endpoint: verifies signed QR meal pass and marks attendance."""
    s = _sched(db, sid, ctx)

    try:
        p = read_meal_pass(b.token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(400, "Meal pass has expired")
    except Exception:
        raise HTTPException(400, "Invalid or tampered meal pass")

    if p.get("schedule_id") != sid:
        raise HTTPException(400, "Meal pass is for a different meal schedule")

    student_id = int(p.get("student_id", 0))
    u = db.get(User, student_id)
    if not u or u.role != "student" or u.institution_id != ctx.inst_id:
        raise HTTPException(404, "Student not found or does not belong to this institution")

    if db.query(Attendance).filter_by(schedule_id=sid, student_id=u.id).first():
        raise HTTPException(409, f"Attendance already marked for {u.name}")

    # Verify active booking
    bk = db.query(Booking).filter_by(schedule_id=sid, student_id=u.id, status="booked").first()
    was_booked = bk is not None

    db.add(Attendance(schedule_id=sid, student_id=u.id, was_booked=was_booked, marked_by=ctx.user.id))
    s.headcount = (s.headcount or 0) + 1
    audit(db, ctx.user, "scan_attendance", "meal_schedule", sid, f"student={u.id} booked={was_booked}")
    db.commit()

    prof = db.get(StudentProfile, u.id)
    total_scanned = db.query(Attendance).filter_by(schedule_id=sid).count()
    total_booked = db.query(Booking).filter_by(schedule_id=sid, status="booked").count()

    return {
        "status": "success",
        "student_id": u.id,
        "student_name": u.name,
        "diet": prof.diet if prof and prof.diet else "veg",
        "was_booked": was_booked,
        "headcount": s.headcount,
        "total_scanned": total_scanned,
        "total_booked": total_booked,
    }


class MarkIn(BaseModel):
    student_id: Optional[int] = None
    student_email: Optional[str] = None


@router.post("/attendance/{sid}/mark", status_code=201)
def mark(sid: int, b: MarkIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, sid, ctx)
    u = db.get(User, b.student_id) if b.student_id else db.query(User).filter(User.email == (b.student_email or "").strip().lower()).first()
    if not u or u.role != "student" or u.institution_id != ctx.inst_id:
        raise HTTPException(404, "Student not found")
    if db.query(Attendance).filter_by(schedule_id=sid, student_id=u.id).first():
        raise HTTPException(409, "Attendance already marked")
    booked = db.query(Booking).filter_by(schedule_id=sid, student_id=u.id, status="booked").first() is not None
    db.add(Attendance(schedule_id=sid, student_id=u.id, was_booked=booked, marked_by=ctx.user.id))
    s.headcount = (s.headcount or 0) + 1
    audit(db, ctx.user, "mark_attendance", "meal_schedule", sid, f"student={u.id} walk_in={not booked}")
    db.commit()

    total_scanned = db.query(Attendance).filter_by(schedule_id=sid).count()
    total_booked = db.query(Booking).filter_by(schedule_id=sid, status="booked").count()

    return {
        "headcount": s.headcount,
        "was_booked": booked,
        "total_scanned": total_scanned,
        "total_booked": total_booked,
    }


class HeadIn(BaseModel):
    headcount: int = Field(ge=0, le=100000)


@router.post("/attendance/{sid}/headcount")
def set_headcount(sid: int, b: HeadIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, sid, ctx)
    s.headcount = b.headcount
    audit(db, ctx.user, "set_headcount", "meal_schedule", sid, str(b.headcount))
    db.commit()
    return {"headcount": s.headcount}
