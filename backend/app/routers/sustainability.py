"""Module 8. Every number is tagged measured / calculated / estimate."""
from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import CollectionRecord, Institution, MenuItem, RedistributionRequest, SurplusListing, SustainabilitySnapshot
from ..security import Ctx, need
from ..services import analytics as A
from ..util import audit, local_now, merged_settings

router = APIRouter(prefix="/sustainability", tags=["sustainability"])


def build(db, inst_id, start: date, end: date):
    cfg = merged_settings(db.get(Institution, inst_id))
    df = A.outcome_frame(db, inst_id, start, end)
    p = float(df["prepared"].sum()) if not df.empty else 0.0
    c = float(df["consumed"].sum()) if not df.empty else 0.0
    l = float(df["leftover"].sum()) if not df.empty else 0.0
    e = float(df["edible"].sum()) if not df.empty else 0.0
    loss = float(df["loss"].sum()) if not df.empty else 0.0
    col = (db.query(CollectionRecord, SurplusListing).join(RedistributionRequest, RedistributionRequest.id == CollectionRecord.request_id)
           .join(SurplusListing, SurplusListing.id == RedistributionRequest.listing_id)
           .filter(SurplusListing.institution_id == inst_id, func.date(CollectionRecord.collected_at) >= str(start), func.date(CollectionRecord.collected_at) <= str(end)).all())
    ckg = sum(x.collected_kg for x, _ in col)
    cportions = sum(x.portions or 0 for x, _ in col)
    costs = {i: v for i, v in db.query(MenuItem.id, MenuItem.cost_per_kg).filter_by(institution_id=inst_id)}
    avg_cost = (sum(costs.values()) / len(costs)) if costs else 0
    value = sum(x.collected_kg * costs.get(lst.menu_item_id, avg_cost) for x, lst in col)
    listed = db.query(func.coalesce(func.sum(SurplusListing.quantity_kg), 0)).filter(SurplusListing.institution_id == inst_id, SurplusListing.status.in_(("eligible", "approved", "collected", "expired")),
                                                                                    func.date(SurplusListing.created_at) >= str(start), func.date(SurplusListing.created_at) <= str(end)).scalar()
    f = settings.co2e_per_kg_food
    M = lambda k, label, v, unit, typ, note="": {"key": k, "label": label, "value": round(v, 2), "unit": unit, "type": typ, "note": note}
    metrics = [
        M("prepared", "Food prepared", p, "kg", "measured", "Recorded by kitchen staff"),
        M("consumed", "Food consumed", c, "kg", "measured", "Recorded by kitchen staff"),
        M("wasted", "Food left over", l, "kg", "measured", "Recorded leftovers (edible + inedible)"),
        M("waste_pct", "Waste rate", l / p * 100 if p else 0, "%", "calculated", "leftover / prepared"),
        M("edible_surplus", "Edible surplus recorded", e, "kg", "measured", "Edible leftovers recorded; NOT all of it is eligible or redistributed"),
        M("listed", "Surplus listed as eligible", float(listed or 0), "kg", "measured", "Verified listings only"),
        M("collected", "Surplus actually collected", ckg, "kg", "measured", "Recorded by partners at pickup"),
        M("portions", "Meal portions collected", cportions, "portions", "measured", "As entered by partner at pickup"),
        M("redistribution_rate", "Share of edible surplus collected", ckg / e * 100 if e else 0, "%", "calculated", "collected / edible surplus recorded"),
        M("waste_cost", "Cost of leftover food", loss, cfg["currency"], "calculated", "leftover kg x configured cost per kg"),
        M("savings", "Value of food redistributed", value, cfg["currency"], "estimate", "collected kg x configured dish cost; not cash saved"),
        M("co2e_avoided", "CO2e linked to redistributed food", ckg * f, "kg CO2e", "estimate", f"Uses an adjustable factor of {f} kg CO2e per kg food - an approximation, verify before citing"),
    ]
    df2 = A.with_period(df, "month") if not df.empty else df
    series = []
    if not df.empty:
        agg = A.aggregate(df2, "period").sort_values("period")
        cm = {}
        for x, _ in col:
            cm[x.collected_at.strftime("%Y-%m")] = cm.get(x.collected_at.strftime("%Y-%m"), 0) + x.collected_kg
        for r in A.records(agg):
            series.append({"period": r["period"], "prepared": r["prepared"], "consumed": r["consumed"], "leftover": r["leftover"], "waste_pct": r["waste_pct"], "collected": round(cm.get(r["period"], 0), 2)})
    return {"start": start, "end": end, "currency": cfg["currency"], "metrics": metrics, "series": series}


def summary_text(db, inst_id, cur, start, end):
    days = (end - start).days + 1
    prev = build(db, inst_id, start - timedelta(days=days), start - timedelta(days=1))
    g = lambda d, k: next(m["value"] for m in d["metrics"] if m["key"] == k)
    lines = []
    if g(cur, "prepared"):
        lines.append(f"Waste rate this period: {g(cur, 'waste_pct'):.1f}% of {g(cur, 'prepared'):.0f} kg prepared.")
        if g(prev, "prepared"):
            d = g(cur, "waste_pct") - g(prev, "waste_pct")
            lines.append(f"That is {abs(d):.1f} percentage points {'lower' if d < 0 else 'higher'} than the previous period of equal length ({g(prev, 'waste_pct'):.1f}%).")
    if g(cur, "collected"):
        lines.append(f"{g(cur, 'collected'):.1f} kg ({g(cur, 'portions'):.0f} portions) were collected by partners - {g(cur, 'redistribution_rate'):.0f}% of recorded edible surplus.")
    return lines or ["No recorded activity in this period."]


@router.get("/summary")
def summary(start: Optional[date] = None, end: Optional[date] = None, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    end = end or local_now().date()
    start = start or end - timedelta(days=89)
    d = build(db, ctx.inst_id, start, end)
    d["summary"] = summary_text(db, ctx.inst_id, d, start, end)
    d["legend"] = {"measured": "Recorded directly", "calculated": "Derived from measured values", "estimate": "Depends on assumptions"}
    return d


@router.get("/report")
def report(period: str, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    """period = YYYY-MM (monthly) or YYYY (yearly)."""
    try:
        if len(period) == 7:
            y, m = int(period[:4]), int(period[5:]); start, end = date(y, m, 1), date(y, m, monthrange(y, m)[1])
        else:
            y = int(period); start, end = date(y, 1, 1), date(y, 12, 31)
    except Exception:
        raise HTTPException(422, "period must be YYYY or YYYY-MM")
    d = build(db, ctx.inst_id, start, end)
    d["summary"] = summary_text(db, ctx.inst_id, d, start, end)
    return d


@router.post("/snapshot")
def snapshot(period: str, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    d = report(period, ctx, db)
    db.add(SustainabilitySnapshot(institution_id=ctx.inst_id, period=period, data=jsonable(d)))
    audit(db, ctx.user, "sustainability_snapshot", "snapshot", None, period); db.commit()
    return {"saved": period}


def jsonable(d):
    import json
    return json.loads(json.dumps(d, default=str))


@router.get("/snapshots")
def snapshots(ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    return [{"id": s.id, "period": s.period, "created_at": s.created_at} for s in db.query(SustainabilitySnapshot).filter_by(institution_id=ctx.inst_id).order_by(SustainabilitySnapshot.id.desc())]
