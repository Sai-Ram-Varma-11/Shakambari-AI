import csv, io, math
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
REPORT_COLUMNS = {"date", "meal_type", "dish", "attendance", "prepared_kg", "leftover_kg"}


@router.post("/analyze-report")
async def analyze_report(
    file: UploadFile = File(...),
    ctx: Ctx = Depends(need("mess_admin")),
):
    """Prototype analysis of an uploaded CSV report; it never writes imported data to operational records."""
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Report must be 5 MB or smaller")
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except UnicodeDecodeError:
        raise HTTPException(422, "Report must be a UTF-8 CSV file")
    if not reader.fieldnames:
        raise HTTPException(422, "CSV report is empty or missing a header row")

    field_map = {name.strip().lower(): name for name in reader.fieldnames if name}
    missing = REPORT_COLUMNS - field_map.keys()
    if missing:
        raise HTTPException(422, f"CSV is missing required columns: {', '.join(sorted(missing))}")

    rows = []
    try:
        for line, raw in enumerate(reader, start=2):
            if line > 10002:
                raise HTTPException(422, "Report can contain at most 10,000 rows")
            if not any((value or "").strip() for value in raw.values()):
                continue
            row = {key: (raw.get(column) or "").strip() for key, column in field_map.items()}
            meal = row["meal_type"].lower()
            if meal not in ("breakfast", "lunch", "snacks", "dinner"):
                raise ValueError(f"row {line}: meal_type must be breakfast, lunch, snacks, or dinner")
            day = date.fromisoformat(row["date"][:10])
            dish = row["dish"]
            if not dish:
                raise ValueError(f"row {line}: dish is required")
            attendance = int(row["attendance"])
            prepared = float(row["prepared_kg"])
            leftover = float(row["leftover_kg"])
            consumed = float(row["consumed_kg"]) if row.get("consumed_kg") else prepared - leftover
            bookings = int(row["bookings"]) if row.get("bookings") else 0
            values = (attendance, prepared, leftover, consumed, bookings)
            if any(not math.isfinite(value) for value in values):
                raise ValueError(f"row {line}: quantities must be finite numbers")
            if attendance < 0 or bookings < 0 or prepared < 0 or leftover < 0 or consumed < 0:
                raise ValueError(f"row {line}: attendance and quantities cannot be negative")
            if leftover > prepared or consumed > prepared + 0.01:
                raise ValueError(f"row {line}: consumed and leftover quantities cannot exceed prepared kg")
            rows.append({
                "date": day.isoformat(),
                "meal_type": meal,
                "dish": dish,
                "attendance": attendance,
                "bookings": bookings,
                "prepared_kg": prepared,
                "consumed_kg": consumed,
                "leftover_kg": leftover,
            })
    except HTTPException:
        raise
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, f"Invalid CSV data: {exc}")

    if not rows:
        raise HTTPException(422, "Report has no data rows")

    dish_totals = {}
    meal_totals = {}
    daily_totals = {}
    attendance_by_meal = {}
    bookings_by_meal = {}
    for row in rows:
        key = row["dish"]
        record = dish_totals.setdefault(key, {"dish": key, "services": 0, "prepared_kg": 0.0, "leftover_kg": 0.0})
        record["services"] += 1
        record["prepared_kg"] += row["prepared_kg"]
        record["leftover_kg"] += row["leftover_kg"]

        key = row["meal_type"]
        record = meal_totals.setdefault(key, {"meal_type": key, "prepared_kg": 0.0, "leftover_kg": 0.0, "consumed_kg": 0.0})
        for field in ("prepared_kg", "leftover_kg", "consumed_kg"):
            record[field] += row[field]

        key = row["date"]
        record = daily_totals.setdefault(key, {"date": key, "prepared_kg": 0.0, "leftover_kg": 0.0, "consumed_kg": 0.0})
        for field in ("prepared_kg", "leftover_kg", "consumed_kg"):
            record[field] += row[field]
        attendance_by_meal[(row["date"], row["meal_type"])] = row["attendance"]
        bookings_by_meal[(row["date"], row["meal_type"])] = row["bookings"]

    dishes = []
    recommendations = []
    for record in dish_totals.values():
        waste_pct = record["leftover_kg"] / record["prepared_kg"] * 100 if record["prepared_kg"] else 0
        record["waste_pct"] = round(waste_pct, 1)
        record["average_leftover_kg"] = round(record["leftover_kg"] / record["services"], 2)
        dishes.append(record)
        if record["services"] >= 2 and waste_pct >= 15:
            recommendations.append(
                f"Reduce the next batch of {record['dish']} by about 10-15%. "
                f"{waste_pct:.0f}% was left over across {record['services']} recorded services "
                f"(about {record['average_leftover_kg']:.1f} kg per service)."
            )
    if not recommendations:
        best = max(dishes, key=lambda record: record["waste_pct"])
        if best["waste_pct"] > 0:
            recommendations.append(
                f"Review {best['dish']} first: it had the highest recorded leftovers "
                f"({best['waste_pct']:.0f}%). More repeat records are needed before suggesting a batch change."
            )
        else:
            recommendations.append("No repeat high-waste dish was found in this report. Keep recording daily quantities.")

    series = []
    for day, record in sorted(daily_totals.items()):
        record["waste_pct"] = round(record["leftover_kg"] / record["prepared_kg"] * 100, 1) if record["prepared_kg"] else 0
        record["attendance"] = sum(value for (d, _), value in attendance_by_meal.items() if d == day)
        record["bookings"] = sum(value for (d, _), value in bookings_by_meal.items() if d == day)
        series.append({key: round(value, 1) if isinstance(value, float) else value for key, value in record.items()})

    total_prepared = sum(row["prepared_kg"] for row in rows)
    total_leftover = sum(row["leftover_kg"] for row in rows)
    total_attendance = sum(attendance_by_meal.values())
    return {
        "generated_at": local_now().isoformat(),
        "rows_analyzed": len(rows),
        "summary": {
            "prepared_kg": round(total_prepared, 1),
            "leftover_kg": round(total_leftover, 1),
            "waste_pct": round(total_leftover / total_prepared * 100, 1) if total_prepared else 0,
            "attendance": total_attendance,
        },
        "series": series,
        "meal_totals": [
            {**record, "waste_pct": round(record["leftover_kg"] / record["prepared_kg"] * 100, 1) if record["prepared_kg"] else 0}
            for record in meal_totals.values()
        ],
        "top_dishes": sorted(dishes, key=lambda record: record["leftover_kg"], reverse=True)[:10],
        "recommendations": recommendations,
        "model_note": "Prototype analysis using patterns in the uploaded report; this is not a trained or predictive machine-learning model.",
    }


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


@router.get("/cooking-advice")
def cooking_advice(
    on: Optional[date] = None,
    ctx: Ctx = Depends(need("mess_admin")),
    db: Session = Depends(get_db),
):
    """Simple next-cook quantities grounded in the next day's forecast and recent recorded leftovers."""
    target = on or (local_now().date() + timedelta(days=1))
    schedules = (
        db.query(MealSchedule)
        .filter(MealSchedule.institution_id == ctx.inst_id, MealSchedule.date == target)
        .order_by(MealSchedule.meal_type)
        .all()
    )
    if not schedules:
        return {"date": target.isoformat(), "recommendations": []}

    from ..services.forecast import predict_schedules

    predictions = {
        row["schedule_id"]: row
        for row in predict_schedules(db, ctx.inst_id, [s.id for s in schedules], persist=False)
    }
    recent = A.outcome_frame(db, ctx.inst_id, target - timedelta(days=30), target - timedelta(days=1))
    thr = merged_settings(db.get(Institution, ctx.inst_id))["waste_alert_pct"]
    recommendations = []
    for schedule in schedules:
        prediction = predictions.get(schedule.id, {})
        predicted_dishes = {dish["menu_item_id"]: dish for dish in prediction.get("dishes", [])}
        menu = (
            db.query(MenuItem)
            .join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id)
            .filter(ScheduleDish.schedule_id == schedule.id)
            .order_by(MenuItem.name)
            .all()
        )
        for item in menu:
            if not item.is_active or item.diet not in ("veg", "vegan"):
                continue
            forecast_dish = predicted_dishes.get(item.id)
            if not forecast_dish:
                continue
            history = recent[
                (recent["item_id"] == item.id) & (recent["meal_type"] == schedule.meal_type)
            ] if not recent.empty else recent
            services = int(history["schedule_id"].nunique()) if not history.empty else 0
            prepared = float(history["prepared"].sum()) if services else 0
            leftover = float(history["leftover"].sum()) if services else 0
            waste_pct = round(leftover / prepared * 100, 1) if prepared else 0
            suggested = float(forecast_dish["recommended_kg"])

            if services >= 2 and waste_pct >= thr:
                action = (
                    f"Cook about {suggested:.1f} kg of {item.name}. "
                    f"In the last {services} {schedule.meal_type} meals, about {leftover / services:.1f} kg was left over each time."
                )
            elif services:
                action = (
                    f"Cook about {suggested:.1f} kg of {item.name}. "
                    f"Recent leftovers were low ({waste_pct:.0f}% of what was prepared)."
                )
            else:
                action = (
                    f"Cook about {suggested:.1f} kg of {item.name}, based on expected attendance. "
                    "There is not enough recent waste history for this meal to suggest a change."
                )

            recommendations.append({
                "schedule_id": schedule.id,
                "meal_type": schedule.meal_type,
                "dish": item.name,
                "suggested_kg": round(suggested, 1),
                "recent_services": services,
                "recent_waste_pct": waste_pct,
                "action": action,
            })
    return {"date": target.isoformat(), "generated_at": local_now().isoformat(), "recommendations": recommendations}


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
