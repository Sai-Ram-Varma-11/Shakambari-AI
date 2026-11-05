from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import NGOPartner, StudentProfile, User
from ..security import Ctx, hash_password, need
from ..util import audit, local_now, notify
from .auth import Email, check_pw

router = APIRouter(prefix="/users", tags=["users"])


def row(db, u):
    d = {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "is_active": u.is_active,
         "is_approved": u.is_approved, "institution_id": u.institution_id, "last_login": u.last_login}
    if u.role == "ngo":
        n = db.get(NGOPartner, u.id)
        d["org_name"] = n.org_name if n else None
        d["verified"] = bool(n and n.verified)
    return d


@router.get("")
def list_users(role: Optional[str] = None, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    q = db.query(User).filter((User.institution_id == ctx.inst_id) | (User.role == "ngo"))
    if role:
        q = q.filter(User.role == role)
    return [row(db, u) for u in q.order_by(User.role, User.name).limit(500)]


class CreateIn(BaseModel):
    name: str
    email: Email
    password: str
    role: str = "kitchen"


@router.post("", status_code=201)
def create_user(b: CreateIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    allowed = ("kitchen", "student", "mess_admin") if ctx.user.role == "super_admin" else ("kitchen", "student")
    if b.role not in allowed:
        raise HTTPException(403, f"You can only create: {', '.join(allowed)}")
    check_pw(b.password)
    if db.query(User).filter(User.email == b.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    u = User(email=b.email.lower(), name=b.name.strip(), password_hash=hash_password(b.password), role=b.role,
             institution_id=ctx.inst_id)
    db.add(u); db.flush()
    if b.role == "student":
        db.add(StudentProfile(user_id=u.id))
    audit(db, ctx.user, "create_user", "user", u.id, b.role)
    db.commit()
    return row(db, u)


class PatchIn(BaseModel):
    is_active: Optional[bool] = None
    name: Optional[str] = None


@router.patch("/{uid}")
def patch_user(uid: int, b: PatchIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or (u.role != "ngo" and u.institution_id != ctx.inst_id):
        raise HTTPException(404, "User not found")
    if u.role == "super_admin" or u.id == ctx.user.id:
        raise HTTPException(400, "This account cannot be modified here")
    if b.is_active is not None:
        u.is_active = b.is_active
    if b.name:
        u.name = b.name
    audit(db, ctx.user, "patch_user", "user", u.id, str(b.model_dump(exclude_none=True)))
    db.commit()
    return row(db, u)


class ApproveIn(BaseModel):
    approve: bool = True


@router.post("/{uid}/approve")
def approve_partner(uid: int, b: ApproveIn, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    u, n = db.get(User, uid), db.get(NGOPartner, uid)
    if not u or u.role != "ngo" or not n:
        raise HTTPException(404, "Partner not found")
    u.is_approved = b.approve
    n.verified, n.verified_by, n.verified_at = b.approve, ctx.user.id, local_now()
    notify(db, [u.id], "Partner account " + ("approved" if b.approve else "not approved"), "", "/")
    audit(db, ctx.user, "approve_partner" if b.approve else "reject_partner", "user", u.id)
    db.commit()
    return row(db, u)
