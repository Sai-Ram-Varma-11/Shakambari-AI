import logging, re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Institution, NGOPartner, StudentProfile, User
from ..security import (Ctx, current_user, hash_password, make_token, rate_limit, read_token, verify_password)
from ..util import audit, local_now, notify, staff_ids

log = logging.getLogger("platesense")
router = APIRouter(prefix="/auth", tags=["auth"])
Email = Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)]


def check_pw(p: str):
    if len(p) < 8 or len(p) > 128 or not re.search(r"[A-Za-z]", p) or not re.search(r"\d", p):
        raise HTTPException(422, "Password must be 8-128 characters and include a letter and a number")


def user_out(db, u: User):
    out = {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "institution_id": u.institution_id,
           "phone": u.phone, "is_approved": u.is_approved}
    if u.institution_id:
        i = db.get(Institution, u.institution_id)
        out["institution"] = {"id": i.id, "name": i.name, "data_mode": i.data_mode}
    if u.role == "student":
        p = db.get(StudentProfile, u.id)
        out["profile"] = {"diet": p.diet, "hostel": p.hostel, "dietary_notes": p.dietary_notes} if p else {}
    if u.role == "ngo":
        n = db.get(NGOPartner, u.id)
        out["partner"] = {"org_name": n.org_name, "verified": n.verified, "address": n.address} if n else {}
    return out


class RegisterIn(BaseModel):
    name: Annotated[str, StringConstraints(min_length=2, max_length=120, strip_whitespace=True)]
    email: Email
    password: str
    role: str = "student"
    institution_id: Optional[int] = None
    phone: Optional[str] = None
    diet: Optional[str] = "veg"
    hostel: Optional[str] = None
    org_name: Optional[str] = None
    registration_no: Optional[str] = None
    address: Optional[str] = None


@router.get("/institutions")
def institutions(db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name} for i in db.query(Institution).order_by(Institution.name)]


@router.post("/register", status_code=201)
def register(b: RegisterIn, request: Request, db: Session = Depends(get_db)):
    rate_limit(f"reg:{request.client.host if request.client else '-'}", 10, 300)
    if b.role not in ("student", "ngo"):
        raise HTTPException(403, "Only student and NGO partner accounts can self-register")
    check_pw(b.password)
    email = b.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    if b.role == "student":
        inst = db.get(Institution, b.institution_id) if b.institution_id else None
        if not inst:
            raise HTTPException(422, "Select a valid institution")
        if b.diet not in ("veg", "egg", "non_veg", "vegan"):
            raise HTTPException(422, "Invalid diet")
        u = User(email=email, name=b.name, password_hash=hash_password(b.password), role="student",
                 institution_id=inst.id, phone=b.phone, is_approved=True)
        db.add(u); db.flush()
        db.add(StudentProfile(user_id=u.id, diet=b.diet, hostel=b.hostel))
    else:
        if not b.org_name:
            raise HTTPException(422, "Organisation name is required")
        u = User(email=email, name=b.name, password_hash=hash_password(b.password), role="ngo", phone=b.phone,
                 is_approved=False)
        db.add(u); db.flush()
        db.add(NGOPartner(user_id=u.id, org_name=b.org_name, registration_no=b.registration_no, address=b.address))
        admins = [x for (x,) in db.query(User.id).filter(User.role.in_(("mess_admin", "super_admin")), User.is_active == True)]  # noqa
        notify(db, admins, "New partner awaiting approval", f"{b.org_name} registered as a redistribution partner.", "/users")
    audit(db, u, "register", "user", u.id)
    db.commit()
    return {"id": u.id, "message": "Registered. Partner accounts must be approved before first login." if b.role == "ngo" else "Registered."}


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(b: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = b.email.strip().lower()
    rate_limit(f"login:{request.client.host if request.client else '-'}:{email}", 8, 60)
    u = db.query(User).filter(User.email == email).first()
    if not u or not verify_password(b.password, u.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not u.is_active:
        raise HTTPException(403, "This account has been deactivated")
    if not u.is_approved:
        raise HTTPException(403, "Your partner account is awaiting approval")
    u.last_login = local_now()
    audit(db, u, "login", "user", u.id)
    db.commit()
    return {"access_token": make_token(u.id), "token_type": "bearer", "user": user_out(db, u)}


@router.get("/me")
def me(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, u)


class ProfileIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    diet: Optional[str] = None
    hostel: Optional[str] = None
    dietary_notes: Optional[str] = None


@router.patch("/me")
def update_me(b: ProfileIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.name:
        u.name = b.name.strip()[:120]
    if b.phone is not None:
        u.phone = b.phone[:30]
    if u.role == "student":
        p = db.get(StudentProfile, u.id) or StudentProfile(user_id=u.id)
        db.add(p)
        if b.diet:
            if b.diet not in ("veg", "egg", "non_veg", "vegan"):
                raise HTTPException(422, "Invalid diet")
            p.diet = b.diet
        if b.hostel is not None:
            p.hostel = b.hostel[:80]
        if b.dietary_notes is not None:
            p.dietary_notes = b.dietary_notes[:300]
    db.commit()
    return user_out(db, u)


class ChangePw(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(b: ChangePw, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(b.current_password, u.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    check_pw(b.new_password)
    u.password_hash = hash_password(b.new_password)
    audit(db, u, "change_password", "user", u.id)
    db.commit()
    return {"ok": True}


class ForgotIn(BaseModel):
    email: str


@router.post("/forgot-password")
def forgot(b: ForgotIn, request: Request, db: Session = Depends(get_db)):
    rate_limit(f"forgot:{request.client.host if request.client else '-'}", 5, 300)
    u = db.query(User).filter(User.email == b.email.strip().lower()).first()
    resp = {"message": "If that email is registered, a reset link has been issued."}
    if u:
        token = make_token(u.id, "reset", 30, pw=u.password_hash[-12:])
        # No email provider is configured: the token is logged server-side for the operator (dev) and only
        # returned in the response when DEBUG_RETURN_RESET_TOKEN=true. Never enable that in production.
        log.warning("Password reset token for %s: %s", u.email, token)
        if settings.debug_return_reset_token:
            resp["dev_reset_token"] = token
    return resp


class ResetIn(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
def reset(b: ResetIn, db: Session = Depends(get_db)):
    try:
        p = read_token(b.token)
        assert p.get("purpose") == "reset"
    except Exception:
        raise HTTPException(400, "Reset link is invalid or expired")
    u = db.get(User, int(p["sub"]))
    if not u or u.password_hash[-12:] != p.get("pw"):
        raise HTTPException(400, "Reset link is invalid or already used")
    check_pw(b.new_password)
    u.password_hash = hash_password(b.new_password)
    audit(db, u, "reset_password", "user", u.id)
    db.commit()
    return {"ok": True}
