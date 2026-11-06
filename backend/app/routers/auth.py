import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal, Optional

import jwt
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import EmailOTP, Institution, InstitutionRequest, NGOPartner, StudentProfile, User
from ..security import (
    Ctx,
    client_ip,
    current_user,
    hash_password,
    make_token,
    rate_limit,
    read_token,
    verify_password,
)
from ..services.mailer import render_general_html, render_otp_html, send_email
from ..util import audit, local_now, notify, staff_ids

log = logging.getLogger("shakambari.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

PhoneRegex = r"^\+?[0-9]{10,15}$"

# Load disposable domains
DISPOSABLE_DOMAINS = set()
_disp_file = Path(__file__).resolve().parent.parent / "disposable_domains.txt"
if _disp_file.exists():
    for line in _disp_file.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            DISPOSABLE_DOMAINS.add(line)


def mask_email(email: str) -> str:
    if "@" not in email:
        return email
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"


def validate_email_address(raw_email: str) -> str:
    cleaned = raw_email.strip().lower()
    is_prod = getattr(settings, "app_env", "development") == "production"
    try:
        try:
            valid = validate_email(cleaned, check_deliverability=is_prod, test_environment=not is_prod)
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            log.warning("DNS MX check unavailable (%s), falling back to syntax check for %s", e, cleaned)
            valid = validate_email(cleaned, check_deliverability=False, test_environment=not is_prod)
        normalized = valid.normalized.lower()
        domain = normalized.split("@")[-1].lower()
        if domain in DISPOSABLE_DOMAINS:
            raise HTTPException(422, "Disposable and temporary email domains are not allowed")
        return normalized
    except HTTPException:
        raise
    except EmailNotValidError as e:
        raise HTTPException(422, f"Invalid email format: {str(e)}")


def check_pw(p: str):
    if len(p) < 8 or len(p) > 128 or not re.search(r"[A-Za-z]", p) or not re.search(r"\d", p):
        raise HTTPException(422, "Password must be 8-128 characters and include a letter and a number")


def hash_otp(code: str) -> str:
    return hmac.new(settings.secret_key.encode(), code.strip().encode(), "sha256").hexdigest()


def user_out(db: Session, u: User):
    out = {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "institution_id": u.institution_id,
        "phone": u.phone,
        "is_approved": u.is_approved,
        "email_verified": u.email_verified,
    }
    if u.institution_id:
        i = db.get(Institution, u.institution_id)
        if i:
            out["institution"] = {"id": i.id, "name": i.name, "data_mode": i.data_mode}
    if u.role == "student":
        p = db.get(StudentProfile, u.id)
        out["profile"] = {"diet": p.diet, "hostel": p.hostel, "dietary_notes": p.dietary_notes} if p else {}
    if u.role == "ngo":
        n = db.get(NGOPartner, u.id)
        out["partner"] = {
            "org_name": n.org_name,
            "verified": n.verified,
            "address": n.address,
            "document_url": n.document_url,
            "approval_note": n.approval_note,
        } if n else {}
    return out


def generate_and_dispatch_otp(
    db: Session,
    email: str,
    purpose: str,
    ip: str,
    background_tasks: Optional[BackgroundTasks] = None,
    subject_override: Optional[str] = None,
) -> str:
    one_hour_ago = local_now() - timedelta(hours=1)
    sends_email = db.query(EmailOTP).filter(
        EmailOTP.email == email,
        EmailOTP.purpose == purpose,
        EmailOTP.created_at >= one_hour_ago,
    ).count()
    if sends_email >= 5:
        raise HTTPException(429, "Too many verification codes requested for this email. Please wait an hour.")

    sends_ip = db.query(EmailOTP).filter(
        EmailOTP.ip == ip,
        EmailOTP.created_at >= one_hour_ago,
    ).count()
    if sends_ip >= 20:
        raise HTTPException(429, "Too many requests from this network. Please wait an hour.")

    sixty_secs_ago = local_now() - timedelta(seconds=60)
    recent = db.query(EmailOTP).filter(
        EmailOTP.email == email,
        EmailOTP.purpose == purpose,
        EmailOTP.created_at >= sixty_secs_ago,
    ).first()
    if recent:
        raise HTTPException(429, "Please wait at least 60 seconds before requesting another code.")

    # Invalidate earlier unused codes for same email + purpose
    db.query(EmailOTP).filter(
        EmailOTP.email == email,
        EmailOTP.purpose == purpose,
        EmailOTP.consumed_at.is_(None),
    ).update({"consumed_at": local_now()}, synchronize_session=False)

    code = f"{secrets.randbelow(900000) + 100000:06d}"
    otp = EmailOTP(
        email=email,
        purpose=purpose,
        code_hash=hash_otp(code),
        expires_at=local_now() + timedelta(minutes=10),
        attempts=0,
        max_attempts=5,
        created_at=local_now(),
        ip=ip,
    )
    db.add(otp)
    db.commit()

    if settings.app_env == "development" and settings.dev_log_otp:
        log.info("[DEV_LOG_OTP] Generated %s OTP for %s: %s", purpose, email, code)

    title_map = {
        "signup": "Confirm your email address",
        "login": "Your login verification code",
        "reset": "Password reset verification code",
    }
    title = title_map.get(purpose, "Verification Code")
    subtitle = f"Use this code to complete your {purpose} on Shakambari AI."
    subject = subject_override or f"Your Shakambari AI verification code: {code}"
    html = render_otp_html(code, title, subtitle, expiry_minutes=10)
    text = f"Your Shakambari AI verification code is: {code}\n\nThis code expires in 10 minutes.\nIf you did not request this, please ignore this email."

    if background_tasks:
        background_tasks.add_task(send_email, email, subject, html, text)
    else:
        send_email(email, subject, html, text)

    return code


def check_and_consume_otp(db: Session, email: str, purpose: str, candidate_code: str):
    otp = db.query(EmailOTP).filter(
        EmailOTP.email == email,
        EmailOTP.purpose == purpose,
        EmailOTP.consumed_at.is_(None),
    ).order_by(EmailOTP.id.desc()).first()

    if not otp:
        raise HTTPException(400, "No active verification code found. Please request a new code.")

    if local_now() > otp.expires_at:
        otp.consumed_at = local_now()
        db.commit()
        raise HTTPException(400, "Verification code has expired. Please request a new one.")

    if otp.attempts >= otp.max_attempts:
        otp.consumed_at = local_now()
        db.commit()
        raise HTTPException(400, "Too many incorrect attempts. This code is invalidated. Please request a new code.")

    if hmac.compare_digest(hash_otp(candidate_code), otp.code_hash):
        otp.consumed_at = local_now()
        db.commit()
        return True
    else:
        otp.attempts += 1
        remaining = otp.max_attempts - otp.attempts
        db.commit()
        if remaining <= 0:
            otp.consumed_at = local_now()
            db.commit()
            raise HTTPException(400, "Incorrect code. Maximum attempts reached. Please request a new one.")
        raise HTTPException(400, f"Incorrect verification code. {remaining} attempt{'s' if remaining != 1 else ''} remaining.")


class RegisterIn(BaseModel):
    name: Annotated[str, StringConstraints(min_length=2, max_length=120, strip_whitespace=True)]
    email: str
    password: str
    role: Literal["student", "ngo"] = "student"
    institution_id: Optional[int] = None
    phone: Optional[Annotated[str, StringConstraints(pattern=PhoneRegex)]] = None
    diet: Optional[Literal["veg", "vegan"]] = "veg"
    hostel: Optional[Annotated[str, StringConstraints(max_length=80, strip_whitespace=True)]] = None
    org_name: Optional[Annotated[str, StringConstraints(max_length=200, strip_whitespace=True)]] = None
    registration_no: Optional[Annotated[str, StringConstraints(max_length=80, strip_whitespace=True)]] = None
    address: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None
    document_url: Optional[Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]] = None


@router.get("/institutions")
def institutions(db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name} for i in db.query(Institution).order_by(Institution.name)]


class InstitutionRequestIn(BaseModel):
    name: Annotated[str, StringConstraints(min_length=2, max_length=200, strip_whitespace=True)]
    code: Annotated[str, StringConstraints(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$", strip_whitespace=True)]
    requester_name: Annotated[str, StringConstraints(min_length=2, max_length=120, strip_whitespace=True)]
    email: str
    password: str
    phone: Optional[Annotated[str, StringConstraints(pattern=PhoneRegex)]] = None
    message: Optional[Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]] = None


@router.post("/institution-requests", status_code=201)
def request_institution(b: InstitutionRequestIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    rate_limit(f"inst_request:{ip}", 5, 3600)
    check_pw(b.password)
    email = validate_email_address(b.email)
    code = b.code.strip().upper()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    if db.query(Institution).filter(func.lower(Institution.code) == code.lower()).first():
        raise HTTPException(409, "A mess with this code is already registered")
    if db.query(InstitutionRequest).filter(
        InstitutionRequest.status == "pending",
        func.lower(InstitutionRequest.code) == code.lower(),
    ).first():
        raise HTTPException(409, "A request with this mess code is already awaiting review")
    if db.query(InstitutionRequest).filter(
        InstitutionRequest.status == "pending",
        InstitutionRequest.email == email,
    ).first():
        raise HTTPException(409, "A mess request from this email is already awaiting review")

    pending = InstitutionRequest(
        name=b.name.strip(),
        code=code,
        requester_name=b.requester_name.strip(),
        email=email,
        password_hash=hash_password(b.password),
        phone=b.phone,
        message=b.message,
    )
    db.add(pending)
    db.commit()
    return {"id": pending.id, "message": "Mess registration request submitted for review."}


@router.post("/register", status_code=201)
def register(
    b: RegisterIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    rate_limit(f"reg:{ip}", 10, 300)
    check_pw(b.password)
    norm_email = validate_email_address(b.email)

    if db.query(User).filter(User.email == norm_email).first():
        raise HTTPException(409, "An account with this email already exists")

    if b.role == "student":
        inst = db.get(Institution, b.institution_id) if b.institution_id else None
        if not inst:
            raise HTTPException(422, "Select a valid institution")
        allowed_domains = (inst.settings or {}).get("allowed_email_domains")
        if allowed_domains and isinstance(allowed_domains, list):
            domain = norm_email.split("@")[-1].lower()
            if domain not in [d.lower() for d in allowed_domains]:
                raise HTTPException(422, f"Student registration requires an approved institutional email ({', '.join(allowed_domains)})")

        require_appr = bool((inst.settings or {}).get("require_student_approval", False))
        u = User(
            email=norm_email,
            name=b.name,
            password_hash=hash_password(b.password),
            role="student",
            institution_id=inst.id,
            phone=b.phone,
            is_approved=not require_appr,
            email_verified=False,
            token_version=1,
        )
        db.add(u)
        db.flush()
        db.add(StudentProfile(user_id=u.id, diet=b.diet, hostel=b.hostel))
    else:
        if not b.org_name:
            raise HTTPException(422, "Organisation name is required")
        u = User(
            email=norm_email,
            name=b.name,
            password_hash=hash_password(b.password),
            role="ngo",
            phone=b.phone,
            is_approved=False,
            email_verified=False,
            token_version=1,
        )
        db.add(u)
        db.flush()
        db.add(
            NGOPartner(
                user_id=u.id,
                org_name=b.org_name,
                registration_no=b.registration_no,
                address=b.address,
                document_url=b.document_url,
                verified=False,
            )
        )

    generate_and_dispatch_otp(db, norm_email, "signup", ip, background_tasks)
    audit(db, u, "register", "user", u.id, "Registered account, OTP issued")
    db.commit()

    return {
        "id": u.id,
        "message": "Account created. Please check your inbox for the 6-digit verification code.",
        "email_masked": mask_email(norm_email),
        "resend_in": 60,
    }


class VerifyEmailIn(BaseModel):
    email: str
    code: str


@router.post("/verify-email")
def verify_email(b: VerifyEmailIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    rate_limit(f"verify_email:{ip}", 10, 60)
    email = b.email.strip().lower()
    u = db.query(User).filter(User.email == email).first()
    if not u:
        raise HTTPException(404, "User account not found")

    check_and_consume_otp(db, email, "signup", b.code)
    u.email_verified = True
    u.email_verified_at = local_now()

    if u.role == "ngo":
        # Notify admins that NGO is now verified and awaiting approval
        admins = staff_ids(db, u.institution_id, ("mess_admin", "super_admin")) if u.institution_id else [
            x for (x,) in db.query(User.id).filter(User.role.in_(("mess_admin", "super_admin")), User.is_active == True)  # noqa
        ]
        partner = db.get(NGOPartner, u.id)
        org = partner.org_name if partner else "NGO partner"
        notify(db, admins, "New verified partner awaiting approval", f"{org} ({u.email}) verified email and is awaiting review.", "/users")

    audit(db, u, "verify_email", "user", u.id, "Email address verified via OTP")
    db.commit()

    if u.role == "student" and u.is_approved:
        return {
            "access_token": make_token(u.id, token_version=u.token_version),
            "token_type": "bearer",
            "user": user_out(db, u),
            "message": "Email verified successfully.",
        }

    return {
        "message": "Email verified successfully. Partner accounts must be approved by an administrator before logging in." if u.role == "ngo" else "Email verified. Awaiting admin approval.",
        "user": user_out(db, u),
    }


class ResendOtpIn(BaseModel):
    email: str
    purpose: Literal["signup", "login", "reset"]


@router.post("/resend-otp")
def resend_otp(b: ResendOtpIn, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    ip = client_ip(request)
    rate_limit(f"resend_otp:{ip}", 6, 60)
    email = b.email.strip().lower()

    # Never reveal whether an unregistered email exists on login/reset
    u = db.query(User).filter(User.email == email).first()
    if u or b.purpose == "signup":
        generate_and_dispatch_otp(db, email, b.purpose, ip, background_tasks)

    return {"message": "A new verification code has been dispatched if the account is eligible.", "resend_in": 60}


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(
    b: LoginIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None),
):
    ip = client_ip(request)
    email = b.email.strip().lower()
    rate_limit(f"login:{ip}:{email}", 8, 60)

    u = db.query(User).filter(User.email == email).first()

    # Generic check to prevent account enumeration
    if not u:
        raise HTTPException(401, "Incorrect email or password")

    # Account Lockout Check
    if u.locked_until and u.locked_until > local_now():
        log.warning("Login attempt on locked account: %s", email)
        raise HTTPException(401, "Incorrect email or password")

    if not verify_password(b.password, u.password_hash):
        u.failed_login_attempts = (u.failed_login_attempts or 0) + 1
        if u.failed_login_attempts >= 5:
            u.locked_until = local_now() + timedelta(minutes=15)
            audit(db, u, "account_lockout", "user", u.id, "5 failed login attempts; locked for 15 minutes")
            log.warning("Account locked for 15 minutes due to 5 failures: %s", email)
        db.commit()
        raise HTTPException(401, "Incorrect email or password")

    # Reset failure counter on valid password
    u.failed_login_attempts = 0
    u.locked_until = None
    db.commit()

    if not u.is_active:
        raise HTTPException(403, "This account has been deactivated")
    if not u.email_verified:
        # Issue a new signup OTP so user can finish verification
        generate_and_dispatch_otp(db, email, "signup", ip, background_tasks)
        raise HTTPException(403, "Please verify your email address before logging in. A new verification code was sent to your inbox.")
    if not u.is_approved:
        raise HTTPException(403, "Your partner account is awaiting approval from the mess administrator")

    # Check Trusted Device
    trusted_device = False
    if x_device_token:
        try:
            device_payload = jwt.decode(x_device_token, settings.secret_key, algorithms=["HS256"])
            if (
                device_payload.get("purpose") == "trusted_device"
                and device_payload.get("sub") == str(u.id)
                and device_payload.get("token_version") == u.token_version
            ):
                trusted_device = True
        except Exception:
            trusted_device = False

    # Check if OTP is required
    require_otp = settings.login_otp_enabled
    if settings.app_env == "production" and u.role in ("super_admin", "mess_admin"):
        require_otp = True

    if require_otp and not trusted_device:
        challenge_id = jwt.encode(
            {
                "sub": str(u.id),
                "purpose": "login_challenge",
                "email": u.email,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            settings.secret_key,
            algorithm="HS256",
        )
        generate_and_dispatch_otp(db, u.email, "login", ip, background_tasks)
        return {
            "otp_required": True,
            "challenge_id": challenge_id,
            "email_masked": mask_email(u.email),
            "message": "Enter the 6-digit code sent to your email to complete login.",
        }

    u.last_login = local_now()
    audit(db, u, "login", "user", u.id)
    db.commit()

    return {
        "access_token": make_token(u.id, token_version=u.token_version),
        "token_type": "bearer",
        "user": user_out(db, u),
    }


class LoginVerifyIn(BaseModel):
    challenge_id: str
    code: str
    trust_device: Optional[bool] = False


@router.post("/login/verify")
def login_verify(b: LoginVerifyIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    rate_limit(f"login_verify:{ip}", 10, 60)

    try:
        p = jwt.decode(b.challenge_id, settings.secret_key, algorithms=["HS256"])
        assert p.get("purpose") == "login_challenge"
        email = p.get("email")
    except Exception:
        raise HTTPException(400, "Invalid or expired login challenge")

    u = db.get(User, int(p["sub"]))
    if not u or not u.is_active:
        raise HTTPException(401, "Account not available")

    check_and_consume_otp(db, email, "login", b.code)

    u.last_login = local_now()
    audit(db, u, "login_otp_verified", "user", u.id)
    db.commit()

    res = {
        "access_token": make_token(u.id, token_version=u.token_version),
        "token_type": "bearer",
        "user": user_out(db, u),
    }

    if b.trust_device:
        device_token = jwt.encode(
            {
                "sub": str(u.id),
                "purpose": "trusted_device",
                "token_version": u.token_version,
                "exp": datetime.now(timezone.utc) + timedelta(days=30),
            },
            settings.secret_key,
            algorithm="HS256",
        )
        res["device_token"] = device_token

    return res


@router.get("/me")
def me(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, u)


class ProfileIn(BaseModel):
    name: Optional[Annotated[str, StringConstraints(min_length=2, max_length=120, strip_whitespace=True)]] = None
    phone: Optional[Annotated[str, StringConstraints(pattern=PhoneRegex)]] = None
    diet: Optional[Literal["veg", "vegan"]] = None
    hostel: Optional[Annotated[str, StringConstraints(max_length=80, strip_whitespace=True)]] = None
    dietary_notes: Optional[Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]] = None


@router.patch("/me")
def update_me(b: ProfileIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.name:
        u.name = b.name
    if b.phone is not None:
        u.phone = b.phone
    if u.role == "student":
        p = db.get(StudentProfile, u.id) or StudentProfile(user_id=u.id)
        db.add(p)
        if b.diet:
            p.diet = b.diet
        if b.hostel is not None:
            p.hostel = b.hostel
        if b.dietary_notes is not None:
            p.dietary_notes = b.dietary_notes
    audit(db, u, "update_profile", "user", u.id)
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
    # Invalidate all prior sessions on password change
    u.token_version = (u.token_version or 1) + 1
    audit(db, u, "change_password", "user", u.id, "Password changed; invalidated existing sessions")
    db.commit()
    return {"ok": True, "message": "Password changed. Please log in again."}


@router.post("/logout-all")
def logout_all(u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Invalidates all issued JWT tokens for this user across all devices."""
    u.token_version = (u.token_version or 1) + 1
    audit(db, u, "logout_all", "user", u.id, "Invalidated all sessions")
    db.commit()
    return {"ok": True, "message": "All sessions have been logged out."}


class ForgotIn(BaseModel):
    email: str


@router.post("/forgot-password")
def forgot(
    b: ForgotIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    rate_limit(f"forgot:{ip}", 5, 300)
    email = b.email.strip().lower()
    u = db.query(User).filter(User.email == email).first()

    # Never reveal whether an email exists
    if u and u.is_active:
        generate_and_dispatch_otp(
            db,
            u.email,
            "reset",
            ip,
            background_tasks,
            subject_override="Shakambari AI Password Reset Code",
        )

    return {"message": "If that email is registered, a 6-digit verification code has been dispatched."}


class ResetIn(BaseModel):
    email: str
    code: str
    new_password: str


@router.post("/reset-password")
def reset_password(b: ResetIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    rate_limit(f"reset:{ip}", 6, 60)
    email = b.email.strip().lower()
    check_pw(b.new_password)

    u = db.query(User).filter(User.email == email).first()
    if not u or not u.is_active:
        raise HTTPException(400, "Password reset request is invalid or expired")

    check_and_consume_otp(db, email, "reset", b.code)
    u.password_hash = hash_password(b.new_password)
    u.token_version = (u.token_version or 1) + 1  # Invalidate all prior tokens
    u.failed_login_attempts = 0
    u.locked_until = None
    audit(db, u, "reset_password", "user", u.id, "Password reset via OTP")
    db.commit()

    return {"ok": True, "message": "Password has been successfully updated. You may now log in."}
