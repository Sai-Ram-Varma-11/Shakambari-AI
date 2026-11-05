from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Notification
from ..security import Ctx, get_ctx, need
from ..services.alerts_engine import generate
from ..util import audit

router = APIRouter(tags=["alerts"])


def a_out(a):
    return {"id": a.id, "kind": a.kind, "severity": a.severity, "title": a.title, "what": a.what, "evidence": a.evidence, "why": a.why,
            "action": a.action, "is_resolved": a.is_resolved, "created_at": a.created_at}


@router.get("/alerts")
def list_alerts(include_resolved: bool = False, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    q = db.query(Alert).filter_by(institution_id=ctx.inst_id)
    if not include_resolved:
        q = q.filter_by(is_resolved=False)
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted([a_out(a) for a in q.order_by(Alert.id.desc())], key=lambda a: order.get(a["severity"], 3))


@router.post("/alerts/generate")
def gen(ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    rows = generate(db, ctx.inst_id)
    audit(db, ctx.user, "generate_alerts", "alert", None, str(len(rows))); db.commit()
    return [a_out(a) for a in rows]


@router.post("/alerts/{aid}/resolve")
def resolve(aid: int, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    a = db.get(Alert, aid)
    if not a or a.institution_id != ctx.inst_id:
        raise HTTPException(404, "Alert not found")
    a.is_resolved = True; db.commit()
    return a_out(a)


@router.get("/notifications")
def notifications(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    q = db.query(Notification).filter_by(user_id=ctx.user.id)
    unread = q.filter_by(is_read=False).count()
    rows = q.order_by(Notification.id.desc()).limit(50).all()
    return {"unread": unread, "items": [{"id": n.id, "title": n.title, "body": n.body, "link": n.link, "is_read": n.is_read, "created_at": n.created_at} for n in rows]}


@router.post("/notifications/read-all")
def read_all(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    db.query(Notification).filter_by(user_id=ctx.user.id, is_read=False).update({"is_read": True}); db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/read")
def read_one(nid: int, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != ctx.user.id:
        raise HTTPException(404, "Notification not found")
    n.is_read = True; db.commit()
    return {"ok": True}
