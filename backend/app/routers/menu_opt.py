"""Module 5 - menu optimisation. Evidence-based suggestions only; managers decide."""
from datetime import timedelta
from itertools import combinations

import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..food_policy import food_is_allowed, is_eligible_menu_item
from ..models import DishPreference, Institution, MenuItem, MenuRecommendation, Rating
from ..security import Ctx, need
from ..services import analytics as A
from ..util import audit, local_now, merged_settings

router = APIRouter(prefix="/menu-opt", tags=["menu-optimisation"])


def compute(db, inst_id, days=90):
    since = local_now().date() - timedelta(days=days)
    df = A.outcome_frame(db, inst_id, since)
    thr = merged_settings(db.get(Institution, inst_id))["waste_alert_pct"]
    if df.empty:
        return [], [], {}
    df["pct"] = df["leftover"] / df["prepared"] * 100
    df["uptake"] = np.where((df["headcount"] > 0), df["consumed"] / (df["headcount"] * df["portion_kg"]), np.nan)
    rat = {i: (float(a), int(n)) for i, a, n in db.query(Rating.menu_item_id, func.avg(Rating.rating), func.count()).group_by(Rating.menu_item_id)}
    like = dict(db.query(DishPreference.menu_item_id, func.count()).filter_by(preference="like").group_by(DishPreference.menu_item_id).all())
    dis = dict(db.query(DishPreference.menu_item_id, func.count()).filter_by(preference="dislike").group_by(DishPreference.menu_item_id).all())
    stats, recs = [], []
    for (iid, name), g in df.groupby(["item_id", "item"]):
        iid = int(iid)
        r = rat.get(iid, (None, 0))
        s = {"item_id": iid, "item": name, "services": int(len(g)), "avg_waste_pct": round(float(g["pct"].mean()), 1),
             "high_waste_share_pct": round(float((g["pct"] > thr).mean() * 100), 1), "avg_uptake": None if g["uptake"].isna().all() else round(float(g["uptake"].mean()), 2),
             "avg_rating": None if r[0] is None else round(r[0], 2), "ratings": r[1], "likes": like.get(iid, 0), "dislikes": dis.get(iid, 0),
             "cost_per_kg": float(g["cost_per_kg"].iloc[0]), "loss": round(float(g["loss"].sum()), 2)}
        stats.append(s)
        if s["services"] < 4:
            continue
        ev = {k: s[k] for k in ("services", "avg_waste_pct", "high_waste_share_pct", "avg_uptake", "avg_rating", "ratings")}
        if s["high_waste_share_pct"] >= 50 and s["avg_uptake"] is not None and s["avg_uptake"] < 0.9:
            cut = round((1 - s["avg_uptake"]) * 100 * 0.6)
            recs.append(("portion", iid, f"{name}: prepared above need in {s['high_waste_share_pct']:.0f}% of {s['services']} services. Average students consume {s['avg_uptake'] * 100:.0f}% of the nominal portion. "
                         f"Consider reducing the planned quantity by about {cut}% and re-check after 2 weeks.", ev))
        if s["avg_rating"] is not None and s["ratings"] >= 8 and s["avg_rating"] < 3.2 and s["avg_waste_pct"] > thr:
            recs.append(("review_dish", iid, f"{name}: low rating ({s['avg_rating']}/5 from {s['ratings']} ratings) together with {s['avg_waste_pct']}% average waste. Consider reviewing the recipe or replacing it, after checking feedback comments.", ev))
        if s["avg_rating"] is not None and s["ratings"] >= 8 and s["avg_rating"] >= 4.2 and s["avg_waste_pct"] < thr / 2:
            recs.append(("popular", iid, f"{name}: well rated ({s['avg_rating']}/5) with low waste ({s['avg_waste_pct']}%). Could be scheduled more often.", ev))
    # menu combinations: pairs served together, compare with overall average waste
    sched = df.groupby("schedule_id").agg(l=("leftover", "sum"), p=("prepared", "sum"))
    sched["pct"] = sched["l"] / sched["p"] * 100
    overall = float(sched["pct"].mean())
    names = df.groupby("schedule_id")["item"].apply(lambda s: sorted(set(s)))
    pair = {}
    for sid, items in names.items():
        for a, b in combinations(items, 2):
            pair.setdefault((a, b), []).append(sched.loc[sid, "pct"])
    combos = [{"pair": f"{a} + {b}", "times": len(v), "avg_waste_pct": round(float(np.mean(v)), 1), "vs_overall_pp": round(float(np.mean(v)) - overall, 1)} for (a, b), v in pair.items() if len(v) >= 4]
    combos.sort(key=lambda c: c["vs_overall_pp"])
    for c in combos[-2:]:
        if c["vs_overall_pp"] >= 3:
            recs.append(("combination", None, f"{c['pair']} served together {c['times']} times with {c['avg_waste_pct']}% waste ({c['vs_overall_pp']} points above the overall {overall:.1f}%). Correlation only - consider testing a different pairing.", c))
    return stats, recs, {"best_combinations": combos[:3], "worst_combinations": combos[-3:][::-1], "overall_meal_waste_pct": round(overall, 1)}


@router.get("/insights")
def insights(days: int = 90, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    stats, recs, extra = compute(db, ctx.inst_id, days)
    cost_rows = sorted(stats, key=lambda s: s["loss"], reverse=True)[:5]
    return {"window_days": days, "dish_stats": sorted(stats, key=lambda s: -s["avg_waste_pct"]), "recommendations": [{"kind": k, "menu_item_id": i, "message": m, "evidence": e} for k, i, m, e in recs],
            "highest_cost_waste": [{"item": s["item"], "loss": s["loss"]} for s in cost_rows], **extra,
            "note": "Suggestions are generated from recorded history and are advisory. Ingredient availability is not modelled."}


@router.post("/generate")
def generate(days: int = 90, ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    _, recs, _ = compute(db, ctx.inst_id, days)
    db.query(MenuRecommendation).filter_by(institution_id=ctx.inst_id).delete()
    for k, i, m, e in recs:
        db.add(MenuRecommendation(institution_id=ctx.inst_id, menu_item_id=i, kind=k, message=m, evidence=e))
    audit(db, ctx.user, "generate_menu_recs", "menu_recommendation", None, str(len(recs))); db.commit()
    return {"saved": len(recs)}


@router.get("/saved")
def saved(ctx: Ctx = Depends(need("mess_admin")), db: Session = Depends(get_db)):
    rows = db.query(MenuRecommendation).filter_by(institution_id=ctx.inst_id).order_by(MenuRecommendation.id.desc())
    out = []
    for recommendation in rows:
        item = db.get(MenuItem, recommendation.menu_item_id) if recommendation.menu_item_id else None
        if recommendation.menu_item_id and not is_eligible_menu_item(item):
            continue
        if not recommendation.menu_item_id and not food_is_allowed(recommendation.message or ""):
            continue
        out.append({"id": recommendation.id, "kind": recommendation.kind, "message": recommendation.message,
                    "evidence": recommendation.evidence, "created_at": recommendation.created_at})
    return out
