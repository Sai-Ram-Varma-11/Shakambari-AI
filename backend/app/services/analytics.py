"""Shared analytics over preparation / consumption / waste records (Module 2). Feeds Modules 1, 5, 7, 8."""
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..models import ConsumptionRecord, MealSchedule, MenuItem, PreparationRecord, WasteRecord

COLS = ["schedule_id", "date", "meal_type", "headcount", "item_id", "item", "cost_per_kg", "portion_kg",
        "prepared", "consumed", "leftover", "edible", "inedible"]


def outcome_frame(db: Session, inst_id: int, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
    """One row per (meal, dish) that has BOTH preparation and consumption recorded."""
    w = (db.query(WasteRecord.schedule_id.label("sid"), WasteRecord.menu_item_id.label("mid"),
                  func.sum(WasteRecord.leftover_qty).label("l"), func.sum(WasteRecord.edible_qty).label("e"),
                  func.sum(WasteRecord.inedible_qty).label("i"))
         .group_by(WasteRecord.schedule_id, WasteRecord.menu_item_id).subquery())
    P, C, S, M = PreparationRecord, ConsumptionRecord, MealSchedule, MenuItem
    q = (db.query(S.id, S.date, S.meal_type, S.headcount, M.id, M.name, M.cost_per_kg, M.portion_kg, P.prepared_qty,
                  C.consumed_qty, w.c.l, w.c.e, w.c.i)
         .select_from(P).join(S, S.id == P.schedule_id).join(M, M.id == P.menu_item_id)
         .join(C, and_(C.schedule_id == P.schedule_id, C.menu_item_id == P.menu_item_id))
         .outerjoin(w, and_(w.c.sid == P.schedule_id, w.c.mid == P.menu_item_id))
         .filter(S.institution_id == inst_id, M.is_active.is_(True), M.diet.in_(("veg", "vegan"))))
    if start:
        q = q.filter(S.date >= start)
    if end:
        q = q.filter(S.date <= end)
    df = pd.DataFrame([tuple(r) for r in q.all()], columns=COLS)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    for c in ("prepared", "consumed", "leftover", "edible", "inedible", "headcount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["leftover"] = df["leftover"].fillna((df["prepared"] - df["consumed"]).clip(lower=0))
    df["edible"] = df["edible"].fillna(0.0)
    df["inedible"] = df["inedible"].fillna(df["leftover"] - df["edible"])
    df["loss"] = df["leftover"] * df["cost_per_kg"]
    return df


def aggregate(df: pd.DataFrame, by) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(by, as_index=False).agg(prepared=("prepared", "sum"), consumed=("consumed", "sum"),
                                           leftover=("leftover", "sum"), edible=("edible", "sum"),
                                           inedible=("inedible", "sum"), loss=("loss", "sum"), services=("schedule_id", "nunique"))
    g["waste_pct"] = np.where(g["prepared"] > 0, g["leftover"] / g["prepared"] * 100, 0.0)
    g["consumption_pct"] = np.where(g["prepared"] > 0, g["consumed"] / g["prepared"] * 100, 0.0)
    return g


def records(df: pd.DataFrame, nd=2):
    """JSON-safe list of dicts (NaN -> None, dates -> str)."""
    if df.empty:
        return []
    out = df.copy()
    for c in out.columns:
        if str(out[c].dtype).startswith("datetime"):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    out = out.round(nd).astype(object).where(pd.notnull(out), None)
    return out.to_dict("records")


PERIOD_FMT = {"day": "%Y-%m-%d", "week": "%G-W%V", "month": "%Y-%m", "year": "%Y"}


def with_period(df: pd.DataFrame, group: str) -> pd.DataFrame:
    df = df.copy()
    df["period"] = df["date"].dt.strftime(PERIOD_FMT.get(group, "%Y-%m-%d"))
    return df
