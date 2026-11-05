import hashlib, hmac, os, time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

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


def make_token(sub, purpose="access", minutes=None, **extra):
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes or settings.access_token_minutes)
    return jwt.encode({"sub": str(sub), "purpose": purpose, "exp": exp, **extra}, settings.secret_key, algorithm="HS256")


def read_token(t: str):
    return jwt.decode(t, settings.secret_key, algorithms=["HS256"])


_hits = defaultdict(deque)


def rate_limit(key: str, limit=8, window=60):
    q, nowt = _hits[key], time.time()
    while q and q[0] < nowt - window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many attempts. Please wait a minute and try again.")
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
