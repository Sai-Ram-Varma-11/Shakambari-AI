import base64
import hashlib
import hmac
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

ITER = 200_000


def hash_password(p: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", p.encode(), salt, ITER)
    return f"pbkdf2_sha256${ITER}${salt.hex()}${dk.hex()}"


def verify_password(p: str, h: str) -> bool:
    try:
        _, it, salt, dk = h.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


def make_token(sub, purpose="access", minutes=None, token_version=None, **extra):
    now_utc = datetime.now(timezone.utc)
    exp = now_utc + timedelta(minutes=minutes or settings.access_token_minutes)
    payload = {
        "sub": str(sub),
        "purpose": purpose,
        "iat": int(now_utc.timestamp()),
        "jti": uuid.uuid4().hex,
        "exp": exp,
    }
    if token_version is not None:
        payload["token_version"] = token_version
    payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def read_token(t: str):
    return jwt.decode(t, settings.secret_key, algorithms=["HS256"])


# --- QR Meal Pass Token Utilities ---
def make_meal_pass(student_id: int, schedule_id: int, booking_id: int, exp_dt: datetime) -> str:
    now_utc = datetime.now(timezone.utc)
    payload = {
        "purpose": "meal_pass",
        "student_id": student_id,
        "schedule_id": schedule_id,
        "booking_id": booking_id,
        "iat": int(now_utc.timestamp()),
        "jti": uuid.uuid4().hex,
        "exp": exp_dt,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def read_meal_pass(token: str) -> dict:
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    if payload.get("purpose") != "meal_pass":
        raise ValueError("Invalid pass type")
    return payload


# --- Pickup Handover Code Utilities ---
def hash_handover_code(code: str) -> str:
    return hmac.new(settings.secret_key.encode(), code.strip().encode(), "sha256").hexdigest()


def encrypt_handover_code(code: str) -> str:
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    nonce = os.urandom(12)
    keystream = hashlib.sha256(key + nonce).digest()
    code_bytes = code.encode("utf-8")
    cipher = bytes(c ^ k for c, k in zip(code_bytes, keystream))
    tag = hmac.new(key, nonce + cipher, "sha256").digest()[:16]
    return base64.urlsafe_b64encode(nonce + tag + cipher).decode()


def decrypt_handover_code(enc: str) -> Optional[str]:
    try:
        raw = base64.urlsafe_b64decode(enc.encode())
        nonce, tag, cipher = raw[:12], raw[12:28], raw[28:]
        key = hashlib.sha256(settings.secret_key.encode()).digest()
        expected_tag = hmac.new(key, nonce + cipher, "sha256").digest()[:16]
        if not hmac.compare_digest(tag, expected_tag):
            return None
        keystream = hashlib.sha256(key + nonce).digest()
        return bytes(c ^ k for c, k in zip(cipher, keystream)).decode("utf-8")
    except Exception:
        return None


# --- Client IP & Rate Limiting ---
def client_ip(request: Request) -> str:
    if not request:
        return "127.0.0.1"
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


_hits = defaultdict(deque)


def rate_limit(key: str, limit=8, window=60):
    nowt = time.time()
    q = _hits[key]
    while q and q[0] < nowt - window:
        q.popleft()
    if len(q) >= limit:
        retry_after = int(q[0] + window - nowt + 1)
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait a minute and try again.",
            headers={"Retry-After": str(max(1, retry_after))},
        )
    q.append(nowt)


bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    try:
        p = read_token(creds.credentials)
        assert p.get("purpose") == "access"
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    u = db.get(User, int(p["sub"]))
    if not u or not u.is_active:
        raise HTTPException(401, "Account not available")
    if "token_version" in p and getattr(u, "token_version", 1) != p["token_version"]:
        raise HTTPException(401, "Token has been invalidated. Please log in again.")
    return u


class Ctx:
    def __init__(self, user, inst_id):
        self.user, self.inst_id = user, inst_id


def get_ctx(request: Request, user: User = Depends(current_user)) -> Ctx:
    inst = user.institution_id
    if user.role == "super_admin" and request.headers.get("x-institution-id", "").isdigit():
        inst = int(request.headers["x-institution-id"])
    return Ctx(user, inst)


def need(*roles):
    """Role guard. super_admin passes every guard."""
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if ctx.user.role != "super_admin" and ctx.user.role not in roles:
            raise HTTPException(403, "You do not have permission for this action")
        if ctx.user.role != "ngo" and ctx.inst_id is None:
            raise HTTPException(400, "No institution selected")
        return ctx
    return dep


MANAGER = ("mess_admin",)
STAFF = ("mess_admin", "kitchen")
