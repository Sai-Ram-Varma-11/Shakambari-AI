from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import MealSchedule, MLModel, Prediction
from ..security import Ctx, need
from ..services import forecast
from ..util import audit, local_now, notify, staff_ids

router = APIRouter(prefix="/predict", tags=["demand-prediction"])


class RunIn(BaseModel):
    schedule_ids: Optional[List[int]] = None
    days: int = 3


def _ids(db, ctx, b: RunIn):
    if b.schedule_ids:
        n = db.query(MealSchedule).filter(MealSchedule.id.in_(b.schedule_ids), MealSchedule.institution_id == ctx.inst_id).count()
        if n != len(set(b.schedule_ids)):
            raise HTTPException(404, "One or more schedules not found")
        return b.schedule_ids
    t = local_now().date()
    return [i for (i,) in db.query(MealSchedule.id).filter(MealSchedule.institution_id == ctx.inst_id, MealSchedule.date >= t,
                                                         MealSchedule.date <= t + timedelta(days=max(1, min(b.days, 14))))]


@router.post("/run")
def run(b: RunIn = RunIn(), ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    ids = _ids(db, ctx, b)
    res = forecast.predict_schedules(db, ctx.inst_id, ids) if ids else []
    if res:
        notify(db, staff_ids(db, ctx.inst_id, ("mess_admin", "kitchen")), "Demand predictions updated", f"{len(res)} meal predictions refreshed.", "/prediction")
        audit(db, ctx.user, "run_prediction", "prediction", None, f"{len(res)} schedules"); db.commit()
    return res


@router.get("/upcoming")
def upcoming(days: int = 3, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    """Computes (without persisting) fresh predictions for the next N days using current booking counts."""
    ids = _ids(db, ctx, RunIn(days=days))
    return forecast.predict_schedules(db, ctx.inst_id, ids, persist=False) if ids else []


@router.get("/model")
def model(ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    m = forecast.active_model(db, ctx.inst_id)
    return {"id": m.id, "algorithm": m.algorithm, "metrics": m.metrics, "n_train": m.n_train, "n_test": m.n_test,
            "trained_at": m.trained_at, "data_mode": m.data_mode, "features": m.features,
            "data_label": "Trained on SYNTHETIC demonstration data - not real institutional data" if m.data_mode == "demo" else "Trained on recorded institutional data"}


@router.post("/retrain")
def retrain(ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    m = forecast.train(db, ctx.inst_id)
    audit(db, ctx.user, "retrain_model", "ml_model", m.id, m.algorithm); db.commit()
    return {"id": m.id, "algorithm": m.algorithm, "metrics": m.metrics, "n_train": m.n_train, "n_test": m.n_test}


@router.get("/history")
def history(limit: int = 40, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    """Stored attendance predictions joined with actual attendance once it has been recorded."""
    rows = (db.query(Prediction, MealSchedule).join(MealSchedule, MealSchedule.id == Prediction.schedule_id)
            .filter(MealSchedule.institution_id == ctx.inst_id, Prediction.kind == "attendance")
            .order_by(Prediction.id.desc()).limit(min(limit, 200)).all())
    out = [{"prediction_id": p.id, "date": s.date.isoformat(), "meal_type": s.meal_type, "predicted": round(p.value), "lower": round(p.lower or 0),
            "upper": round(p.upper or 0), "active_bookings": p.active_bookings, "actual": s.headcount, "created_at": p.created_at} for p, s in rows]
    done = [o for o in out if o["actual"] is not None]
    mae = round(sum(abs(o["predicted"] - o["actual"]) for o in done) / len(done), 2) if done else None
    return {"rows": out, "compared": len(done), "mae_on_stored_predictions": mae}
