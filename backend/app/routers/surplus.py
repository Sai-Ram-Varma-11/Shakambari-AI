import secrets
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..food_policy import food_is_allowed, ingredients_list, is_eligible_menu_item, require_vegetarian_food
from ..models import (
    CollectionRecord,
    Institution,
    MealSchedule,
    MenuItem,
    NGOPartner,
    RedistributionRequest,
    SurplusListing,
    User,
    WasteRecord,
)
from ..security import (
    Ctx,
    decrypt_handover_code,
    encrypt_handover_code,
    get_ctx,
    hash_handover_code,
    need,
)
from ..services.mailer import render_general_html, send_email
from ..services.surplus_rules import evaluate
from ..util import audit, local_now, merged_settings, notify, staff_ids

router = APIRouter(prefix="/surplus", tags=["redistribution"])
CATEGORIES = ("cooked", "packaged", "fruit", "bakery", "raw", "other")
STORAGE = ("hot_held", "refrigerated", "room_temp", "frozen")


def lout(db: Session, l: SurplusListing, with_requests=False, req_counts: Optional[dict] = None):
    d = {
        c: getattr(l, c)
        for c in (
            "id",
            "food_name",
            "diet",
            "ingredients",
            "category",
            "quantity_kg",
            "portions",
            "prepared_at",
            "storage_condition",
            "storage_temp_c",
            "use_by",
            "status",
            "auto_check",
            "review_notes",
            "verified_at",
            "created_at",
            "schedule_id",
            "menu_item_id",
        )
    }
    institution = db.get(Institution, l.institution_id)
    d["institution_name"] = institution.name if institution else "Participating mess"
    if with_requests:
        if req_counts is not None:
            d["requests"] = req_counts.get(l.id, 0)
        else:
            d["requests"] = db.query(RedistributionRequest).filter_by(listing_id=l.id).count()
    return d


def refresh(db: Session, l: SurplusListing):
    """An eligible listing that no longer passes the time-based rules is expired automatically."""
    if l.status == "eligible":
        if not listing_food_is_valid(db, l):
            l.status = "ineligible"
            db.commit()
            return
        inst = db.get(Institution, l.institution_id)
        if not all(
            c["passed"]
            for c in evaluate(
                merged_settings(inst),
                l.category,
                l.prepared_at,
                l.storage_condition,
                l.storage_temp_c,
                l.use_by,
                local_now(),
            )
        ):
            l.status = "expired"
            db.commit()


def listing_food_is_valid(db: Session, listing: SurplusListing):
    if listing.diet not in ("veg", "vegan") or not food_is_allowed(listing.food_name, listing.ingredients):
        return False
    if listing.menu_item_id:
        item = db.get(MenuItem, listing.menu_item_id)
        return bool(
            is_eligible_menu_item(item)
            and listing.food_name.strip().casefold() == item.name.strip().casefold()
            and listing.diet == item.diet
            and ingredients_list(listing.ingredients) == ingredients_list(item.ingredients)
        )
    return True


def partner_ok(db: Session, user: User):
    n = db.get(NGOPartner, user.id)
    if not n or not n.verified or not user.is_approved:
        raise HTTPException(403, "Your organisation has not been verified yet")
    return n


class ListIn(BaseModel):
    schedule_id: Optional[int] = None
    menu_item_id: Optional[int] = None
    food_name: Annotated[str, StringConstraints(min_length=2, max_length=150, strip_whitespace=True)]
    diet: Literal["veg", "vegan"]
    ingredients: List[Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]] = Field(min_length=1, max_length=50)
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
    require_vegetarian_food(b.food_name, b.ingredients)
    if b.schedule_id:
        sc = db.get(MealSchedule, b.schedule_id)
        if not sc or sc.institution_id != ctx.inst_id:
            raise HTTPException(404, "Schedule not found")
    if b.menu_item_id:
        item = db.get(MenuItem, b.menu_item_id)
        if not item or item.institution_id != ctx.inst_id:
            raise HTTPException(404, "Dish not found")
        if not is_eligible_menu_item(item):
            raise HTTPException(422, "Only active vegetarian dishes can be redistributed")
        if b.food_name.strip().casefold() != item.name.strip().casefold() or b.diet != item.diet:
            raise HTTPException(422, "Surplus classification must match the selected menu item")
        if ingredients_list(b.ingredients) != ingredients_list(item.ingredients):
            raise HTTPException(422, "Surplus ingredients must match the selected menu item")
        if b.schedule_id and not db.query(WasteRecord).filter_by(schedule_id=b.schedule_id, menu_item_id=item.id).first():
            raise HTTPException(422, "The selected dish was not recorded for this meal")

    cfg = merged_settings(db.get(Institution, ctx.inst_id))
    checks = evaluate(cfg, b.category, b.prepared_at, b.storage_condition, b.storage_temp_c, b.use_by, local_now())
    ok = all(c["passed"] for c in checks)
    l = SurplusListing(
        institution_id=ctx.inst_id,
        **b.model_dump(),
        status="pending_review" if ok else "ineligible",
        auto_check=checks,
        created_by=ctx.user.id,
        review_notes=None if ok else "Failed automatic screening - cannot be listed as eligible.",
    )
    db.add(l)
    db.flush()
    notify(
        db,
        staff_ids(db, ctx.inst_id),
        "Surplus listing needs food-safety review" if ok else "Surplus listing failed screening",
        f"{b.food_name} - {b.quantity_kg} kg",
        "/surplus",
    )
    audit(db, ctx.user, "create_surplus", "surplus_listing", l.id, f"{b.food_name} ok={ok}")
    db.commit()
    return lout(db, l)


@router.get("/suggestions")
def suggestions(ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    """Module 2 -> 3: edible leftovers recorded by the kitchen that have not been listed yet."""
    since = local_now().date() - timedelta(days=1)
    listed = {(i, j) for i, j in db.query(SurplusListing.schedule_id, SurplusListing.menu_item_id).filter_by(institution_id=ctx.inst_id)}
    rows = (
        db.query(WasteRecord, MealSchedule, MenuItem)
        .join(MealSchedule, MealSchedule.id == WasteRecord.schedule_id)
        .join(MenuItem, MenuItem.id == WasteRecord.menu_item_id)
        .filter(
            MealSchedule.institution_id == ctx.inst_id,
            MealSchedule.date >= since,
            WasteRecord.edible_qty > 0,
            WasteRecord.source == "manual",
            MenuItem.is_active.is_(True),
            MenuItem.diet.in_(("veg", "vegan")),
        )
        .all()
    )
    return [
        {
            "schedule_id": s.id,
            "menu_item_id": m.id,
            "food_name": m.name,
            "edible_kg": w.edible_qty,
            "date": s.date.isoformat(),
            "meal_type": s.meal_type,
            "category": m.category,
            "diet": m.diet,
            "ingredients": m.ingredients or [],
        }
        for w, s, m in rows
        if (s.id, m.id) not in listed and is_eligible_menu_item(m)
    ]


@router.get("")
def list_surplus(
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: Ctx = Depends(get_ctx),
    db: Session = Depends(get_db),
):
    q = db.query(SurplusListing).filter(SurplusListing.diet.in_(("veg", "vegan")))
    if ctx.user.role != "ngo":
        q = q.filter(SurplusListing.institution_id == ctx.inst_id)
    else:
        q = q.filter(SurplusListing.status == "eligible")

    if status:
        q = q.filter(SurplusListing.status == status)

    rows = q.order_by(SurplusListing.id.desc()).offset(offset).limit(limit).all()
    for l in rows:
        refresh(db, l)

    # Batch load request counts
    lids = [l.id for l in rows]
    counts_map = {}
    if lids:
        c_rows = (
            db.query(RedistributionRequest.listing_id, func.count())
            .filter(RedistributionRequest.listing_id.in_(lids))
            .group_by(RedistributionRequest.listing_id)
            .all()
        )
        counts_map = dict(c_rows)

    return [lout(db, l, with_requests=True, req_counts=counts_map) for l in rows if listing_food_is_valid(db, l)]


@router.get("/{lid}")
def get_one(lid: int, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    l = db.get(SurplusListing, lid)
    if not l or (ctx.user.role != "ngo" and l.institution_id != ctx.inst_id):
        raise HTTPException(404, "Listing not found")
    if not listing_food_is_valid(db, l):
        raise HTTPException(404, "Listing is not verified vegetarian surplus")
    refresh(db, l)
    return lout(db, l, with_requests=True)


class ReviewIn(BaseModel):
    decision: Literal["eligible", "ineligible"]
    notes: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None


@router.post("/{lid}/review")
def review(lid: int, b: ReviewIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    l = db.get(SurplusListing, lid)
    if not l or l.institution_id != ctx.inst_id:
        raise HTTPException(404, "Listing not found")
    if not listing_food_is_valid(db, l):
        raise HTTPException(409, "Unverified food cannot be reviewed or marked eligible")
    if l.status != "pending_review":
        raise HTTPException(409, f"Listing is already {l.status}")
    if b.decision == "eligible" and not all(c["passed"] for c in (l.auto_check or [])):
        raise HTTPException(422, "Cannot mark eligible: listing failed automatic food-safety checks")
    l.status = b.decision
    l.review_notes = b.notes
    l.verified_by = ctx.user.id
    l.verified_at = local_now()
    if b.decision == "eligible":
        ngos = [x for (x,) in db.query(User.id).filter(User.role == "ngo", User.is_active.is_(True), User.is_approved.is_(True))]
        notify(db, ngos, "New surplus available", f"{l.food_name} ({l.quantity_kg} kg) listed for collection.", "/partner")
    audit(db, ctx.user, f"surplus_{b.decision}", "surplus_listing", l.id)
    db.commit()
    return lout(db, l)


@router.post("/{lid}/withdraw")
def withdraw(lid: int, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    l = db.get(SurplusListing, lid)
    if not l or l.institution_id != ctx.inst_id:
        raise HTTPException(404, "Listing not found")
    l.status = "withdrawn"
    audit(db, ctx.user, "surplus_withdraw", "surplus_listing", lid)
    db.commit()
    return lout(db, l)


class ReqIn(BaseModel):
    pickup_time: Optional[datetime] = None
    message: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None


@router.post("/{lid}/request", status_code=201)
def request_listing(lid: int, b: ReqIn = ReqIn(), ctx: Ctx = Depends(need("ngo")), db: Session = Depends(get_db)):
    partner_ok(db, ctx.user)
    l = db.get(SurplusListing, lid)
    if not l or not listing_food_is_valid(db, l):
        raise HTTPException(404, "Listing not found")
    refresh(db, l)
    if l.status != "eligible":
        raise HTTPException(409, "This listing is no longer available")
    if db.query(RedistributionRequest).filter_by(listing_id=lid, partner_id=ctx.user.id, status="pending").first():
        raise HTTPException(409, "You already have a pending request for this listing")

    r = RedistributionRequest(
        listing_id=lid,
        partner_id=ctx.user.id,
        pickup_time=b.pickup_time,
        message=b.message,
    )
    db.add(r)
    db.flush()
    notify(
        db,
        staff_ids(db, l.institution_id),
        "New surplus collection request",
        f"{ctx.user.name} requested {l.food_name} ({l.quantity_kg} kg)",
        "/surplus",
    )
    audit(db, ctx.user, "request_collection", "surplus_listing", lid)
    db.commit()
    return rout(db, r, user=ctx.user)


def rout(db: Session, r: RedistributionRequest, user: Optional[User] = None):
    l = db.get(SurplusListing, r.listing_id)
    n = db.get(NGOPartner, r.partner_id)
    institution = db.get(Institution, l.institution_id) if l else None
    c = db.query(CollectionRecord).filter_by(request_id=r.id).first()
    d = {
        "id": r.id,
        "listing_id": l.id,
        "food_name": l.food_name,
        "diet": l.diet,
        "quantity_kg": l.quantity_kg,
        "status": r.status,
        "pickup_time": r.pickup_time,
        "message": r.message,
        "org_name": n.org_name if n else None,
        "institution_name": institution.name if institution else "Participating mess",
        "created_at": r.created_at,
        "listing_status": l.status,
        "collected_kg": c.collected_kg if c else None,
        "portions": c.portions if c else None,
    }
    # Only reveal pickup code to the NGO partner who owns the approved request
    if user and user.role == "ngo" and r.status == "approved" and r.handover_code_enc:
        d["pickup_code"] = decrypt_handover_code(r.handover_code_enc)
    return d


@router.get("/requests/all")
def requests(
    status: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: Ctx = Depends(get_ctx),
    db: Session = Depends(get_db),
):
    q = (
        db.query(RedistributionRequest)
        .join(SurplusListing, SurplusListing.id == RedistributionRequest.listing_id)
        .filter(SurplusListing.diet.in_(("veg", "vegan")))
    )
    if ctx.user.role == "ngo":
        q = q.filter(RedistributionRequest.partner_id == ctx.user.id)
    elif ctx.user.role in ("mess_admin", "kitchen", "super_admin"):
        q = q.filter(SurplusListing.institution_id == ctx.inst_id)
    else:
        raise HTTPException(403, "You do not have permission for this action")

    if status:
        q = q.filter(RedistributionRequest.status == status)

    rows = q.order_by(RedistributionRequest.id.desc()).offset(offset).limit(limit).all()
    return [rout(db, r, user=ctx.user) for r in rows if listing_food_is_valid(db, db.get(SurplusListing, r.listing_id))]


class DecideIn(BaseModel):
    approve: bool
    pickup_time: Optional[datetime] = None


@router.post("/requests/{rid}/decision")
def decide(
    rid: int,
    b: DecideIn,
    background_tasks: BackgroundTasks,
    ctx: Ctx = Depends(need("mess_admin")),
    db: Session = Depends(get_db),
):
    r = db.get(RedistributionRequest, rid)
    l = db.get(SurplusListing, r.listing_id) if r else None
    if not r or not l or l.institution_id != ctx.inst_id:
        raise HTTPException(404, "Request not found")
    if r.status != "pending":
        raise HTTPException(409, f"Request is already {r.status}")

    partner_user = db.get(User, r.partner_id)

    if b.approve:
        refresh(db, l)
        if l.status != "eligible" or not listing_food_is_valid(db, l):
            raise HTTPException(409, "Listing is no longer eligible")

        # Generate 6-digit pickup handover code
        pickup_code = f"{secrets.randbelow(900000) + 100000:06d}"
        r.handover_code_hash = hash_handover_code(pickup_code)
        r.handover_code_enc = encrypt_handover_code(pickup_code)

        r.status = "approved"
        r.pickup_time = b.pickup_time
        r.decided_by = ctx.user.id
        l.status = "approved"

        # Reject competing pending requests
        for o in db.query(RedistributionRequest).filter(
            RedistributionRequest.listing_id == l.id,
            RedistributionRequest.id != r.id,
            RedistributionRequest.status == "pending",
        ):
            o.status = "rejected"
            notify(db, [o.partner_id], "Collection request not selected", l.food_name, "/partner")

        # Email the handover code to NGO
        if partner_user:
            subj = f"Collection Approved: {l.food_name} — Your Pickup Code"
            msg = (
                f"Hello {partner_user.name},\n\nYour request to collect {l.food_name} ({l.quantity_kg} kg) has been approved.\n\n"
                f"YOUR 6-DIGIT PICKUP CODE: {pickup_code}\n\n"
                "Please present this code to the kitchen staff at pickup to confirm handover."
            )
            html = render_otp_html(
                pickup_code,
                "Collection Request Approved",
                f"Present this 6-digit handover code to kitchen staff when collecting {l.food_name} ({l.quantity_kg} kg).",
                expiry_minutes=240,
            )
            background_tasks.add_task(send_email, partner_user.email, subj, html, msg)
    else:
        r.status = "rejected"
        r.decided_by = ctx.user.id
        if partner_user:
            subj = f"Collection Request Update: {l.food_name}"
            msg = f"Hello {partner_user.name},\n\nYour collection request for {l.food_name} could not be approved at this time."
            html = render_general_html(subj, msg)
            background_tasks.add_task(send_email, partner_user.email, subj, html, msg)

    r.updated_at = local_now()
    notify(
        db,
        [r.partner_id],
        f"Collection request {r.status}",
        f"{l.food_name}" + (f" - pickup {b.pickup_time:%d %b %H:%M}" if b.pickup_time and b.approve else ""),
        "/partner",
    )
    audit(db, ctx.user, f"request_{r.status}", "redistribution_request", r.id)
    db.commit()
    return rout(db, r, user=ctx.user)


class HandoverIn(BaseModel):
    code: Annotated[str, StringConstraints(min_length=6, max_length=6, strip_whitespace=True)]
    collected_kg: float = Field(gt=0, le=10000)
    portions: Optional[int] = Field(default=0, ge=0)


@router.post("/requests/{rid}/handover")
def confirm_handover(
    rid: int,
    b: HandoverIn,
    ctx: Ctx = Depends(need("mess_admin", "kitchen")),
    db: Session = Depends(get_db),
):
    """Kitchen staff confirms pickup handover by entering the 6-digit code presented by NGO."""
    r = db.get(RedistributionRequest, rid)
    if not r:
        raise HTTPException(404, "Request not found")
    l = db.get(SurplusListing, r.listing_id)
    if not l or l.institution_id != ctx.inst_id:
        raise HTTPException(404, "Listing not found or access denied")
    if r.status != "approved":
        raise HTTPException(409, f"Cannot confirm handover for request in '{r.status}' state. Only approved requests can be collected.")

    if not r.handover_code_hash or not hmac.compare_digest(hash_handover_code(b.code), r.handover_code_hash):
        raise HTTPException(400, "Incorrect pickup handover code")

    if b.collected_kg > l.quantity_kg * 1.05:
        raise HTTPException(422, f"Collected quantity cannot exceed listed {l.quantity_kg} kg")

    c = CollectionRecord(request_id=r.id, collected_kg=b.collected_kg, portions=b.portions or 0)
    db.add(c)
    r.status = "picked_up"
    r.updated_at = local_now()
    l.status = "collected"

    notify(
        db,
        [r.partner_id],
        "Pickup Handover Confirmed",
        f"Kitchen staff verified code and confirmed handover of {l.food_name} ({b.collected_kg} kg).",
        "/partner",
    )
    notify(
        db,
        staff_ids(db, l.institution_id),
        "Surplus Handover Completed",
        f"{l.food_name} ({b.collected_kg} kg) successfully collected.",
        "/surplus",
    )
    audit(db, ctx.user, "confirm_handover", "redistribution_request", r.id, f"Handover code verified. Collected {b.collected_kg} kg")
    db.commit()
    return rout(db, r, user=ctx.user)


class StatusIn(BaseModel):
    status: Literal["delivered", "cancelled"]
    delivered_to: Optional[Annotated[str, StringConstraints(max_length=200, strip_whitespace=True)]] = None


@router.post("/requests/{rid}/status")
def update_status(rid: int, b: StatusIn, ctx: Ctx = Depends(need("ngo")), db: Session = Depends(get_db)):
    r = db.get(RedistributionRequest, rid)
    if not r or r.partner_id != ctx.user.id:
        raise HTTPException(404, "Request not found")
    l = db.get(SurplusListing, r.listing_id)
    if not listing_food_is_valid(db, l):
        raise HTTPException(409, "This listing is not verified vegetarian surplus")

    flow = {"approved": ("cancelled",), "picked_up": ("delivered",)}
    if b.status not in flow.get(r.status, ()):
        raise HTTPException(409, f"Cannot move request from {r.status} to {b.status}. Handover requires kitchen confirmation.")

    if b.status == "delivered":
        c = db.query(CollectionRecord).filter_by(request_id=r.id).first()
        if c:
            c.delivered_to = b.delivered_to
    elif b.status == "cancelled":
        l.status = "eligible"

    r.status = b.status
    r.updated_at = local_now()
    notify(db, staff_ids(db, l.institution_id), f"Collection {b.status.replace('_', ' ')}", l.food_name, "/surplus")
    audit(db, ctx.user, f"collection_{b.status}", "redistribution_request", r.id)
    db.commit()
    return rout(db, r, user=ctx.user)


@router.get("/donations/history")
def donations(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: Ctx = Depends(get_ctx),
    db: Session = Depends(get_db),
):
    q = (
        db.query(CollectionRecord, RedistributionRequest, SurplusListing)
        .join(RedistributionRequest, RedistributionRequest.id == CollectionRecord.request_id)
        .join(SurplusListing, SurplusListing.id == RedistributionRequest.listing_id)
        .filter(RedistributionRequest.status.in_(("picked_up", "delivered")))
    )
    if ctx.user.role == "ngo":
        q = q.filter(RedistributionRequest.partner_id == ctx.user.id)
    elif ctx.user.role in ("mess_admin", "super_admin"):
        q = q.filter(SurplusListing.institution_id == ctx.inst_id)
    else:
        raise HTTPException(403, "You do not have permission for this action")

    rows = q.order_by(CollectionRecord.id.desc()).offset(offset).limit(limit).all()

    # Performance: Batch load NGO partner names
    partner_ids = [r.partner_id for _, r, _ in rows]
    partner_map = {}
    if partner_ids:
        partners = db.query(NGOPartner).filter(NGOPartner.user_id.in_(partner_ids)).all()
        partner_map = {p.user_id: p.org_name for p in partners}

    return [
        {
            "collected_at": c.collected_at,
            "food_name": l.food_name,
            "collected_kg": c.collected_kg,
            "portions": c.portions,
            "delivered_to": c.delivered_to,
            "status": r.status,
            "org_name": partner_map.get(r.partner_id),
        }
        for c, r, l in rows
    ]
