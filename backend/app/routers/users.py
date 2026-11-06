from typing import Annotated, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import NGOPartner, StudentProfile, User
from ..security import Ctx, hash_password, need
from ..services.mailer import render_general_html, send_email
from ..util import audit, local_now, notify
from .auth import check_pw, validate_email_address

router = APIRouter(prefix="/users", tags=["users"])


def row(db: Session, u: User, partner_map: Optional[dict] = None):
    d = {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "is_approved": u.is_approved,
        "email_verified": u.email_verified,
        "institution_id": u.institution_id,
        "last_login": u.last_login,
    }
    if u.role == "ngo":
        n = partner_map.get(u.id) if partner_map is not None else db.get(NGOPartner, u.id)
        d["org_name"] = n.org_name if n else None
        d["verified"] = bool(n and n.verified)
        d["document_url"] = n.document_url if n else None
        d["approval_note"] = n.approval_note if n else None
    return d


@router.get("")
def list_users(
    role: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: Ctx = Depends(need("mess_admin")),
    db: Session = Depends(get_db),
):
    q = db.query(User).filter((User.institution_id == ctx.inst_id) | (User.role == "ngo"))
    if role:
        q = q.filter(User.role == role)

    users = q.order_by(User.role, User.name).offset(offset).limit(limit).all()

    # Performance: Avoid N+1 by batch loading NGO partners in a single query
    ngo_user_ids = [u.id for u in users if u.role == "ngo"]
    partner_map = {}
    if ngo_user_ids:
        partners = db.query(NGOPartner).filter(NGOPartner.user_id.in_(ngo_user_ids)).all()
        partner_map = {p.user_id: p for p in partners}

    return [row(db, u, partner_map) for u in users]


class CreateIn(BaseModel):
    name: Annotated[str, StringConstraints(min_length=2, max_length=120, strip_whitespace=True)]
    email: str
    password: str
    role: Literal["kitchen", "student", "mess_admin"] = "kitchen"


@router.post("", status_code=201)
def create_user(b: CreateIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    allowed = ("kitchen", "student", "mess_admin") if ctx.user.role == "super_admin" else ("kitchen", "student")
    if b.role not in allowed:
        raise HTTPException(403, f"You can only create: {', '.join(allowed)}")
    check_pw(b.password)
    norm_email = validate_email_address(b.email)

    if db.query(User).filter(User.email == norm_email).first():
        raise HTTPException(409, "Email already registered")

    u = User(
        email=norm_email,
        name=b.name,
        password_hash=hash_password(b.password),
        role=b.role,
        institution_id=ctx.inst_id,
        email_verified=True,  # Administrator-created accounts are pre-verified
        email_verified_at=local_now(),
        is_approved=True,
    )
    db.add(u)
    db.flush()
    if b.role == "student":
        db.add(StudentProfile(user_id=u.id))
    audit(db, ctx.user, "create_user", "user", u.id, b.role)
    db.commit()
    return row(db, u)


class PatchIn(BaseModel):
    is_active: Optional[bool] = None
    name: Optional[Annotated[str, StringConstraints(min_length=2, max_length=120, strip_whitespace=True)]] = None


@router.patch("/{uid}")
def patch_user(uid: int, b: PatchIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or (u.role != "ngo" and u.institution_id != ctx.inst_id):
        raise HTTPException(404, "User not found")
    if u.role == "super_admin" or u.id == ctx.user.id:
        raise HTTPException(400, "This account cannot be modified here")

    if b.is_active is not None:
        u.is_active = b.is_active
        if not b.is_active:
            u.token_version = (u.token_version or 1) + 1  # Invalidate tokens on deactivate

    if b.name:
        u.name = b.name

    audit(db, ctx.user, "patch_user", "user", u.id, str(b.model_dump(exclude_none=True)))
    db.commit()
    return row(db, u)


class ApproveIn(BaseModel):
    approve: bool = True
    note: Optional[Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]] = None


@router.post("/{uid}/approve")
def approve_partner(
    uid: int,
    b: ApproveIn,
    background_tasks: BackgroundTasks,
    ctx: Ctx = Depends(need("mess_admin")),
    db: Session = Depends(get_db),
):
    u = db.get(User, uid)
    n = db.get(NGOPartner, uid)
    if not u or u.role != "ngo" or not n:
        raise HTTPException(404, "Partner not found")

    if b.approve and not u.email_verified:
        raise HTTPException(400, "Cannot approve partner until their email address has been verified.")

    u.is_approved = b.approve
    n.verified = b.approve
    n.verified_by = ctx.user.id
    n.verified_at = local_now()
    if b.note:
        n.approval_note = b.note

    notify(
        db,
        [u.id],
        "Partner account " + ("approved" if b.approve else "not approved"),
        b.note or "",
        "/",
    )
    audit(db, ctx.user, "approve_partner" if b.approve else "reject_partner", "user", u.id, b.note)
    db.commit()

    # Notify NGO by email
    subj = f"Your Shakambari AI partner account has been {'approved' if b.approve else 'declined'}"
    msg = (
        f"Hello {u.name},\n\nYour organisation ({n.org_name}) has been {'approved as a verified surplus redistribution partner.' if b.approve else 'declined for surplus food redistribution.'}"
    )
    if b.note:
        msg += f"\n\nNote from mess administration:\n{b.note}"
    html = render_general_html(subj, msg, action_url="/login" if b.approve else None, action_text="Log In to Shakambari AI" if b.approve else None)
    background_tasks.add_task(send_email, u.email, subj, html, msg)

    return row(db, u)
