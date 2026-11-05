from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..food_policy import is_eligible_menu_item
from ..models import (ConsumptionRecord, Institution, MealSchedule, MenuItem, PreparationRecord, ScheduleDish, WasteRecord)
from ..security import Ctx, need
from ..services import forecast
from ..util import audit, local_now, merged_settings, notify, staff_ids

router = APIRouter(prefix="/kitchen", tags=["kitchen"])


def _sched(db, sid, ctx):
    s = db.get(MealSchedule, sid)
    if not s or s.institution_id != ctx.inst_id:
        raise HTTPException(404, "Meal schedule not found")
    return s


def plan(db, s):
    reco = forecast.latest_dish_reco(db, s.id)
    out = []
    for it in db.query(MenuItem).join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id).filter(
        ScheduleDish.schedule_id == s.id, MenuItem.is_active.is_(True), MenuItem.diet.in_(("veg", "vegan"))
    ):
        if not is_eligible_menu_item(it):
            continue
        p = db.query(PreparationRecord).filter_by(schedule_id=s.id, menu_item_id=it.id).first()
        c = db.query(ConsumptionRecord).filter_by(schedule_id=s.id, menu_item_id=it.id).first()
        ws = db.query(WasteRecord).filter_by(schedule_id=s.id, menu_item_id=it.id, source="manual").all()
        out.append({"menu_item_id": it.id, "name": it.name, "portion_kg": it.portion_kg, "recommended_kg": reco.get(it.id),
                    "prepared_kg": p.prepared_qty if p else None, "available_kg": p.available_qty if p else None,
                    "consumed_kg": c.consumed_qty if c else None, "leftover_kg": sum(w.leftover_qty for w in ws) if c else None,
                    "edible_kg": sum(w.edible_qty for w in ws) if c else None})
    return {"schedule_id": s.id, "date": s.date.isoformat(), "meal_type": s.meal_type, "service_status": s.service_status,
            "headcount": s.headcount, "dishes": out}


@router.get("/plan/{sid}")
def get_plan(sid: int, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    return plan(db, _sched(db, sid, ctx))


class PrepItem(BaseModel):
    menu_item_id: int
    prepared_qty: float = Field(ge=0, le=100000)
    available_qty: Optional[float] = Field(default=None, ge=0, le=100000)


class PrepIn(BaseModel):
    schedule_id: int
    items: List[PrepItem]


def _check_items(db, s, ids):
    valid = {
        item_id for item_id, item in db.query(ScheduleDish.menu_item_id, MenuItem)
        .join(MenuItem, MenuItem.id == ScheduleDish.menu_item_id)
        .filter(ScheduleDish.schedule_id == s.id)
        if is_eligible_menu_item(item)
    }
    if not ids or any(i not in valid for i in ids):
        raise HTTPException(422, "Items must be dishes scheduled for this meal")


@router.post("/preparation")
def record_prep(b: PrepIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, b.schedule_id, ctx)
    _check_items(db, s, [i.menu_item_id for i in b.items])
    reco = forecast.latest_dish_reco(db, s.id)
    flagged = []
    for i in b.items:
        r = db.query(PreparationRecord).filter_by(schedule_id=s.id, menu_item_id=i.menu_item_id).first()
        if not r:
            r = PreparationRecord(schedule_id=s.id, menu_item_id=i.menu_item_id, prepared_qty=i.prepared_qty); db.add(r)
        r.prepared_qty, r.available_qty, r.recorded_by, r.recommended_qty = i.prepared_qty, i.available_qty, ctx.user.id, reco.get(i.menu_item_id)
        if r.recommended_qty and abs(i.prepared_qty - r.recommended_qty) / r.recommended_qty > 0.15:
            flagged.append(db.get(MenuItem, i.menu_item_id).name)
    if s.service_status == "planned":
        s.service_status = "preparing"
    if flagged:
        notify(db, staff_ids(db, ctx.inst_id), "Preparation differs from prediction", f"{s.meal_type.title()} {s.date}: {', '.join(flagged)} differ by >15% from the recommendation.", "/prep")
    audit(db, ctx.user, "record_preparation", "meal_schedule", s.id); db.commit()
    return plan(db, s)


class OutItem(BaseModel):
    menu_item_id: int
    consumed_qty: float = Field(ge=0, le=100000)
    leftover_qty: float = Field(ge=0, le=100000)
    edible_qty: float = Field(default=0, ge=0, le=100000)
    notes: Optional[str] = Field(default=None, max_length=300)


class OutIn(BaseModel):
    schedule_id: int
    items: List[OutItem]


def _bg_retrain(inst_id):
    db = SessionLocal()
    try:
        forecast.maybe_retrain(db, inst_id)
    finally:
        db.close()


@router.post("/outcome")
def record_outcome(b: OutIn, bg: BackgroundTasks, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s = _sched(db, b.schedule_id, ctx)
    _check_items(db, s, [i.menu_item_id for i in b.items])
    for i in b.items:
        p = db.query(PreparationRecord).filter_by(schedule_id=s.id, menu_item_id=i.menu_item_id).first()
        if not p:
            raise HTTPException(400, "Record the prepared quantity before recording consumption/leftovers")
        if i.edible_qty > i.leftover_qty + 1e-9:
            raise HTTPException(422, "Edible surplus cannot exceed the leftover quantity")
        if i.consumed_qty + i.leftover_qty > p.prepared_qty * 1.05 + 1e-9:
            raise HTTPException(422, f"Consumed + leftover exceeds the prepared quantity ({p.prepared_qty} kg)")
    for i in b.items:
        c = db.query(ConsumptionRecord).filter_by(schedule_id=s.id, menu_item_id=i.menu_item_id).first()
        if c:
            c.consumed_qty, c.recorded_by = i.consumed_qty, ctx.user.id
        else:
            db.add(ConsumptionRecord(schedule_id=s.id, menu_item_id=i.menu_item_id, consumed_qty=i.consumed_qty, recorded_by=ctx.user.id))
        db.query(WasteRecord).filter_by(schedule_id=s.id, menu_item_id=i.menu_item_id, source="manual").delete()
        db.add(WasteRecord(schedule_id=s.id, menu_item_id=i.menu_item_id, leftover_qty=i.leftover_qty, edible_qty=i.edible_qty,
                           inedible_qty=i.leftover_qty - i.edible_qty, source="manual", notes=i.notes, recorded_by=ctx.user.id))
    db.flush()
    n_dishes = db.query(ScheduleDish).filter_by(schedule_id=s.id).count()
    n_done = db.query(ConsumptionRecord).filter_by(schedule_id=s.id).count()
    s.service_status = "closed" if n_done >= n_dishes else "served"
    prep = sum(p.prepared_qty for p in db.query(PreparationRecord).filter_by(schedule_id=s.id))
    left = sum(w.leftover_qty for w in db.query(WasteRecord).filter_by(schedule_id=s.id))
    thr = merged_settings(db.get(Institution, ctx.inst_id))["waste_alert_pct"]
    if prep > 0 and left / prep * 100 > thr:
        notify(db, staff_ids(db, ctx.inst_id), "Food waste above threshold", f"{s.meal_type.title()} {s.date}: waste {left / prep * 100:.1f}% (threshold {thr}%).", "/waste")
    audit(db, ctx.user, "record_outcome", "meal_schedule", s.id); db.commit()
    bg.add_task(_bg_retrain, ctx.inst_id)
    return plan(db, s)


class ObsIn(BaseModel):
    schedule_id: int
    menu_item_id: Optional[int] = None
    note: str = Field(min_length=3, max_length=300)


@router.post("/observation", status_code=201)
def observation(b: ObsIn, ctx: Ctx = Depends(need("kitchen", "mess_admin")), db: Session = Depends(get_db)):
    s = _sched(db, b.schedule_id, ctx)
    notify(db, staff_ids(db, ctx.inst_id), f"Kitchen waste observation ({s.meal_type} {s.date})", b.note, "/waste")
    audit(db, ctx.user, "waste_observation", "meal_schedule", s.id, b.note); db.commit()
    return {"ok": True}
