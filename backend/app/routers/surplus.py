from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (CollectionRecord, Institution, MealSchedule, MenuItem, NGOPartner, RedistributionRequest, SurplusListing, User, WasteRecord)
from ..security import Ctx, get_ctx, need
from ..services.surplus_rules import evaluate
from ..util import audit, local_now, merged_settings, notify, staff_ids

router = APIRouter(prefix="/surplus", tags=["redistribution"])
CATEGORIES = ("cooked", "packaged", "fruit", "bakery", "raw", "other")
STORAGE = ("hot_held", "refrigerated", "room_temp", "frozen")


def lout(db, l, with_requests=False):
    d = {c: getattr(l, c) for c in ("id", "food_name", "category", "quantity_kg", "portions", "prepared_at", "storage_condition", "storage_temp_c",
                                    "use_by", "status", "auto_check", "review_notes", "verified_at", "created_at", "schedule_id", "menu_item_id")}
    if with_requests:
        d["requests"] = db.query(RedistributionRequest).filter_by(listing_id=l.id).count()
    return d


def refresh(db, l):
    """An eligible listing that no longer passes the time-based rules is expired automatically."""
    if l.status == "eligible":
        inst = db.get(Institution, l.institution_id)
        if not all(c["passed"] for c in evaluate(merged_settings(inst), l.category, l.prepared_at, l.storage_condition, l.storage_temp_c, l.use_by, local_now())):
            l.status = "expired"; db.commit()


def partner_ok(db, user):
    n = db.get(NGOPartner, user.id)
    if not n or not n.verified or not user.is_approved:
        raise HTTPException(403, "Your organisation has not been verified yet")
    return n


class ListIn(BaseModel):
    schedule_id: Optional[int] = None
    menu_item_id: Optional[int] = None
    food_name: str = Field(min_length=2, max_length=150)
    category: str
    quantity_kg: float = Field(gt=0, le=10000)
    portions: int = Field(default=0, ge=0, le=100000)
    prepared_at: datetime
    storage_condition: str
    storage_temp_c: Optional[float] = Field(default=None, ge=-40, le=200)
    use_by: Optional[datetime] = None


@router.post("", status_code=201)
def create(b: ListIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    if b.category not in CATEGORIES or b.storage_condition not in STORAGE:
        raise HTTPException(422, "Invalid category or storage condition")
    if b.prepared_at > local_now() + timedelta(minutes=5):
        raise HTTPException(422, "Preparation time cannot be in the future")
    if b.schedule_id:
        sc = db.get(MealSchedule, b.schedule_id)
        if not sc or sc.institution_id != ctx.inst_id:
            raise HTTPException(404, "Schedule not found")
    cfg = merged_settings(db.get(Institution, ctx.inst_id))
    checks = evaluate(cfg, b.category, b.prepared_at, b.storage_condition, b.storage_temp_c, b.use_by, local_now())
    ok = all(c["passed"] for c in checks)
    l = SurplusListing(institution_id=ctx.inst_id, **b.model_dump(), status="pending_review" if ok else "ineligible", auto_check=checks, created_by=ctx.user.id,
                       review_notes=None if ok else "Failed automatic screening - cannot be listed as eligible.")
    db.add(l); db.flush()
    notify(db, staff_ids(db, ctx.inst_id), "Surplus listing needs food-safety review" if ok else "Surplus listing failed screening", f"{b.food_name} - {b.quantity_kg} kg", "/surplus")
    audit(db, ctx.user, "create_surplus", "surplus_listing", l.id, f"{b.food_name} ok={ok}"); db.commit()
    return lout(db, l)


@router.get("/suggestions")
def suggestions(ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    """Module 2 -> 3: edible leftovers recorded by the kitchen that have not been listed yet."""
    since = local_now().date() - timedelta(days=1)
    listed = {(i, j) for i, j in db.query(SurplusListing.schedule_id, SurplusListing.menu_item_id).filter_by(institution_id=ctx.inst_id)}
    rows = (db.query(WasteRecord, MealSchedule, MenuItem).join(MealSchedule, MealSchedule.id == WasteRecord.schedule_id)
            .join(MenuItem, MenuItem.id == WasteRecord.menu_item_id)
            .filter(MealSchedule.institution_id == ctx.inst_id, MealSchedule.date >= since, WasteRecord.edible_qty > 0, WasteRecord.source == "manual").all())
    return [{"schedule_id": s.id, "menu_item_id": m.id, "food_name": m.name, "edible_kg": w.edible_qty, "date": s.date.isoformat(), "meal_type": s.meal_type,
             "suggested_portions": int(w.edible_qty / m.portion_kg) if m.portion_kg else 0} for w, s, m in rows if (s.id, m.id) not in listed]


@router.get("")
def list_listings(status: Optional[str] = None, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    u = ctx.user
    if u.role == "ngo":
        partner_ok(db, u)
        q = db.query(SurplusListing).filter(SurplusListing.status == "eligible")
    elif u.role in ("mess_admin", "kitchen", "super_admin"):
        q = db.query(SurplusListing).filter(SurplusListing.institution_id == ctx.inst_id)
    else:
        raise HTTPException(403, "You do not have permission for this action")
    if status:
        q = q.filter(SurplusListing.status == status)
    rows = q.order_by(SurplusListing.id.desc()).limit(200).all()
    for l in rows:
        refresh(db, l)
    if u.role == "ngo":
        rows = [l for l in rows if l.status == "eligible"]
    return [lout(db, l, True) for l in rows]


class ReviewIn(BaseModel):
    decision: str  # approve | reject
    notes: Optional[str] = Field(default=None, max_length=300)
    checklist_confirmed: bool = False


@router.post("/{lid}/review")
def review(lid: int, b: ReviewIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    l = db.get(SurplusListing, lid)
    if not l or l.institution_id != ctx.inst_id:
        raise HTTPException(404, "Listing not found")
    if l.status not in ("pending_review", "eligible"):
        raise HTTPException(409, f"Listing is {l.status} and cannot be reviewed")
    if b.decision == "approve":
        if not b.checklist_confirmed:
            raise HTTPException(422, "A responsible person must confirm the food-safety checklist (visual inspection, temperature, packaging, transport)")
        cfg = merged_settings(db.get(Institution, ctx.inst_id))
        checks = evaluate(cfg, l.category, l.prepared_at, l.storage_condition, l.storage_temp_c, l.use_by, local_now())
        l.auto_check = checks
        if not all(c["passed"] for c in checks):
            l.status = "ineligible"; db.commit()
            raise HTTPException(409, "Listing no longer passes the eligibility rules and cannot be approved")
        l.status, l.verified_by, l.verified_at = "eligible", ctx.user.id, local_now()
        partners = [x for (x,) in db.query(NGOPartner.user_id).filter_by(verified=True)]
        notify(db, partners, "Surplus food available", f"{l.food_name}: {l.quantity_kg} kg", "/partner")
    elif b.decision == "reject":
        l.status = "ineligible"
    else:
        raise HTTPException(422, "decision must be approve or reject")
    l.review_notes = b.notes
    audit(db, ctx.user, f"surplus_{b.decision}", "surplus_listing", l.id); db.commit()
    return lout(db, l, True)


@router.post("/{lid}/withdraw")
def withdraw(lid: int, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    l = db.get(SurplusListing, lid)
    if not l or l.institution_id != ctx.inst_id:
        raise HTTPException(404, "Listing not found")
    if l.status in ("collected",):
        raise HTTPException(409, "Already collected")
    l.status = "withdrawn"
    db.query(RedistributionRequest).filter(RedistributionRequest.listing_id == lid, RedistributionRequest.status == "pending").update({"status": "rejected"})
    audit(db, ctx.user, "surplus_withdraw", "surplus_listing", lid); db.commit()
    return lout(db, l, True)


class ReqIn(BaseModel):
    message: Optional[str] = Field(default=None, max_length=300)


@router.post("/{lid}/request", status_code=201)
def request_collection(lid: int, b: ReqIn = ReqIn(), ctx: Ctx = Depends(need("ngo")), db: Session = Depends(get_db)):
    partner_ok(db, ctx.user)
    l = db.get(SurplusListing, lid)
    if not l:
        raise HTTPException(404, "Listing not found")
    refresh(db, l)
    if l.status != "eligible":
        raise HTTPException(409, "This listing is no longer available")
    if db.query(RedistributionRequest).filter_by(listing_id=lid, partner_id=ctx.user.id).filter(RedistributionRequest.status.in_(("pending", "approved"))).first():
        raise HTTPException(409, "You already requested this listing")
    r = RedistributionRequest(listing_id=lid, partner_id=ctx.user.id, message=b.message); db.add(r); db.flush()
    notify(db, staff_ids(db, l.institution_id), "Collection request received", f"{db.get(NGOPartner, ctx.user.id).org_name} requested {l.food_name}", "/surplus")
    audit(db, ctx.user, "request_collection", "surplus_listing", lid); db.commit()
    return {"id": r.id, "status": r.status}


def rout(db, r):
    l, n = db.get(SurplusListing, r.listing_id), db.get(NGOPartner, r.partner_id)
    c = db.query(CollectionRecord).filter_by(request_id=r.id).first()
    return {"id": r.id, "listing_id": l.id, "food_name": l.food_name, "quantity_kg": l.quantity_kg, "status": r.status, "pickup_time": r.pickup_time,
            "message": r.message, "org_name": n.org_name if n else None, "created_at": r.created_at, "listing_status": l.status,
            "collected_kg": c.collected_kg if c else None, "portions": c.portions if c else None}


@router.get("/requests/all")
def requests(status: Optional[str] = None, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    q = db.query(RedistributionRequest)
    if ctx.user.role == "ngo":
        q = q.filter(RedistributionRequest.partner_id == ctx.user.id)
    elif ctx.user.role in ("mess_admin", "kitchen", "super_admin"):
        q = q.join(SurplusListing, SurplusListing.id == RedistributionRequest.listing_id).filter(SurplusListing.institution_id == ctx.inst_id)
    else:
        raise HTTPException(403, "You do not have permission for this action")
    if status:
        q = q.filter(RedistributionRequest.status == status)
    return [rout(db, r) for r in q.order_by(RedistributionRequest.id.desc()).limit(200)]


class DecideIn(BaseModel):
    approve: bool
    pickup_time: Optional[datetime] = None


@router.post("/requests/{rid}/decision")
def decide(rid: int, b: DecideIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    r = db.get(RedistributionRequest, rid)
    l = db.get(SurplusListing, r.listing_id) if r else None
    if not r or l.institution_id != ctx.inst_id:
        raise HTTPException(404, "Request not found")
    if r.status != "pending":
        raise HTTPException(409, f"Request is already {r.status}")
    if b.approve:
        refresh(db, l)
        if l.status != "eligible":
            raise HTTPException(409, "Listing is no longer eligible")
        r.status, r.pickup_time, r.decided_by, l.status = "approved", b.pickup_time, ctx.user.id, "approved"
        for o in db.query(RedistributionRequest).filter(RedistributionRequest.listing_id == l.id, RedistributionRequest.id != r.id, RedistributionRequest.status == "pending"):
            o.status = "rejected"; notify(db, [o.partner_id], "Collection request not selected", l.food_name, "/partner")
    else:
        r.status, r.decided_by = "rejected", ctx.user.id
    r.updated_at = local_now()
    notify(db, [r.partner_id], f"Collection request {r.status}", f"{l.food_name}" + (f" - pickup {b.pickup_time:%d %b %H:%M}" if b.pickup_time and b.approve else ""), "/partner")
    audit(db, ctx.user, f"request_{r.status}", "redistribution_request", r.id); db.commit()
    return rout(db, r)


class StatusIn(BaseModel):
    status: str  # picked_up | delivered | cancelled
    collected_kg: Optional[float] = Field(default=None, gt=0, le=10000)
    portions: Optional[int] = Field(default=None, ge=0)
    delivered_to: Optional[str] = Field(default=None, max_length=200)


@router.post("/requests/{rid}/status")
def update_status(rid: int, b: StatusIn, ctx: Ctx = Depends(need("ngo")), db: Session = Depends(get_db)):
    r = db.get(RedistributionRequest, rid)
    if not r or r.partner_id != ctx.user.id:
        raise HTTPException(404, "Request not found")
    l = db.get(SurplusListing, r.listing_id)
    flow = {"approved": ("picked_up", "cancelled"), "picked_up": ("delivered",)}
    if b.status not in flow.get(r.status, ()):
        raise HTTPException(409, f"Cannot move a request from {r.status} to {b.status}")
    if b.status == "picked_up":
        if not b.collected_kg:
            raise HTTPException(422, "Enter the quantity actually collected (kg)")
        if b.collected_kg > l.quantity_kg * 1.02:
            raise HTTPException(422, f"Collected quantity cannot exceed the listed {l.quantity_kg} kg")
        db.add(CollectionRecord(request_id=r.id, collected_kg=b.collected_kg, portions=b.portions or 0))
        l.status = "collected"
    elif b.status == "delivered":
        c = db.query(CollectionRecord).filter_by(request_id=r.id).first()
        if c:
            c.delivered_to = b.delivered_to
    else:
        l.status = "eligible"
    r.status, r.updated_at = b.status, local_now()
    notify(db, staff_ids(db, l.institution_id), f"Collection {b.status.replace('_', ' ')}", l.food_name, "/surplus")
    audit(db, ctx.user, f"collection_{b.status}", "redistribution_request", r.id); db.commit()
    return rout(db, r)


@router.get("/donations/history")
def donations(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    q = (db.query(CollectionRecord, RedistributionRequest, SurplusListing).join(RedistributionRequest, RedistributionRequest.id == CollectionRecord.request_id)
         .join(SurplusListing, SurplusListing.id == RedistributionRequest.listing_id))
    if ctx.user.role == "ngo":
        q = q.filter(RedistributionRequest.partner_id == ctx.user.id)
    elif ctx.user.role in ("mess_admin", "super_admin"):
        q = q.filter(SurplusListing.institution_id == ctx.inst_id)
    else:
        raise HTTPException(403, "You do not have permission for this action")
    return [{"collected_at": c.collected_at, "food_name": l.food_name, "collected_kg": c.collected_kg, "portions": c.portions, "delivered_to": c.delivered_to,
             "status": r.status, "org_name": (db.get(NGOPartner, r.partner_id).org_name)} for c, r, l in q.order_by(CollectionRecord.id.desc()).limit(300)]
