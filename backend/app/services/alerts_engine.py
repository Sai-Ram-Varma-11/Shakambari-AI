"""Module 7 - rule-based, explainable alerts. Every alert states what / evidence / why / action and uses only recorded data."""
from datetime import datetime, timedelta
from typing import Dict, List, Set

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..models import (
    Alert,
    Booking,
    Institution,
    MealSchedule,
    Notification,
    RedistributionRequest,
    SurplusListing,
    User,
)
from ..util import local_now, merged_settings, notify, staff_ids
from . import analytics as A
from . import forecast


def generate(db: Session, inst_id: int):
    inst = db.get(Institution, inst_id)
    if not inst:
        return []
    cfg = merged_settings(inst)
    thr = cfg.get("waste_alert_pct", 15)
    now = local_now()
    alerts_data: List[dict] = []

    def add(fingerprint, kind, sev, title, what, ev, why, action):
        alerts_data.append({
            "fingerprint": fingerprint,
            "kind": kind,
            "severity": sev,
            "title": title,
            "what": what,
            "evidence": ev,
            "why": why,
            "action": action,
        })

    # 1. Historical waste trends
    df = A.outcome_frame(db, inst_id, now.date() - timedelta(days=120))
    if not df.empty:
        daily = A.aggregate(A.with_period(df, "day"), "period")
        daily["date"] = pd.to_datetime(daily["period"])
        daily = daily.sort_values("date")
        last = daily.iloc[-1]
        prev = daily[(daily["date"].dt.day_of_week == last["date"].day_of_week) & (daily["date"] < last["date"])].tail(4)
        if len(prev) >= 3 and last["waste_pct"] > prev["waste_pct"].mean() + 5:
            wd = last["date"].strftime("%A")
            fp = f"waste_increase:{last['date'].strftime('%Y-%m-%d')}"
            add(
                fp,
                "waste_increase",
                "warning",
                f"Food waste higher than previous {wd}s",
                f"Waste on {last['date']:%d %b} was {last['waste_pct']:.1f}% of prepared food.",
                f"Average of the previous {len(prev)} {wd}s: {prev['waste_pct'].mean():.1f}% (recorded kitchen data).",
                "A sustained rise means over-preparation is costing money and food.",
                "Check that day's preparation quantities against attendance and review the dishes with the most leftovers.",
            )

        for (iid, name), g in df.sort_values("date").groupby(["item_id", "item"]):
            g = g.tail(7)
            hi = int(((g["leftover"] / g["prepared"] * 100) > thr).sum())
            if len(g) >= 5 and hi >= 3:
                fp = f"dish_high_leftover:{iid}"
                add(
                    fp,
                    "dish_high_leftover",
                    "warning",
                    f"{name}: repeated high leftovers",
                    f"{name} exceeded the {thr}% waste threshold in {hi} of its last {len(g)} services.",
                    f"Average leftover {g['leftover'].mean():.1f} kg per service; average waste {(g['leftover'].sum() / g['prepared'].sum() * 100):.1f}%.",
                    "Repeated surplus of one dish suggests its portion/quantity assumption is too high or it is unpopular.",
                    "Reduce its planned quantity or review it in Menu Optimisation.",
                )

    # 2. Upcoming schedule forecasts vs bookings
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
            sid = int(r["id"])
            if len(same) >= 3:
                usual_b = same["active"].mean()
                if usual_b > 10 and r["active"] < 0.7 * usual_b:
                    add(
                        f"low_bookings:{sid}",
                        "low_bookings",
                        "warning",
                        f"Bookings low for {label}",
                        f"{int(r['active'])} active bookings so far.",
                        f"The previous {len(same)} similar meals had {usual_b:.0f} bookings on average.",
                        "Preparing from bookings alone could cause shortages if students arrive unbooked, or surplus if the low count is real.",
                        "Wait for the cutoff, then rely on the demand forecast rather than raw bookings.",
                    )
                if sid in preds:
                    p = preds[sid]
                    usual_a = same["att"].mean()
                    if p["predicted_attendance"] < 0.85 * usual_a:
                        add(
                            f"low_demand:{sid}",
                            "low_demand",
                            "info",
                            f"Lower demand predicted for {label}",
                            f"Forecast {p['predicted_attendance']} students (80% range {p['lower']}-{p['upper']}).",
                            f"Usual attendance for this meal and weekday: {usual_a:.0f} (last {len(same)} occurrences).",
                            "Preparing the usual quantity would likely leave surplus.",
                            "Scale preparation to the recommendation in Demand Prediction.",
                        )
            if sid in preds:
                for d in preds[sid].get("dishes", []):
                    if d.get("status") in ("surplus_risk", "shortage_risk"):
                        add(
                            f"prep_vs_prediction:{sid}:{d.get('dish_id', d['name'])}",
                            "prep_vs_prediction",
                            "warning",
                            f"Preparation vs forecast: {d['name']} ({label})",
                            f"Prepared {d['prepared_kg']} kg; recommended {d['recommended_kg']} kg.",
                            f"Forecast range for this dish: {d['lower_kg']}-{d['upper_kg']} kg.",
                            "Quantity outside the forecast range signals likely " + ("surplus." if d["status"] == "surplus_risk" else "shortage."),
                            "Review the quantity before cooking completes.",
                        )

    # 3. Surplus and redistribution status
    pend = db.query(SurplusListing).filter_by(institution_id=inst_id, status="pending_review").count()
    elig = db.query(SurplusListing).filter_by(institution_id=inst_id, status="eligible").count()
    reqs = (
        db.query(RedistributionRequest)
        .join(SurplusListing, SurplusListing.id == RedistributionRequest.listing_id)
        .filter(SurplusListing.institution_id == inst_id, RedistributionRequest.status == "pending")
        .count()
    )
    if pend:
        add(
            "surplus_review:pending",
            "surplus_review",
            "warning",
            "Surplus listings need food-safety review",
            f"{pend} listing(s) are waiting for review.",
            "Status 'pending_review' in Surplus Management.",
            "Time-sensitive: food must be collected within the safe holding window.",
            "Review and approve or reject them promptly.",
        )
    if elig:
        add(
            "surplus_awaiting:unclaimed",
            "surplus_awaiting",
            "info",
            "Eligible surplus awaiting collection",
            f"{elig} verified listing(s) have not been requested yet.",
            "Status 'eligible' with no approved request.",
            "Unclaimed surplus becomes ineligible as time passes.",
            "Contact verified partners or withdraw the listing.",
        )
    if reqs:
        add(
            "requests_pending:unanswered",
            "requests_pending",
            "warning",
            "Collection requests awaiting your decision",
            f"{reqs} request(s) are pending.",
            "Redistribution requests in 'pending' state.",
            "Partners are waiting to plan pickup.",
            "Approve one request and set a pickup time.",
        )

    # 4. Menu pairing optimization alert
    try:
        from ..routers.menu_opt import compute
        _, _, extra = compute(db, inst_id, 90)
        for c in extra.get("worst_combinations", [])[:1]:
            if c["vs_overall_pp"] >= 4:
                add(
                    f"combo_waste:{c['pair']}",
                    "combo_waste",
                    "info",
                    "A menu combination is linked to higher waste",
                    f"{c['pair']} served together {c['times']} times: {c['avg_waste_pct']}% waste.",
                    f"{c['vs_overall_pp']} points above the overall meal average.",
                    "Association only; other factors (weekday, event) may explain it.",
                    "Try an alternative pairing for a few weeks and compare.",
                )
    except Exception:
        pass

    # STABLE FINGERPRINT PERSISTENCE LOGIC
    # Rather than deleting all unresolved alerts, update existing ones, insert new ones, and auto-resolve stale ones.
    existing_unresolved = {
        a.fingerprint: a
        for a in db.query(Alert).filter_by(institution_id=inst_id, is_resolved=False).all()
        if a.fingerprint
    }
    active_fingerprints: Set[str] = set()
    result_alerts: List[Alert] = []

    for alert_dict in alerts_data:
        fp = alert_dict["fingerprint"]
        active_fingerprints.add(fp)
        if fp in existing_unresolved:
            existing = existing_unresolved[fp]
            existing.title = alert_dict["title"]
            existing.what = alert_dict["what"]
            existing.evidence = alert_dict["evidence"]
            existing.why = alert_dict["why"]
            existing.action = alert_dict["action"]
            existing.severity = alert_dict["severity"]
            existing.updated_at = now
            result_alerts.append(existing)
        else:
            new_alert = Alert(
                institution_id=inst_id,
                created_at=now,
                updated_at=now,
                is_resolved=False,
                **alert_dict,
            )
            db.add(new_alert)
            result_alerts.append(new_alert)

    # Auto-resolve stale alerts that no longer trigger
    for fp, stale_alert in existing_unresolved.items():
        if fp not in active_fingerprints:
            stale_alert.is_resolved = True
            stale_alert.resolved_at = now
            stale_alert.updated_at = now

    # Booking cutoff reminders with dedicated dedup_key
    cutoff_horizon = now + timedelta(hours=2)
    schedules_closing = (
        db.query(MealSchedule)
        .filter(
            MealSchedule.institution_id == inst_id,
            MealSchedule.is_holiday == False,  # noqa
            MealSchedule.cutoff_at > now,
            MealSchedule.cutoff_at <= cutoff_horizon,
        )
        .all()
    )
    for s in schedules_closing:
        body = f"Booking for {s.meal_type} on {s.date} closes at {s.cutoff_at:%H:%M}."
        have_booked = {u for (u,) in db.query(Booking.student_id).filter_by(schedule_id=s.id, status="booked")}
        students = [uid for (uid,) in db.query(User.id).filter_by(institution_id=inst_id, role="student", is_active=True) if uid not in have_booked]
        if students:
            notify(
                db,
                students,
                "Booking closes soon",
                body,
                "/book",
                dedup_key=f"cutoff_reminder:{s.id}",
            )

    crit = [a for a in alerts_data if a["severity"] == "critical"]
    if crit:
        notify(
            db,
            staff_ids(db, inst_id),
            "Critical alert",
            crit[0]["title"],
            "/alerts",
            dedup_key=f"crit_alert:{crit[0]['fingerprint']}",
        )

    db.commit()
    return result_alerts
