"""End-to-end tests. They run against a freshly seeded (synthetic) SQLite database."""
import io
from datetime import timedelta

import pandas as pd
import pytest
from PIL import Image
from sqlalchemy.exc import IntegrityError

from app.models import Attendance, Booking, ConsumptionRecord, MealSchedule, WasteRecord
from app.services import analytics as A
from app.util import local_now, today

PW = "Demo@12345"
TOK, S = {}, {}


@pytest.fixture
def call(client):
    def _call(method, path, who=None, **kw):
        h = kw.pop("headers", {})
        pw = kw.pop("pw", PW)
        if who:
            if who not in TOK:
                r = client.post("/api/auth/login", json={"email": who, "password": pw})
                assert r.status_code == 200, r.text
                TOK[who] = r.json()["access_token"]
            h["Authorization"] = f"Bearer {TOK[who]}"
        return client.request(method, "/api" + path, headers=h, **kw)
    return _call


MGR, KIT, NGO, ADM = "manager@shakambari.demo", "kitchen@shakambari.demo", "ngo@shakambari.demo", "superadmin@shakambari.demo"


# ---------------- authentication & authorisation ----------------
def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_register_login_and_me(call, client):
    inst = call("get", "/auth/institutions").json()[0]["id"]
    S["inst"] = inst
    for i in (1, 2, 3):
        r = call("post", "/auth/register", json={"name": f"Test Student {i}", "email": f"t{i}@x.test", "password": "Passw0rdX", "role": "student", "institution_id": inst})
        assert r.status_code == 201, r.text
    assert call("post", "/auth/register", json={"name": "Dup", "email": "t1@x.test", "password": "Passw0rdX", "role": "student", "institution_id": inst}).status_code == 409
    assert call("post", "/auth/register", json={"name": "Weak", "email": "w@x.test", "password": "short", "role": "student", "institution_id": inst}).status_code == 422
    assert call("post", "/auth/register", json={"name": "Evil", "email": "e@x.test", "password": "Passw0rdX", "role": "super_admin", "institution_id": inst}).status_code == 403
    assert call("post", "/auth/register", json={"name": "Egg eater", "email": "egg@x.test", "password": "Passw0rdX", "role": "student", "institution_id": inst, "diet": "egg"}).status_code == 422
    assert call("post", "/auth/login", json={"email": "t1@x.test", "password": "wrong"}).status_code == 401
    me = call("get", "/auth/me", who="t1@x.test", pw="Passw0rdX").json()
    assert me["role"] == "student" and "password" not in str(me).lower()


def test_password_is_hashed(db):
    from app.models import User
    u = db.query(User).filter_by(email="t1@x.test").first()
    assert u.password_hash.startswith("pbkdf2_sha256$") and "Passw0rdX" not in u.password_hash


def test_protected_routes_and_roles(call):
    assert call("get", "/users").status_code == 401
    assert call("get", "/users", who="t1@x.test").status_code == 403
    assert call("post", "/menu/schedules", who="t1@x.test", json={"date": "2030-01-01", "meal_type": "lunch"}).status_code == 403
    assert call("get", "/waste/summary", who=NGO).status_code == 403
    assert call("post", "/surplus/1/review", who=KIT, json={"decision": "approve", "checklist_confirmed": True}).status_code == 403
    assert call("get", "/admin/overview", who=MGR).status_code == 403
    assert call("get", "/admin/overview", who=ADM).status_code == 200


def test_password_reset(call):
    r = call("post", "/auth/forgot-password", json={"email": "t3@x.test"}).json()
    tok = r["dev_reset_token"]
    assert call("post", "/auth/reset-password", json={"token": tok, "new_password": "NewPass123"}).status_code == 200
    assert call("post", "/auth/reset-password", json={"token": tok, "new_password": "Another123"}).status_code == 400  # single use
    assert call("post", "/auth/login", json={"email": "t3@x.test", "password": "NewPass123"}).status_code == 200
    TOK.pop("t3@x.test", None)


def test_ngo_approval_flow(call):
    inst = S["inst"]
    r = call("post", "/auth/register", json={"name": "Partner", "email": "p@ngo.test", "password": "Passw0rdX", "role": "ngo", "org_name": "Test NGO", "address": "x"})
    assert r.status_code == 201
    assert call("post", "/auth/login", json={"email": "p@ngo.test", "password": "Passw0rdX"}).status_code == 403
    uid = r.json()["id"]
    assert call("post", f"/users/{uid}/approve", who=MGR, json={"approve": True}).status_code == 200
    assert call("post", "/auth/login", json={"email": "p@ngo.test", "password": "Passw0rdX"}).status_code == 200


# ---------------- Module 4: booking -> database ----------------
def test_menu_and_booking_flow(call, db):
    items = call("get", "/menu/items", who=MGR).json()
    rice = next(i for i in items if i["name"] == "Rice")
    r = call("post", "/menu/items", who=MGR, json={"name": "Test Khichdi", "category": "grain", "diet": "veg", "ingredients": ["rice", "lentils", "spices"], "portion_kg": 0.2, "cost_per_kg": 50})
    assert r.status_code == 201; S["khichdi"] = r.json()["id"]; S["rice"] = rice["id"]
    d = (today() + timedelta(days=10)).isoformat()
    r = call("post", "/menu/schedules", who=MGR, json={"date": d, "meal_type": "lunch", "dish_ids": [S["rice"], S["khichdi"]]})
    assert r.status_code == 201, r.text
    sid = S["sid"] = r.json()["id"]
    assert call("post", "/menu/schedules", who=MGR, json={"date": d, "meal_type": "lunch"}).status_code == 409
    for e in ("t1@x.test", "t2@x.test", "t3@x.test"):
        assert call("post", "/bookings", who=e, pw="Passw0rdX" if e != "t3@x.test" else "NewPass123", json={"schedule_id": sid}).status_code == 201
    assert call("post", "/bookings", who="t1@x.test", pw="Passw0rdX", json={"schedule_id": sid}).status_code == 409
    assert db.query(Booking).filter_by(schedule_id=sid, status="booked").count() == 3  # saved in the database
    assert call("delete", f"/bookings/{sid}", who="t3@x.test", json={"reason": "plans"}).status_code == 200
    assert db.query(Booking).filter_by(schedule_id=sid, status="booked").count() == 2
    s = call("get", f"/menu/schedules/{sid}", who="t1@x.test", pw="Passw0rdX").json()
    assert s["active_bookings"] == 2 and s["cancellations"] == 1 and s["my_booking"] == "booked"
    assert call("get", "/bookings/mine", who="t1@x.test", pw="Passw0rdX").json()[0]["schedule_id"] == sid


def test_booking_cutoff_enforced(call):
    t = [s for s in call("get", f"/menu/schedules?start={today()}&end={today()}", who=MGR).json() if s["meal_type"] == "snacks"][0]
    past = (local_now() - timedelta(hours=1)).isoformat()
    r = call("put", f"/menu/schedules/{t['id']}", who=MGR, json={"date": t["date"], "meal_type": "snacks", "dish_ids": [d["id"] for d in t["dishes"]], "cutoff_at": past})
    assert r.status_code == 200
    r = call("post", "/bookings", who="t2@x.test", pw="Passw0rdX", json={"schedule_id": t["id"]})
    assert r.status_code == 400 and "cutoff" in r.json()["detail"].lower()


def test_vegetarian_menu_policy(call, db):
    from sqlalchemy import text
    from app.db import engine
    from app.models import MenuItem

    assert all(item["diet"] in ("veg", "vegan") for item in call("get", "/menu/items", who=MGR).json())
    base = {"category": "curry", "diet": "veg", "ingredients": ["tomato", "spices"], "portion_kg": 0.2, "cost_per_kg": 100}
    for rejected in (
        {**base, "name": "Chicken Curry"},
        {**base, "name": "Garden Curry", "ingredients": ["tomato", "egg"]},
        {**base, "name": "Garden Curry", "diet": "non_veg"},
    ):
        assert call("post", "/menu/items", who=MGR, json=rejected).status_code == 422

    legacy = MenuItem(institution_id=S["inst"], name="Historical Chicken Curry", diet="non_veg", is_active=False,
                      category="curry", ingredients=None, portion_kg=0.2, cost_per_kg=100)
    db.add(legacy); db.commit()
    assert legacy.id not in {item["id"] for item in call("get", "/menu/items", who=MGR).json()}
    d = (today() + timedelta(days=20)).isoformat()
    rejected_schedule = call("post", "/menu/schedules", who=MGR, json={"date": d, "meal_type": "dinner", "dish_ids": [legacy.id]})
    assert rejected_schedule.status_code == 422

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO menu_items (institution_id, name, category, diet, ingredients, portion_kg, cost_per_kg, is_active) "
            "VALUES (:inst, 'Eggplant Curry', 'curry', 'veg', '[\"eggplant\", \"tomato\"]', 0.2, 100, 1)"
        ), {"inst": S["inst"]})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO menu_items (institution_id, name, category, diet, ingredients, portion_kg, cost_per_kg, is_active) "
                "VALUES (:inst, 'Garden Curry', 'curry', 'veg', '[\"chicken\"]', 0.2, 100, 1)"
            ), {"inst": S["inst"]})


def test_attendance_and_participation(call, db):
    sid = S["sid"]
    assert call("post", f"/attendance/{sid}/mark", who=KIT, json={"student_email": "t1@x.test"}).status_code == 201   # booked
    assert call("post", f"/attendance/{sid}/mark", who=KIT, json={"student_email": "t3@x.test"}).json()["was_booked"] is False  # cancelled -> unbooked attendee
    assert call("post", f"/attendance/{sid}/mark", who=KIT, json={"student_email": "t1@x.test"}).status_code == 409
    sm = call("get", f"/bookings/schedule/{sid}/summary", who=MGR).json()
    assert sm["active_bookings"] == 2 and sm["marked_attendance"] == 2 and sm["unbooked_attended"] == 1
    assert call("get", "/bookings/participation", who=MGR).status_code == 200


# ---------------- Module 1: prediction uses booking data ----------------
def test_prediction_uses_bookings(call):
    sid = S["sid"]
    r = call("post", "/predict/run", who=MGR, json={"schedule_ids": [sid]})
    assert r.status_code == 200, r.text
    p = r.json()[0]
    assert p["active_bookings"] == 2 and p["cancellations"] == 1
    assert p["lower"] <= p["predicted_attendance"] <= p["upper"] and p["confidence"] in ("high", "medium", "low")
    eligible_ids = {item["id"] for item in call("get", "/menu/items", who=MGR).json()}
    assert all(d["menu_item_id"] in eligible_ids for d in p["dishes"])
    k = next(d for d in p["dishes"] if d["menu_item_id"] == S["khichdi"])
    assert k["uptake_source"] == "default_assumption"           # no history for a brand-new dish
    assert p["model"]["data_mode"] == "demo"
    assert call("post", "/predict/run", who="t1@x.test", pw="Passw0rdX", json={}).status_code == 403
    plan = call("get", f"/kitchen/plan/{sid}", who=KIT).json()   # manager's recommendation flows to the kitchen
    assert all(d["recommended_kg"] for d in plan["dishes"])
    S["rec"] = {d["menu_item_id"]: d["recommended_kg"] for d in plan["dishes"]}


# ---------------- Module 2: preparation, consumption, waste ----------------
def test_kitchen_validation(call):
    sid = S["sid"]
    bad = call("post", "/kitchen/outcome", who=KIT, json={"schedule_id": sid, "items": [{"menu_item_id": S["rice"], "consumed_qty": 1, "leftover_qty": 1}]})
    assert bad.status_code == 400  # preparation must be recorded first
    assert call("post", "/kitchen/preparation", who=KIT, json={"schedule_id": sid, "items": [{"menu_item_id": 999999, "prepared_qty": 5}]}).status_code == 422


def test_record_outcome_and_waste_math(call):
    sid = S["sid"]; end = (today() + timedelta(days=30)).isoformat(); start = (today() - timedelta(days=200)).isoformat()
    before = call("get", f"/waste/summary?start={start}&end={end}&group=month", who=MGR).json()["totals"]
    assert call("post", f"/attendance/{sid}/headcount", who=KIT, json={"headcount": 120}).json()["headcount"] == 120
    r = call("post", "/kitchen/preparation", who=KIT, json={"schedule_id": sid, "items": [{"menu_item_id": S["rice"], "prepared_qty": 30}, {"menu_item_id": S["khichdi"], "prepared_qty": 20}]})
    assert r.status_code == 200
    over = call("post", "/kitchen/outcome", who=KIT, json={"schedule_id": sid, "items": [{"menu_item_id": S["rice"], "consumed_qty": 40, "leftover_qty": 5}]})
    assert over.status_code == 422
    edible = call("post", "/kitchen/outcome", who=KIT, json={"schedule_id": sid, "items": [{"menu_item_id": S["rice"], "consumed_qty": 25, "leftover_qty": 5, "edible_qty": 9}]})
    assert edible.status_code == 422
    ok = call("post", "/kitchen/outcome", who=KIT, json={"schedule_id": sid, "items": [
        {"menu_item_id": S["rice"], "consumed_qty": 25, "leftover_qty": 5, "edible_qty": 3}, {"menu_item_id": S["khichdi"], "consumed_qty": 15, "leftover_qty": 5, "edible_qty": 2}]})
    assert ok.status_code == 200 and ok.json()["service_status"] == "closed"
    after = call("get", f"/waste/summary?start={start}&end={end}&group=month", who=MGR).json()["totals"]
    assert round(after["prepared"] - before["prepared"], 2) == 50.0
    assert round(after["leftover"] - before["leftover"], 2) == 10.0
    assert round(after["edible"] - before["edible"], 2) == 5.0 and round(after["inedible"] - before["inedible"], 2) == 5.0
    sd = call("get", f"/waste/by-dish?start={start}&end={end}", who=MGR).json()
    k = next(d for d in sd if d["item"] == "Test Khichdi")
    assert k["waste_pct"] == 25.0 and k["consumption_pct"] == 75.0 and k["loss"] == 250.0   # 5/20, 15/20, 5kg x 50
    assert call("get", f"/waste/export.csv?start={start}&end={end}", who=MGR).headers["content-type"].startswith("text/csv")


def test_aggregate_math_unit():
    df = pd.DataFrame({"schedule_id": [1, 1], "g": ["a", "a"], "prepared": [10.0, 10.0], "consumed": [8.0, 6.0], "leftover": [2.0, 4.0], "edible": [1.0, 1.0], "inedible": [1.0, 3.0], "loss": [20.0, 40.0]})
    a = A.aggregate(df, "g").iloc[0]
    assert a["waste_pct"] == pytest.approx(30.0) and a["consumption_pct"] == pytest.approx(70.0) and a["loss"] == 60.0


def test_history_feeds_next_prediction(call):
    sid = S["sid"]
    p = call("post", "/predict/run", who=MGR, json={"schedule_ids": [sid]}).json()[0]
    k = next(d for d in p["dishes"] if d["menu_item_id"] == S["khichdi"])
    assert k["uptake_source"] == "history" and k["uptake"] == pytest.approx(15 / (120 * 0.2), abs=0.001)
    r = call("post", "/predict/retrain", who=MGR)
    assert r.status_code == 200
    t = r.json()["metrics"]["test"]
    assert set(t) == {"mae", "rmse", "r2"}
    m = call("get", "/predict/model", who=MGR).json()
    assert "SYNTHETIC" in m["data_label"] and "chronological" in m["metrics"]["split"]
    assert call("get", "/predict/history", who=MGR).json()["compared"] >= 1


def test_features_have_no_target_leakage(db):
    from app.services.forecast import schedule_frame
    df = schedule_frame(db, S["inst"])
    lunch = df[(df["meal_type"] == "lunch") & df["att"].notna()].sort_values("date")
    r = lunch.iloc[-3]
    prior = lunch[lunch["date"] < r["date"]].tail(7)["att"].mean()
    assert r["roll7"] == pytest.approx(prior)
    assert r["lag1"] == lunch[lunch["date"] < r["date"]].iloc[-1]["att"]


# ---------------- Module 3: redistribution ----------------
def test_surplus_workflow_and_sustainability(call, db):
    sid = S["sid"]
    sug = call("get", "/surplus/suggestions", who=MGR).json()
    assert any(s["schedule_id"] == sid and s["edible_kg"] > 0 for s in sug)      # Module 2 -> 3
    n = local_now()
    body = {"food_name": "Rice", "diet": "vegan", "ingredients": ["rice", "water", "salt"], "category": "cooked", "quantity_kg": 3, "portions": 15, "prepared_at": (n - timedelta(hours=1)).isoformat(), "storage_condition": "hot_held", "storage_temp_c": 65, "use_by": (n + timedelta(hours=6)).isoformat(), "schedule_id": sid, "menu_item_id": S["rice"]}
    assert call("post", "/surplus", who=KIT, json={**body, "food_name": "Chicken Curry"}).status_code == 422
    assert call("post", "/surplus", who=KIT, json={**body, "food_name": "Garden Stew", "menu_item_id": None, "schedule_id": None, "ingredients": ["chicken"]}).status_code == 422
    l = call("post", "/surplus", who=KIT, json=body); assert l.status_code == 201 and l.json()["status"] == "pending_review"
    lid = l.json()["id"]
    bad = call("post", "/surplus", who=KIT, json={**body, "food_name": "Cold hot food", "menu_item_id": None, "schedule_id": None, "storage_temp_c": 40}).json()
    assert bad["status"] == "ineligible"
    assert call("post", "/surplus", who=KIT, json={**body, "prepared_at": (n + timedelta(hours=3)).isoformat()}).status_code == 422
    assert call("post", f"/surplus/{bad['id']}/review", who=MGR, json={"decision": "approve", "checklist_confirmed": True}).status_code == 409
    assert call("post", f"/surplus/{lid}/review", who=MGR, json={"decision": "approve"}).status_code == 422          # needs human checklist
    assert all(x["id"] != lid for x in call("get", "/surplus", who=NGO).json())                                      # not visible until verified
    assert call("post", f"/surplus/{lid}/review", who=MGR, json={"decision": "approve", "checklist_confirmed": True}).json()["status"] == "eligible"
    assert any(x["id"] == lid for x in call("get", "/surplus", who=NGO).json())
    start = (today() - timedelta(days=200)).isoformat(); end = (today() + timedelta(days=30)).isoformat()
    metric = lambda: {m["key"]: m for m in call("get", f"/sustainability/summary?start={start}&end={end}", who=MGR).json()["metrics"]}
    c0 = metric()["collected"]["value"]
    rq = call("post", f"/surplus/{lid}/request", who=NGO, json={"message": "can collect at 8pm"}); assert rq.status_code == 201
    rid = rq.json()["id"]
    assert call("post", f"/surplus/{lid}/request", who=NGO, json={}).status_code == 409
    assert call("post", f"/surplus/requests/{rid}/status", who=NGO, json={"status": "picked_up", "collected_kg": 2}).status_code == 409  # not approved yet
    assert call("post", f"/surplus/requests/{rid}/decision", who=NGO, json={"approve": True}).status_code == 403
    assert call("post", f"/surplus/requests/{rid}/decision", who=MGR, json={"approve": True, "pickup_time": (n + timedelta(hours=2)).isoformat()}).json()["status"] == "approved"
    assert call("post", f"/surplus/requests/{rid}/status", who=NGO, json={"status": "delivered", "delivered_to": "Shelter"}).status_code == 409
    pickup_code = next(r for r in call("get", "/surplus/requests/all", who=NGO).json() if r["id"] == rid)["pickup_code"]
    assert call("post", f"/surplus/requests/{rid}/handover", who=KIT, json={"code": pickup_code, "collected_kg": 9, "portions": 12}).status_code == 422
    assert call("post", f"/surplus/requests/{rid}/handover", who=KIT, json={"code": pickup_code, "collected_kg": 2.5, "portions": 12}).json()["status"] == "picked_up"
    assert call("post", f"/surplus/requests/{rid}/status", who=NGO, json={"status": "delivered", "delivered_to": "Shelter"}).json()["status"] == "delivered"
    assert any(h["food_name"] == "Rice" for h in call("get", "/surplus/donations/history", who=NGO).json())
    m = metric()
    assert round(m["collected"]["value"] - c0, 2) == 2.5                                   # reflected in Module 8
    assert m["collected"]["type"] == "measured" and m["savings"]["type"] == "estimate" and m["co2e_avoided"]["type"] == "estimate" and m["waste_pct"]["type"] == "calculated"


# ---------------- Module 6: image observation ----------------
def _png(color, size=(64, 64)):
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); return b.getvalue()


def test_image_upload_and_correction(call, db):
    sid = S["sid"]
    r = call("post", "/vision/upload", who=KIT, files={"file": ("p.png", _png((230, 190, 40)), "image/png")}, data={"schedule_id": sid, "menu_item_id": S["rice"]})
    assert r.status_code == 201, r.text
    o = r.json(); assert o["predicted_label"] == "dal_gravy" and 0 < o["confidence"] <= 0.95 and "not a food-safety" in o["disclaimer"]
    assert call("post", "/vision/upload", who=KIT, files={"file": ("x.png", b"not an image at all", "image/png")}).status_code == 400
    assert call("post", "/vision/upload", who=KIT, files={"file": ("big.png", b"0" * (6 * 1024 * 1024), "image/png")}).status_code == 413
    assert call("patch", f"/vision/{o['id']}/correct", who=KIT, json={"label": "nonsense"}).status_code == 422
    assert call("patch", f"/vision/{o['id']}/correct", who=KIT, json={"label": "rice"}).json()["final_label"] == "rice"
    n0 = db.query(WasteRecord).filter_by(schedule_id=sid, source="image").count()
    assert call("post", f"/vision/{o['id']}/confirm", who=KIT, json={"quantity_kg": 1.5, "edible_kg": 0.5}).status_code == 200
    assert db.query(WasteRecord).filter_by(schedule_id=sid, source="image").count() == n0 + 1  # Module 6 -> 2
    assert call("get", f"/vision/{o['id']}/image", who=KIT).status_code == 200
    assert call("get", f"/vision/{o['id']}/image", who="t1@x.test", pw="Passw0rdX").status_code == 403


# ---------------- Modules 5, 7 ----------------
def test_menu_optimisation_and_alerts(call):
    ins = call("get", "/menu-opt/insights", who=MGR).json()
    assert ins["dish_stats"] and all("evidence" in r for r in ins["recommendations"])
    assert call("post", "/menu-opt/generate", who=MGR).status_code == 200
    al = call("post", "/alerts/generate", who=MGR).json()
    assert al and all(a["what"] and a["evidence"] and a["why"] and a["action"] for a in al)
    assert call("get", "/alerts", who=KIT).status_code == 200


def test_notifications_and_audit(call):
    n = call("get", "/notifications", who=MGR).json()
    assert n["items"] and n["unread"] >= 1
    assert call("post", "/notifications/read-all", who=MGR).status_code == 200
    assert call("get", "/notifications", who=MGR).json()["unread"] == 0
    assert any(a["action"] == "create_surplus" for a in call("get", "/admin/audit?limit=300", who=MGR).json())


def test_institution_settings_validation(call):
    assert call("put", "/institution", who=MGR, json={"settings": {"booking_cutoff_hours": 500}}).status_code == 422
    assert call("put", "/institution", who=MGR, json={"settings": {"waste_alert_pct": 18}}).json()["settings"]["waste_alert_pct"] == 18
    assert call("put", "/institution", who=KIT, json={"settings": {"waste_alert_pct": 1}}).status_code == 403


def test_api_error_handling(call):
    r = call("get", "/menu/schedules/999999", who=MGR); assert r.status_code == 404 and "detail" in r.json()
    r = call("post", "/bookings", who="t1@x.test", pw="Passw0rdX", json={"schedule_id": "abc"}); assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert call("get", "/nope").status_code == 404
