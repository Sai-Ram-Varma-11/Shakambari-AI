"""Module 1 - demand forecasting. Chronological split, CV-based model selection, no target leakage in features."""
import os
from datetime import timedelta
from typing import List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..config import settings
from ..food_policy import is_eligible_menu_item
from ..models import (MEALS, Booking, Institution, MealSchedule, MenuItem, MLModel, Prediction, PreparationRecord,
                      ScheduleDish)
from ..util import local_now, merged_settings
from .analytics import outcome_frame

MIN_ROWS = 40
FOOD_POLICY_VERSION = 1
FEATURES = ["dow", "is_weekend", "is_holiday", "has_event", "active", "cancellations", "cancel_rate", "lag1", "roll7",
            "same_dow", "hist_ratio", "exp_from_ratio"] + [f"meal_{m}" for m in MEALS]
Z80 = 1.28  # 80% interval multiplier (normal approximation of residuals)


def schedule_frame(db: Session, inst_id: int) -> pd.DataFrame:
    """All schedules with booking aggregates + leak-free historical features (every lag is shift(1) within a meal type)."""
    b = (db.query(Booking.schedule_id.label("sid"), func.sum(case((Booking.status == "booked", 1), else_=0)).label("a"),
                  func.count().label("t")).group_by(Booking.schedule_id).subquery())
    S = MealSchedule
    rows = (db.query(S.id, S.date, S.meal_type, S.is_holiday, S.event, S.headcount, b.c.a, b.c.t)
            .outerjoin(b, b.c.sid == S.id).filter(S.institution_id == inst_id).all())
    schedule_ids = [r[0] for r in rows]
    dishes = db.query(ScheduleDish.schedule_id, MenuItem).join(
        MenuItem, MenuItem.id == ScheduleDish.menu_item_id
    ).filter(ScheduleDish.schedule_id.in_(schedule_ids)).all() if schedule_ids else []
    dish_status = {}
    for schedule_id, item in dishes:
        has_dish, all_eligible = dish_status.get(schedule_id, (False, True))
        dish_status[schedule_id] = (True, all_eligible and is_eligible_menu_item(item))
    rows = [r for r in rows if dish_status.get(r[0], (False, False))[0] and dish_status[r[0]][1]]
    df = pd.DataFrame([tuple(r) for r in rows], columns=["id", "date", "meal_type", "is_holiday", "event", "headcount", "active", "total"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["active"] = pd.to_numeric(df["active"]).fillna(0).astype(float)
    df["cancellations"] = pd.to_numeric(df["total"]).fillna(0).astype(float) - df["active"]
    df["cancel_rate"] = np.where(df["active"] + df["cancellations"] > 0, df["cancellations"] / (df["active"] + df["cancellations"]), 0.0)
    df["att"] = pd.to_numeric(df["headcount"], errors="coerce").astype(float)
    df["dow"] = df["date"].dt.day_of_week
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["is_holiday"] = df["is_holiday"].astype(bool).astype(int)
    df["has_event"] = df["event"].apply(lambda x: 0 if x is None or (isinstance(x, float) and np.isnan(x)) or x == "" else 1)
    df = df.sort_values(["meal_type", "date"]).reset_index(drop=True)
    g = df.groupby("meal_type")["att"]
    df["lag1"] = g.shift(1)
    df["roll7"] = g.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
    df["same_dow"] = df.groupby(["meal_type", "dow"])["att"].shift(1)
    df["_ratio"] = df["att"] / df["active"].replace(0, np.nan)
    df["hist_ratio"] = df.groupby("meal_type")["_ratio"].transform(lambda s: s.shift(1).rolling(14, min_periods=1).mean())
    known = df["att"].dropna()
    fallback = df.groupby("meal_type")["att"].transform("mean").fillna(known.mean() if len(known) else 0.0)
    df["roll7"] = df["roll7"].fillna(fallback)
    df["lag1"] = df["lag1"].fillna(df["roll7"])
    df["same_dow"] = df["same_dow"].fillna(df["roll7"])
    df["hist_ratio"] = df["hist_ratio"].fillna(df["_ratio"].median() if df["_ratio"].notna().any() else 1.0)
    df["exp_from_ratio"] = df["active"] * df["hist_ratio"]
    for m in MEALS:
        df[f"meal_{m}"] = (df["meal_type"] == m).astype(int)
    return df.sort_values(["date", "meal_type"]).reset_index(drop=True)


def _metrics(y, p):
    return {"mae": round(float(mean_absolute_error(y, p)), 2), "rmse": round(float(np.sqrt(mean_squared_error(y, p))), 2),
            "r2": round(float(r2_score(y, p)), 3)}


def _candidates():
    return {"linear_regression": make_pipeline(StandardScaler(), LinearRegression()),
            "random_forest": RandomForestRegressor(n_estimators=150, min_samples_leaf=3, random_state=0, n_jobs=1),
            "gradient_boosting": GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0)}


BASELINES = {"baseline_roll7": "roll7", "baseline_bookings_x_hist_ratio": "exp_from_ratio"}


def train(db: Session, inst_id: int) -> MLModel:
    inst = db.get(Institution, inst_id)
    df = schedule_frame(db, inst_id)
    lab = df[df["att"].notna()].sort_values("date").reset_index(drop=True) if not df.empty else df
    db.query(MLModel).filter_by(institution_id=inst_id, is_active=True).update({"is_active": False})
    if len(lab) < MIN_ROWS:
        m = MLModel(institution_id=inst_id, algorithm="baseline_recent_mean", features=["roll7"], n_train=len(lab), n_test=0,
                    metrics={"food_policy_version": FOOD_POLICY_VERSION,
                             "note": f"Only {len(lab)} completed meals recorded (need {MIN_ROWS}). Using a recent-average baseline; no accuracy metrics are reported."},
                    data_mode=inst.data_mode)
        db.add(m); db.commit()
        return m
    dates = sorted(lab["date"].unique())
    cut = dates[int(len(dates) * 0.8)]
    tr, te = lab[lab["date"] < cut], lab[lab["date"] >= cut]
    if len(tr) < 30 or len(te) < 8:
        k = int(len(lab) * 0.8); tr, te = lab.iloc[:k], lab.iloc[k:]
    cv = TimeSeriesSplit(n_splits=3)
    res = {}
    for name, col in BASELINES.items():
        rm = [np.sqrt(mean_squared_error(tr.iloc[v]["att"], tr.iloc[v][col])) for _, v in cv.split(tr)]
        res[name] = {"cv_rmse": round(float(np.mean(rm)), 2), "test": _metrics(te["att"], te[col])}
    fitted = {}
    for name, est in _candidates().items():
        rm = []
        for a, v in cv.split(tr):
            est.fit(tr.iloc[a][FEATURES], tr.iloc[a]["att"])
            rm.append(np.sqrt(mean_squared_error(tr.iloc[v]["att"], est.predict(tr.iloc[v][FEATURES]))))
        est.fit(tr[FEATURES], tr["att"]); fitted[name] = est
        res[name] = {"cv_rmse": round(float(np.mean(rm)), 2), "test": _metrics(te["att"], est.predict(te[FEATURES]))}
    best = min(res, key=lambda k: res[k]["cv_rmse"])  # selected on training-period CV only; test set untouched
    if best in BASELINES:
        p_te = te[BASELINES[best]].values
        final, joblib_obj = None, None
    else:
        p_te = fitted[best].predict(te[FEATURES])
        final = _candidates()[best].fit(lab[FEATURES], lab["att"])  # refit on all labelled history for deployment
    sd = float(np.std(te["att"].values - p_te, ddof=1)) if len(te) > 2 else 0.1 * float(lab["att"].mean())
    os.makedirs(settings.model_dir, exist_ok=True)
    path = os.path.join(settings.model_dir, f"inst{inst_id}_{local_now():%Y%m%d%H%M%S}.joblib")
    joblib.dump({"model": final, "algo": best, "resid_std": sd, "features": FEATURES}, path)
    back = [{"date": d.strftime("%Y-%m-%d"), "meal_type": m, "actual": float(a), "predicted": round(float(p), 1)}
            for d, m, a, p in zip(te["date"], te["meal_type"], te["att"], p_te)][-60:]
    meta = MLModel(institution_id=inst_id, algorithm=best, features=FEATURES, n_train=len(tr), n_test=len(te), path=path, data_mode=inst.data_mode,
                   metrics={"food_policy_version": FOOD_POLICY_VERSION, "selected": best, "selection": "lowest time-series CV RMSE on the training period",
                            "test": res[best]["test"], "candidates": res, "residual_std": round(sd, 2),
                            "split": f"chronological: train < {pd.Timestamp(cut):%Y-%m-%d} <= test", "backtest": back,
                            "note": "Test metrics come from a model fitted on the training period only; the deployed model is refit on all labelled history."})
    db.add(meta); db.commit()
    return meta


def active_model(db, inst_id) -> MLModel:
    m = db.query(MLModel).filter_by(institution_id=inst_id, is_active=True).order_by(MLModel.id.desc()).first()
    if m and (m.metrics or {}).get("food_policy_version") == FOOD_POLICY_VERSION:
        return m
    return train(db, inst_id)


def maybe_retrain(db: Session, inst_id: int, every: int = 14) -> bool:
    m = active_model(db, inst_id)
    clean = schedule_frame(db, inst_id)
    n = int(clean["att"].notna().sum()) if not clean.empty else 0
    if m is None or n - (m.n_train + m.n_test) >= every:
        train(db, inst_id)
        return True
    return False


def uptake_table(db, inst_id):
    """Per-dish historical share of the 'nominal' portion actually consumed (consumed / (attendance x portion))."""
    df = outcome_frame(db, inst_id)
    if df.empty:
        return {}
    df = df[df["headcount"] > 0].copy()
    df["u"] = df["consumed"] / (df["headcount"] * df["portion_kg"])
    out = {}
    for iid, g in df.groupby("item_id"):
        out[int(iid)] = (float(np.clip(g["u"].mean(), 0.05, 1.5)), int(len(g)))
    return out


def predict_schedules(db: Session, inst_id: int, schedule_ids: List[int], persist: bool = True) -> list:
    meta = active_model(db, inst_id)
    cfg = merged_settings(db.get(Institution, inst_id))
    df = schedule_frame(db, inst_id)
    rows = df[df["id"].isin(schedule_ids)]
    bundle = joblib.load(meta.path) if meta.path and os.path.exists(meta.path) else None
    uptake = uptake_table(db, inst_id)
    out = []
    for _, r in rows.iterrows():
        x = r[FEATURES].to_frame().T.astype(float)
        if bundle and bundle["model"] is not None:
            p, sd = float(bundle["model"].predict(x)[0]), bundle["resid_std"]
        elif bundle:
            p, sd = float(r[BASELINES[bundle["algo"]]]), bundle["resid_std"]
        else:
            p, sd = float(r["roll7"]), 0.2 * float(r["roll7"])
        if r["is_holiday"] and not bundle:
            p = 0.0
        p = max(p, 0.0); lo, hi = max(p - Z80 * sd, 0.0), p + Z80 * sd
        rel = (hi - lo) / max(p, 1.0)
        conf = "high" if rel < 0.2 else "medium" if rel < 0.4 else "low"
        sid = int(r["id"])
        s = db.get(MealSchedule, sid)
        dishes = []
        for it in db.query(MenuItem).join(ScheduleDish, ScheduleDish.menu_item_id == MenuItem.id).filter(
            ScheduleDish.schedule_id == sid, MenuItem.is_active.is_(True), MenuItem.diet.in_(("veg", "vegan"))
        ):
            if not is_eligible_menu_item(it):
                continue
            u, n = uptake.get(it.id, (0.85, 0))
            exp_cons = p * it.portion_kg * u
            rec = exp_cons * (1 + cfg["prep_buffer_pct"] / 100)
            prep = db.query(PreparationRecord).filter_by(schedule_id=sid, menu_item_id=it.id).first()
            d = {"menu_item_id": it.id, "name": it.name, "portion_kg": it.portion_kg, "uptake": round(u, 3), "uptake_n": n,
                 "uptake_source": "history" if n else "default_assumption", "expected_consumption_kg": round(exp_cons, 2),
                 "recommended_kg": round(rec, 2), "lower_kg": round(lo * it.portion_kg * u, 2), "upper_kg": round(hi * it.portion_kg * u * (1 + cfg["prep_buffer_pct"] / 100), 2),
                 "prepared_kg": prep.prepared_qty if prep else None}
            if prep:
                diff = prep.prepared_qty - exp_cons
                d["expected_surplus_kg"] = round(diff, 2)
                d["status"] = "shortage_risk" if prep.prepared_qty < d["lower_kg"] else "surplus_risk" if prep.prepared_qty > d["upper_kg"] else "within_range"
            dishes.append(d)
        item = {"schedule_id": sid, "date": r["date"].strftime("%Y-%m-%d"), "meal_type": r["meal_type"], "is_holiday": bool(r["is_holiday"]),
                "predicted_attendance": round(p), "lower": round(lo), "upper": round(hi), "confidence": conf, "active_bookings": int(r["active"]),
                "cancellations": int(r["cancellations"]), "historical_attendance_per_booking": round(float(r["hist_ratio"]), 2),
                "actual_attendance": None if pd.isna(r["att"]) else int(r["att"]),
                "model": {"id": meta.id, "algorithm": meta.algorithm, "data_mode": meta.data_mode, "metrics": (meta.metrics or {}).get("test")},
                "dishes": dishes}
        if persist:
            db.add(Prediction(schedule_id=sid, kind="attendance", value=p, lower=lo, upper=hi, active_bookings=int(r["active"]), model_id=meta.id))
            for d in dishes:
                db.add(Prediction(schedule_id=sid, menu_item_id=d["menu_item_id"], kind="dish", value=d["recommended_kg"], lower=d["lower_kg"],
                                  upper=d["upper_kg"], active_bookings=int(r["active"]), model_id=meta.id))
        out.append(item)
    if persist:
        db.commit()
    return sorted(out, key=lambda z: (z["date"], MEALS.index(z["meal_type"])))


def latest_dish_reco(db, schedule_id):
    out = {}
    rows = db.query(Prediction, MenuItem).join(MenuItem, MenuItem.id == Prediction.menu_item_id).filter(
        Prediction.schedule_id == schedule_id, Prediction.kind == "dish"
    ).order_by(Prediction.id)
    for p, item in rows:
        if is_eligible_menu_item(item):
            out[p.menu_item_id] = p.value
    return out
