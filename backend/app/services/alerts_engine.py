"""Module 7 - rule-based, explainable alerts. Every alert states what / evidence / why / action and uses only recorded data."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..models import Alert, Booking, Institution, MealSchedule, Notification, SurplusListing, RedistributionRequest, User
from ..util import local_now, merged_settings, notify, staff_ids
from . import analytics as A
from . import forecast


def generate(db: Session, inst_id: int):
    inst = db.get(Institution, inst_id)
    cfg = merged_settings(inst)
    thr = cfg["waste_alert_pct"]
    now = local_now()
    out = []
    add = lambda kind, sev, title, what, ev, why, action: out.append(dict(kind=kind, severity=sev, title=title, what=what, evidence=ev, why=why, action=action))

    df = A.outcome_frame(db, inst_id, now.date() - timedelta(days=120))
    if not df.empty:
        daily = A.aggregate(A.with_period(df, "day"), "period")
        daily["date"] = pd.to_datetime(daily["period"])
        daily = daily.sort_values("date")
        last = daily.iloc[-1]
        prev = daily[(daily["date"].dt.day_of_week == last["date"].day_of_week) & (daily["date"] < last["date"])].tail(4)
        if len(prev) >= 3 and last["waste_pct"] > prev["waste_pct"].mean() + 5:
            wd = last["date"].strftime("%A")
            add("waste_increase", "warning", f"Food waste higher than previous {wd}s", f"Waste on {last['date']:%d %b} was {last['waste_pct']:.1f}% of prepared food.",
                f"Average of the previous {len(prev)} {wd}s: {prev['waste_pct'].mean():.1f}% (recorded kitchen data).",
                "A sustained rise means over-preparation is costing money and food.", "Check that day's preparation quantities against attendance and review the dishes with the most leftovers.")
        for (iid, name), g in df.sort_values("date").groupby(["item_id", "item"]):
            g = g.tail(7)
            hi = int(((g["leftover"] / g["prepared"] * 100) > thr).sum())
            if len(g) >= 5 and hi >= 3:
                add("dish_high_leftover", "warning", f"{name}: repeated high leftovers", f"{name} exceeded the {thr}% waste threshold in {hi} of its last {len(g)} services.",
                    f"Average leftover {g['leftover'].mean():.1f} kg per service; average waste {(g['leftover'].sum() / g['prepared'].sum() * 100):.1f}%.",
                    "Repeated surplus of one dish suggests its portion/quantity assumption is too high or it is unpopular.", "Reduce its planned quantity or review it in Menu Optimisation.")
    sf = forecast.schedule_frame(db, inst_id)
    t = now.date()
    up = [int(i) for i in sf[(sf["date"] >= str(t)) & (sf["date"] <= str(t + timedelta(days=2)))]["id"]] if not sf.empty else []
    if up:
        preds = {p["schedule_id"]: p for p in forecast.predict_schedules(db, inst_id, up, persist=False)}
        hist = sf[sf["att"].notna()]
        for _, r in sf[sf["id"].isin(up)].iterrows():
            if r["is_holiday"]:
                continue
            same = hist[(hist["meal_type"] == r["meal_type"]) & (hist["dow"] == r["dow"])].tail(4)
            label = f"{r['meal_type']} on {r['date']:%a %d %b}"
            if len(same) >= 3:
                usual_b = same["active"].mean()
                if usual_b > 10 and r["active"] < 0.7 * usual_b:
                    add("low_bookings", "warning", f"Bookings low for {label}", f"{int(r['active'])} active bookings so far.",
                        f"The previous {len(same)} similar meals had {usual_b:.0f} bookings on average.", "Preparing from bookings alone could cause shortages if students arrive unbooked, or surplus if the low count is real.", "Wait for the cutoff, then rely on the demand forecast rather than raw bookings.")
                p = preds[int(r["id"])]
                usual_a = same["att"].mean()
                if p["predicted_attendance"] < 0.85 * usual_a:
                    add("low_demand", "info", f"Lower demand predicted for {label}", f"Forecast {p['predicted_attendance']} students (80% range {p['lower']}-{p['upper']}).",
                        f"Usual attendance for this meal and weekday: {usual_a:.0f} (last {len(same)} occurrences).", "Preparing the usual quantity would likely leave surplus.", "Scale preparation to the recommendation in Demand Prediction.")
            if int(r["id"]) in preds:
                for d in preds[int(r["id"])]["dishes"]:
                    if d.get("status") in ("surplus_risk", "shortage_risk"):
                        add("prep_vs_prediction", "warning", f"Preparation vs forecast: {d['name']} ({label})", f"Prepared {d['prepared_kg']} kg; recommended {d['recommended_kg']} kg.",
                            f"Forecast range for this dish: {d['lower_kg']}-{d['upper_kg']} kg.", "Quantity outside the forecast range signals likely " + ("surplus." if d["status"] == "surplus_risk" else "shortage."), "Review the quantity before cooking completes.")
    pend = db.query(SurplusListing).filter_by(institution_id=inst_id, status="pending_review").count()
    elig = db.query(SurplusListing).filter_by(institution_id=inst_id, status="eligible").count()
    reqs = db.query(RedistributionRequest).join(SurplusListing, SurplusListing.id == RedistributionRequest.listing_id).filter(SurplusListing.institution_id == inst_id, RedistributionRequest.status == "pending").count()
    if pend:
        add("surplus_review", "warning", "Surplus listings need food-safety review", f"{pend} listing(s) are waiting for review.", "Status 'pending_review' in Surplus Management.", "Time-sensitive: food must be collected within the safe holding window.", "Review and approve or reject them promptly.")
    if elig:
        add("surplus_awaiting", "info", "Eligible surplus awaiting collection", f"{elig} verified listing(s) have not been requested yet.", "Status 'eligible' with no approved request.", "Unclaimed surplus becomes ineligible as time passes.", "Contact verified partners or withdraw the listing.")
    if reqs:
        add("requests_pending", "warning", "Collection requests awaiting your decision", f"{reqs} request(s) are pending.", "Redistribution requests in 'pending' state.", "Partners are waiting to plan pickup.", "Approve one request and set a pickup time.")
    try:
        from ..routers.menu_opt import compute
        _, _, extra = compute(db, inst_id, 90)
        for c in extra.get("worst_combinations", [])[:1]:
            if c["vs_overall_pp"] >= 4:
                add("combo_waste", "info", "A menu combination is linked to higher waste", f"{c['pair']} served together {c['times']} times: {c['avg_waste_pct']}% waste.",
                    f"{c['vs_overall_pp']} points above the overall meal average.", "Association only; other factors (weekday, event) may explain it.", "Try an alternative pairing for a few weeks and compare.")
    except Exception:
        pass
    db.query(Alert).filter_by(institution_id=inst_id, is_resolved=False).delete()
    rows = [Alert(institution_id=inst_id, **a) for a in out]
    db.add_all(rows)
    # booking-cutoff reminders (in-app) for students who have not booked yet
    for s in db.query(MealSchedule).filter(MealSchedule.institution_id == inst_id, MealSchedule.is_holiday == False, MealSchedule.cutoff_at > now, MealSchedule.cutoff_at <= now + timedelta(hours=2)):  # noqa
        body = f"Booking for {s.meal_type} on {s.date} closes at {s.cutoff_at:%H:%M}."
        have = {u for (u,) in db.query(Booking.student_id).filter_by(schedule_id=s.id, status="booked")}
        sent = {u for (u,) in db.query(Notification.user_id).filter(Notification.body == body)}
        for (uid,) in db.query(User.id).filter_by(institution_id=inst_id, role="student", is_active=True):
            if uid not in have and uid not in sent:
                notify(db, [uid], "Booking closes soon", body, "/book")
    crit = [a for a in out if a["severity"] == "critical"]
    if crit:
        notify(db, staff_ids(db, inst_id), "Critical alert", crit[0]["title"], "/alerts")
    db.commit()
    return rows
