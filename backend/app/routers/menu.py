from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..food_policy import food_is_allowed, is_eligible_menu_item, require_vegetarian_food
from ..models import (MEALS, Booking, Institution, MealSchedule, MenuItem, ScheduleDish)
from ..security import Ctx, get_ctx, need
from ..util import audit, default_cutoff, local_now, merged_settings

router = APIRouter(prefix="/menu", tags=["menu"])
CATS = ("grain", "dal", "curry", "bread", "vegetable", "snack", "beverage", "dairy", "breakfast", "dessert", "other")


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = "other"
    diet: Literal["veg", "vegan"] = "veg"
    ingredients: List[str] = Field(min_length=1, max_length=50)
    portion_kg: float = Field(gt=0, le=2)
    cost_per_kg: float = Field(ge=0, le=100000)
    is_active: bool = True


def item_out(i):
    return {"id": i.id, "name": i.name, "category": i.category, "diet": i.diet, "ingredients": i.ingredients or [], "portion_kg": i.portion_kg,
            "cost_per_kg": i.cost_per_kg, "is_active": i.is_active}


@router.get("/items")
def items(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    if ctx.inst_id is None:
        return []
    rows = db.query(MenuItem).filter_by(institution_id=ctx.inst_id, is_active=True).filter(
        MenuItem.diet.in_(("veg", "vegan"))
    ).order_by(MenuItem.name)
    return [item_out(i) for i in rows if is_eligible_menu_item(i)]


@router.post("/items", status_code=201)
def add_item(b: ItemIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    if b.category not in CATS:
        raise HTTPException(422, "Invalid category")
    require_vegetarian_food(b.name, b.ingredients)
    for ingredient in b.ingredients:
        require_vegetarian_food("ingredient", [ingredient])
    if db.query(MenuItem).filter_by(institution_id=ctx.inst_id, name=b.name.strip()).first():
        raise HTTPException(409, "A dish with this name already exists")
    i = MenuItem(institution_id=ctx.inst_id, **{**b.model_dump(), "name": b.name.strip()})
    db.add(i); audit(db, ctx.user, "create_dish", "menu_item", None, b.name); db.commit()
    return item_out(i)


@router.put("/items/{iid}")
def edit_item(iid: int, b: ItemIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    i = db.get(MenuItem, iid)
    if not i or i.institution_id != ctx.inst_id:
        raise HTTPException(404, "Dish not found")
    if i.diet not in ("veg", "vegan") or not food_is_allowed(i.name, i.ingredients):
        raise HTTPException(409, "Legacy non-vegetarian dishes are preserved as history and cannot be reclassified")
    if b.category not in CATS:
        raise HTTPException(422, "Invalid category")
    require_vegetarian_food(b.name, b.ingredients)
    for ingredient in b.ingredients:
        require_vegetarian_food("ingredient", [ingredient])
    for k, v in b.model_dump().items():
        setattr(i, k, v)
    audit(db, ctx.user, "update_dish", "menu_item", i.id); db.commit()
    return item_out(i)


def sched_out(db, s: MealSchedule, user=None):
    dishes = db.query(MenuItem).join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id).filter(ScheduleDish.schedule_id == s.id).all()
    dishes = [i for i in dishes if is_eligible_menu_item(i)]
    counts = dict(db.query(Booking.status, func.count()).filter(Booking.schedule_id == s.id).group_by(Booking.status).all())
    d = {"id": s.id, "date": s.date.isoformat(), "meal_type": s.meal_type, "cutoff_at": s.cutoff_at.isoformat(),
         "is_holiday": s.is_holiday, "event": s.event, "headcount": s.headcount, "service_status": s.service_status,
         "active_bookings": counts.get("booked", 0), "cancellations": counts.get("cancelled", 0),
         "bookable": (not s.is_holiday) and local_now() < s.cutoff_at, "dishes": [item_out(i) for i in dishes]}
    if user is not None and user.role == "student":
        b = db.query(Booking).filter_by(schedule_id=s.id, student_id=user.id).first()
        d["my_booking"] = b.status if b else None
    return d


@router.get("/schedules")
def schedules(start: Optional[date] = None, end: Optional[date] = None, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    if ctx.inst_id is None:
        return []
    start = start or local_now().date()
    end = end or start + timedelta(days=6)
    if (end - start).days > 92:
        raise HTTPException(422, "Range too large (max 92 days)")
    q = db.query(MealSchedule).filter(MealSchedule.institution_id == ctx.inst_id, MealSchedule.date >= start, MealSchedule.date <= end)
    order = {m: n for n, m in enumerate(MEALS)}
    rows = sorted(q.all(), key=lambda s: (s.date, order.get(s.meal_type, 9)))
    return [sched_out(db, s, ctx.user) for s in rows]


@router.get("/schedules/{sid}")
def one_schedule(sid: int, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    s = db.get(MealSchedule, sid)
    if not s or s.institution_id != ctx.inst_id:
        raise HTTPException(404, "Meal schedule not found")
    return sched_out(db, s, ctx.user)


class SchedIn(BaseModel):
    date: date
    meal_type: str
    dish_ids: List[int] = []
    is_holiday: bool = False
    event: Optional[str] = None
    cutoff_at: Optional[datetime] = None


def _set_dishes(db, s, dish_ids, inst_id):
    ids = set(dish_ids)
    items = db.query(MenuItem).filter(
        MenuItem.institution_id == inst_id,
        MenuItem.id.in_(ids),
        MenuItem.is_active.is_(True),
        MenuItem.diet.in_(("veg", "vegan")),
    ).all() if ids else []
    ok = {i.id for i in items if is_eligible_menu_item(i)}
    if ok != ids:
        raise HTTPException(422, "One or more dishes do not belong to this institution")
    db.query(ScheduleDish).filter_by(schedule_id=s.id).delete()
    for i in ids:
        db.add(ScheduleDish(schedule_id=s.id, menu_item_id=i))


@router.post("/schedules", status_code=201)
def create_schedule(b: SchedIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    if b.meal_type not in MEALS:
        raise HTTPException(422, "Invalid meal type")
    if db.query(MealSchedule).filter_by(institution_id=ctx.inst_id, date=b.date, meal_type=b.meal_type).first():
        raise HTTPException(409, "A schedule already exists for that date and meal")
    cfg = merged_settings(db.get(Institution, ctx.inst_id))
    s = MealSchedule(institution_id=ctx.inst_id, date=b.date, meal_type=b.meal_type, is_holiday=b.is_holiday,
                     event=b.event, cutoff_at=b.cutoff_at or default_cutoff(b.date, b.meal_type, cfg))
    db.add(s); db.flush(); _set_dishes(db, s, b.dish_ids, ctx.inst_id)
    audit(db, ctx.user, "create_schedule", "meal_schedule", s.id, f"{b.date} {b.meal_type}"); db.commit()
    return sched_out(db, s)


@router.put("/schedules/{sid}")
def update_schedule(sid: int, b: SchedIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    s = db.get(MealSchedule, sid)
    if not s or s.institution_id != ctx.inst_id:
        raise HTTPException(404, "Meal schedule not found")
    s.is_holiday, s.event = b.is_holiday, b.event
    if b.cutoff_at:
        s.cutoff_at = b.cutoff_at
    _set_dishes(db, s, b.dish_ids, ctx.inst_id)
    audit(db, ctx.user, "update_schedule", "meal_schedule", s.id); db.commit()
    return sched_out(db, s)


@router.delete("/schedules/{sid}")
def delete_schedule(sid: int, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    s = db.get(MealSchedule, sid)
    if not s or s.institution_id != ctx.inst_id:
        raise HTTPException(404, "Meal schedule not found")
    if db.query(Booking).filter_by(schedule_id=sid).count() or s.headcount is not None:
        raise HTTPException(409, "Schedules with bookings or attendance cannot be deleted")
    db.query(ScheduleDish).filter_by(schedule_id=sid).delete()
    db.delete(s); audit(db, ctx.user, "delete_schedule", "meal_schedule", sid); db.commit()
    return {"ok": True}


class StatusIn(BaseModel):
    service_status: str


@router.patch("/schedules/{sid}/status")
def set_status(sid: int, b: StatusIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = db.get(MealSchedule, sid)
    if not s or s.institution_id != ctx.inst_id:
        raise HTTPException(404, "Meal schedule not found")
    if b.service_status not in ("planned", "preparing", "served", "closed"):
        raise HTTPException(422, "Invalid status")
    s.service_status = b.service_status
    audit(db, ctx.user, "meal_status", "meal_schedule", s.id, b.service_status); db.commit()
    return sched_out(db, s)
