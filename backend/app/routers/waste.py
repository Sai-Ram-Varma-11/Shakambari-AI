import csv, io
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ImageObservation, Institution, MealSchedule, MenuItem, ScheduleDish
from ..security import Ctx, need
from ..services import analytics as A
from ..util import local_now, merged_settings

router = APIRouter(prefix="/waste", tags=["waste-analytics"])
D = lambda s, e: (s or local_now().date() - timedelta(days=29), e)


def totals(df):
    if df.empty:
        return {"prepared": 0, "consumed": 0, "leftover": 0, "edible": 0, "inedible": 0, "loss": 0, "waste_pct": 0, "consumption_pct": 0, "meals": 0}
    p, c, l = df["prepared"].sum(), df["consumed"].sum(), df["leftover"].sum()
    return {"prepared": round(p, 2), "consumed": round(c, 2), "leftover": round(l, 2), "edible": round(df["edible"].sum(), 2),
            "inedible": round(df["inedible"].sum(), 2), "loss": round(df["loss"].sum(), 2), "waste_pct": round(l / p * 100, 2) if p else 0,
            "consumption_pct": round(c / p * 100, 2) if p else 0, "meals": int(df["schedule_id"].nunique())}


@router.get("/summary")
def summary(start: Optional[date] = None, end: Optional[date] = None, group: str = "day", ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s, e = D(start, end)
    df = A.outcome_frame(db, ctx.inst_id, s, e)
    cur = merged_settings(db.get(Institution, ctx.inst_id))["currency"]
    series = A.records(A.aggregate(A.with_period(df, group), "period").sort_values("period")) if not df.empty else []
    return {"currency": cur, "start": s, "end": e, "group": group, "totals": totals(df), "series": series}


@router.get("/by-dish")
def by_dish(start: Optional[date] = None, end: Optional[date] = None, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s, e = D(start, end)
    df = A.outcome_frame(db, ctx.inst_id, s, e)
    return A.records(A.aggregate(df, ["item_id", "item"]).sort_values("leftover", ascending=False)) if not df.empty else []


@router.get("/by-meal")
def by_meal(start: Optional[date] = None, end: Optional[date] = None, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    s, e = D(start, end)
    df = A.outcome_frame(db, ctx.inst_id, s, e)
    return A.records(A.aggregate(df, "meal_type")) if not df.empty else []


@router.get("/recommendations")
def recommendations(start: Optional[date] = None, end: Optional[date] = None,
                    ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    today = local_now().date()
    window_start, window_end = start or today - timedelta(days=29), end or today
    df = A.outcome_frame(db, ctx.inst_id, window_start, window_end)
    if df.empty:
        return {"days_reviewed": max((window_end - window_start).days + 1, 0), "recommendations": []}
    threshold = merged_settings(db.get(Institution, ctx.inst_id))["waste_alert_pct"]
    grouped = df.groupby(["meal_type", "item_id", "item"], as_index=False).agg(
        prepared=("prepared", "sum"), leftover=("leftover", "sum"), services=("schedule_id", "nunique"))
    tomorrow_dishes = {
        (s.meal_type, item_id)
        for s in db.query(MealSchedule).filter_by(institution_id=ctx.inst_id, date=today + timedelta(days=1))
        for (item_id,) in db.query(ScheduleDish.menu_item_id).filter_by(schedule_id=s.id)
    }
    out = []
    for row in grouped.itertuples():
        if row.prepared <= 0 or row.services < 2:
            continue
        waste_pct = row.leftover / row.prepared * 100
        if waste_pct < threshold:
            continue
        reduction = min(35, max(10, round(waste_pct * 0.6)))
        out.append({
            "meal_type": row.meal_type,
            "dish": row.item,
            "services": int(row.services),
            "leftover_kg": round(float(row.leftover), 1),
            "waste_pct": round(float(waste_pct), 1),
            "suggested_reduction_pct": reduction,
            "scheduled_tomorrow": (row.meal_type, int(row.item_id)) in tomorrow_dishes,
            "message": f"Cook about {reduction}% less {row.item} for {row.meal_type}. About {row.leftover:.1f} kg was left over in {int(row.services)} recent meals.",
        })
    out.sort(key=lambda r: (not r["scheduled_tomorrow"], -r["leftover_kg"]))
    return {"days_reviewed": max((window_end - window_start).days + 1, 0), "threshold_pct": threshold, "recommendations": out[:12]}


@router.get("/patterns")
def patterns(days: int = 90, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    """Recurring patterns: weekday profile and dishes that are wasted repeatedly. All figures come from recorded data."""
    df = A.outcome_frame(db, ctx.inst_id, local_now().date() - timedelta(days=days))
    if df.empty:
        return {"weekday": [], "recurring_dishes": [], "recommendations": []}
    df["weekday"] = df["date"].dt.day_name()
    wk = A.aggregate(df, "weekday")
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    wk["o"] = wk["weekday"].map({d: i for i, d in enumerate(order)})
    wk = wk.sort_values("o").drop(columns="o")
    thr = merged_settings(db.get(Institution, ctx.inst_id))["waste_alert_pct"]
    df["hi"] = (df["leftover"] / df["prepared"] * 100 > thr)
    rec = df.groupby(["item_id", "item"]).agg(services=("hi", "size"), high_waste_services=("hi", "sum"), leftover=("leftover", "sum")).reset_index()
    rec["share_high"] = (rec["high_waste_services"] / rec["services"] * 100)
    rec = rec[(rec["services"] >= 4) & (rec["share_high"] >= 50)].sort_values("leftover", ascending=False)
    recs = []
    for _, r in rec.head(5).iterrows():
        recs.append(f"{r['item']} exceeded the {thr}% waste threshold in {int(r['high_waste_services'])} of {int(r['services'])} services "
                    f"({r['leftover']:.1f} kg leftover). Consider reducing its preparation quantity or reviewing the dish.")
    if len(wk) > 1:
        w = wk.sort_values("waste_pct", ascending=False).iloc[0]
        recs.append(f"{w['weekday']} has the highest average waste ({w['waste_pct']:.1f}% of prepared food) across the last {days} days.")
    return {"weekday": A.records(wk), "recurring_dishes": A.records(rec), "recommendations": recs, "threshold_pct": thr}


@router.get("/image-breakdown")
def image_breakdown(ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    lab = func.coalesce(ImageObservation.corrected_label, ImageObservation.predicted_label)
    rows = db.query(lab, func.count()).filter(ImageObservation.institution_id == ctx.inst_id, ImageObservation.status == "confirmed").group_by(lab).all()
    return [{"label": l, "count": c} for l, c in rows]


@router.get("/export.csv")
def export(start: Optional[date] = None, end: Optional[date] = None, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    s, e = D(start, end)
    df = A.outcome_frame(db, ctx.inst_id, s, e)
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["date", "meal", "dish", "prepared_kg", "consumed_kg", "leftover_kg", "edible_kg", "inedible_kg", "waste_pct", "est_loss"])
    for r in (df.sort_values(["date", "meal_type"]).itertuples() if not df.empty else []):
        w.writerow([r.date.date(), r.meal_type, r.item, round(r.prepared, 2), round(r.consumed, 2), round(r.leftover, 2), round(r.edible, 2),
                    round(r.inedible, 2), round(r.leftover / r.prepared * 100, 1) if r.prepared else 0, round(r.loss, 2)])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=waste_report.csv"})
