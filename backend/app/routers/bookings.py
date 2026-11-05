from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..food_policy import is_eligible_menu_item
from ..models import (Attendance, Booking, BookingCancellation, DishPreference, MealSchedule, MenuItem, Rating,
                      ScheduleDish, User)
from ..security import Ctx, get_ctx, need
from ..util import audit, local_now, notify

router = APIRouter(tags=["student-demand"])


def _sched(db, sid, ctx):
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
        dishes = db.query(MenuItem).join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id).filter(
            ScheduleDish.schedule_id == s.id
        ).all()
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
        bk = Booking(schedule_id=s.id, student_id=ctx.user.id); db.add(bk)
    audit(db, ctx.user, "book_meal", "meal_schedule", s.id)
    notify(db, [ctx.user.id], "Meal booked", f"{s.meal_type.title()} on {s.date} is confirmed.", "/history")
    db.commit()
    return {"schedule_id": s.id, "status": "booked"}


class CancelIn(BaseModel):
    reason: Optional[str] = None


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


@router.get("/bookings/mine")
def my_bookings(limit: int = 60, ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    rows = (db.query(Booking, MealSchedule).join(MealSchedule, MealSchedule.id == Booking.schedule_id)
            .filter(Booking.student_id == ctx.user.id).order_by(MealSchedule.date.desc()).limit(min(limit, 200)).all())
    att = {sid for (sid,) in db.query(Attendance.schedule_id).filter(Attendance.student_id == ctx.user.id)}
    rated = {(m, sid) for m, sid in db.query(Rating.menu_item_id, Rating.schedule_id).filter(Rating.student_id == ctx.user.id)}
    out = []
    for b, s in rows:
        dishes = db.query(MenuItem).join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id).filter(ScheduleDish.schedule_id == s.id).all()
        out.append({"schedule_id": s.id, "date": s.date.isoformat(), "meal_type": s.meal_type, "status": b.status,
                    "attended": s.id in att, "dishes": [{"id": d.id, "name": d.name, "rated": (d.id, s.id) in rated} for d in dishes]})
    return out


@router.get("/bookings/stats/mine")
def my_stats(ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    uid = ctx.user.id
    booked = db.query(Booking).filter_by(student_id=uid, status="booked").count()
    cancelled = db.query(Booking).filter_by(student_id=uid, status="cancelled").count()
    attended = db.query(Attendance).filter_by(student_id=uid).count()
    attended_booked = db.query(Attendance).filter_by(student_id=uid, was_booked=True).count()
    return {"booked": booked, "cancelled": cancelled, "attended": attended, "no_shows": max(booked - attended_booked, 0),
            "attendance_rate": round(attended_booked / booked * 100, 1) if booked else None}


class RateIn(BaseModel):
    menu_item_id: int
    schedule_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=500)


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
            raise HTTPException(400, "You can rate a dish from a meal you attended")
    r = db.query(Rating).filter_by(student_id=ctx.user.id, menu_item_id=b.menu_item_id, schedule_id=b.schedule_id).first()
    if r:
        r.rating, r.comment = b.rating, b.comment
    else:
        db.add(Rating(student_id=ctx.user.id, menu_item_id=b.menu_item_id, schedule_id=b.schedule_id, rating=b.rating, comment=b.comment))
    db.commit()
    return {"ok": True}


class PrefIn(BaseModel):
    menu_item_id: int
    preference: Optional[str] = None  # like | dislike | None to clear


@router.put("/bookings/preferences")
def set_pref(b: PrefIn, ctx: Ctx = Depends(need("student")), db: Session = Depends(get_db)):
    item = db.get(MenuItem, b.menu_item_id)
    if not item or item.institution_id != ctx.inst_id:
        raise HTTPException(404, "Dish not found")
    if not is_eligible_menu_item(item):
        raise HTTPException(409, "Only active vegetarian dishes can have preferences")
    if b.preference not in (None, "like", "dislike"):
        raise HTTPException(422, "Preference must be like or dislike")
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
    rows = db.query(DishPreference.menu_item_id, DishPreference.preference, MenuItem).join(
        MenuItem, MenuItem.id == DishPreference.menu_item_id
    ).filter(DishPreference.student_id == ctx.user.id).all()
    return {mid: preference for mid, preference, item in rows if is_eligible_menu_item(item)}


# ---- manager / kitchen views of Module 4 data ----
@router.get("/bookings/schedule/{sid}/summary")
def summary(sid: int, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, sid, ctx)
    c = dict(db.query(Booking.status, func.count()).filter_by(schedule_id=sid).group_by(Booking.status).all())
    a = db.query(Attendance).filter_by(schedule_id=sid).count()
    ab = db.query(Attendance).filter_by(schedule_id=sid, was_booked=True).count()
    active = c.get("booked", 0)
    return {"schedule_id": sid, "total_bookings": sum(c.values()), "active_bookings": active, "cancellations": c.get("cancelled", 0),
            "marked_attendance": a, "headcount": s.headcount, "booked_and_attended": ab, "no_shows": max(active - ab, 0) if a else None,
            "unbooked_attended": a - ab}


@router.get("/bookings/participation")
def participation(days: int = 30, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    """Module 4 statistics: bookings vs attendance by meal over the last N days (recorded data only)."""
    since = local_now().date() - timedelta(days=min(days, 365))
    out = []
    for s in db.query(MealSchedule).filter(MealSchedule.institution_id == ctx.inst_id, MealSchedule.date >= since, MealSchedule.headcount != None).all():  # noqa
        n = db.query(Booking).filter_by(schedule_id=s.id, status="booked").count()
        out.append((s.meal_type, n, s.headcount))
    agg = {}
    for m, n, h in out:
        a = agg.setdefault(m, [0, 0, 0]); a[0] += n; a[1] += h; a[2] += 1
    return [{"meal_type": m, "meals": v[2], "avg_active_bookings": round(v[0] / v[2], 1), "avg_attendance": round(v[1] / v[2], 1),
             "attendance_per_booking": round(v[1] / v[0], 2) if v[0] else None} for m, v in agg.items()]


class MarkIn(BaseModel):
    student_id: Optional[int] = None
    student_email: Optional[str] = None


@router.post("/attendance/{sid}/mark", status_code=201)
def mark(sid: int, b: MarkIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, sid, ctx)
    u = db.get(User, b.student_id) if b.student_id else db.query(User).filter(User.email == (b.student_email or "").lower()).first()
    if not u or u.role != "student" or u.institution_id != ctx.inst_id:
        raise HTTPException(404, "Student not found")
    if db.query(Attendance).filter_by(schedule_id=sid, student_id=u.id).first():
        raise HTTPException(409, "Attendance already marked")
    booked = db.query(Booking).filter_by(schedule_id=sid, student_id=u.id, status="booked").first() is not None
    db.add(Attendance(schedule_id=sid, student_id=u.id, was_booked=booked, marked_by=ctx.user.id))
    s.headcount = (s.headcount or 0) + 1
    db.commit()
    return {"headcount": s.headcount, "was_booked": booked}


class HeadIn(BaseModel):
    headcount: int = Field(ge=0, le=100000)


@router.post("/attendance/{sid}/headcount")
def set_headcount(sid: int, b: HeadIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, sid, ctx)
    s.headcount = b.headcount
    audit(db, ctx.user, "set_headcount", "meal_schedule", sid, str(b.headcount)); db.commit()
    return {"headcount": s.headcount}
