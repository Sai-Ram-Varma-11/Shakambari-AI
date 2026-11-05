"""Seed SYNTHETIC demonstration data. Nothing here is real institutional data.
Usage: python -m app.seed --reset [--students 200] [--days 60]"""
import argparse, random
from datetime import datetime, timedelta

import numpy as np

from .config import settings
from .db import Base, SessionLocal, engine
from .models import *  # noqa
from .security import hash_password
from .util import DEFAULT_SETTINGS, default_cutoff, local_now, meal_start, today

DISHES = {  # name: (category, diet, portion_kg, cost_per_kg, uptake, over_prep, popularity)
    "Rice": ("grain", "veg", .20, 45, .92, 1.08, 3.9), "Dal": ("dal", "veg", .15, 70, .95, 1.08, 4.0), "Chapati": ("bread", "veg", .09, 55, .97, 1.08, 4.1),
    "Sambar": ("dal", "veg", .15, 60, .55, 1.25, 3.1), "Paneer Curry": ("curry", "veg", .12, 260, .88, 1.08, 4.4), "Mixed Veg": ("vegetable", "veg", .12, 90, .60, 1.25, 3.0),
    "Egg Curry": ("curry", "egg", .12, 140, .85, 1.08, 3.9), "Chicken Curry": ("curry", "non_veg", .14, 320, .93, 1.08, 4.5), "Veg Biryani": ("grain", "veg", .30, 120, .90, 1.08, 4.2),
    "Chicken Biryani": ("grain", "non_veg", .32, 230, .96, 1.08, 4.7), "Idli": ("breakfast", "veg", .15, 80, .90, 1.08, 4.0), "Dosa": ("breakfast", "veg", .10, 90, .93, 1.08, 4.3),
    "Upma": ("breakfast", "veg", .15, 60, .70, 1.15, 3.2), "Poha": ("breakfast", "veg", .15, 65, .50, 1.25, 2.9), "Curd": ("dairy", "veg", .10, 70, .65, 1.15, 3.6),
    "Samosa": ("snack", "veg", .08, 110, .92, 1.08, 4.2), "Veg Puff": ("snack", "veg", .08, 100, .80, 1.1, 3.8), "Tea": ("beverage", "veg", .15, 40, .95, 1.08, 4.0),
    "Salad": ("vegetable", "veg", .06, 50, .45, 1.25, 2.8)}
MENU = {
    "breakfast": {0: ["Idli", "Sambar"], 1: ["Dosa", "Sambar"], 2: ["Upma"], 3: ["Poha"], 4: ["Idli", "Sambar"], 5: ["Dosa", "Sambar"], 6: ["Poha"]},
    "lunch": {0: ["Rice", "Dal", "Chapati", "Paneer Curry"], 1: ["Rice", "Dal", "Chapati", "Mixed Veg", "Curd"], 2: ["Rice", "Dal", "Chapati", "Egg Curry"], 3: ["Rice", "Dal", "Chapati", "Mixed Veg"],
              4: ["Rice", "Dal", "Chapati", "Paneer Curry", "Curd"], 5: ["Rice", "Dal", "Chapati", "Chicken Curry"], 6: ["Veg Biryani", "Dal", "Curd"]},
    "snacks": {d: (["Samosa", "Tea"] if d % 2 == 0 else ["Veg Puff", "Tea"]) for d in range(7)},
    "dinner": {0: ["Chapati", "Mixed Veg", "Rice"], 1: ["Chapati", "Paneer Curry", "Rice"], 2: ["Chapati", "Chicken Curry", "Rice"], 3: ["Chapati", "Egg Curry", "Rice"],
               4: ["Veg Biryani", "Curd", "Salad"], 5: ["Chapati", "Mixed Veg", "Dal"], 6: ["Chicken Biryani", "Salad"]}}
FIRST = "Aarav Vivaan Aditya Arjun Sai Reyansh Ayaan Krishna Ishaan Rohan Ananya Diya Aadhya Saanvi Kavya Meera Riya Isha Priya Neha Kiran Varun Teja Harsha Lakshmi Sneha Pooja Ravi Suresh Manoj".split()
LAST = "Sharma Reddy Naidu Varma Kumar Singh Patel Gupta Rao Chowdary Iyer Nair Das Mehta Joshi".split()
COMMENTS = ["Too oily", "Needed more salt", "Really good today", "Cold when served", "Portion was small", "Tasty!", "Too spicy"]


def run(n_students=200, days_back=60, reset=True, seed=42, train_model=True, quiet=False):
    rng, rnd = np.random.default_rng(seed), random.Random(seed)
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.query(Institution).count():
        raise SystemExit("Database already has data. Re-run with --reset to wipe and reseed.")
    cfg = DEFAULT_SETTINGS
    inst = Institution(name="Demo University Mess (SYNTHETIC DEMO DATA)", code="DEMO", data_mode="demo", settings={"currency": "INR"}); db.add(inst); db.flush()
    pw = hash_password(settings.seed_demo_password)
    mk = lambda email, name, role, **k: (db.add(User(email=email, name=name, role=role, password_hash=pw, **k)), db.flush())
    sa = User(email="superadmin@platesense.demo", name="Platform Admin", role="super_admin", password_hash=pw, institution_id=inst.id)
    mg = User(email="manager@platesense.demo", name="Mess Manager", role="mess_admin", password_hash=pw, institution_id=inst.id)
    kt = User(email="kitchen@platesense.demo", name="Kitchen Lead", role="kitchen", password_hash=pw, institution_id=inst.id)
    n1 = User(email="ngo@platesense.demo", name="Asha Volunteer", role="ngo", password_hash=pw, is_approved=True)
    n2 = User(email="ngo.pending@platesense.demo", name="New Partner", role="ngo", password_hash=pw, is_approved=False)
    db.add_all([sa, mg, kt, n1, n2]); db.flush()
    db.add_all([NGOPartner(user_id=n1.id, org_name="Annapurna Food Bank (demo)", registration_no="DEMO-0001", address="Demo address", verified=True, verified_by=mg.id, verified_at=local_now()),
                NGOPartner(user_id=n2.id, org_name="Hope Kitchen (demo, pending)", registration_no="DEMO-0002", verified=False)])
    students = []
    for i in range(n_students):
        students.append(User(email=f"student{i + 1:03d}@students.platesense.demo", name=f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", role="student", password_hash=pw, institution_id=inst.id))
    db.add_all(students); db.flush()
    db.add_all([StudentProfile(user_id=s.id, diet=rnd.choices(["veg", "non_veg", "egg"], [.45, .4, .15])[0], hostel=f"Block {rnd.choice('ABCD')}") for s in students])
    items = {}
    for n, (c, d, p, cost, *_r) in DISHES.items():
        it = MenuItem(institution_id=inst.id, name=n, category=c, diet=d, portion_kg=p, cost_per_kg=cost); db.add(it); items[n] = it
    db.flush()
    sids = [s.id for s in students]
    for sid in sids:  # preferences
        for n in rnd.sample(list(DISHES), 3):
            db.add(DishPreference(student_id=sid, menu_item_id=items[n].id, preference="like" if rnd.random() < .66 else "dislike"))
    book_p, taste = rng.beta(5, 2, n_students), rng.uniform(.8, 1.1, n_students)
    t0 = today()
    holidays = {t0 - timedelta(days=int(days_back * .7)), t0 - timedelta(days=int(days_back * .3))}
    events = {t0 - timedelta(days=int(days_back * f)): n for f, n in ((.9, "Annual Day Feast"), (.55, "Sports Meet"), (.2, "Cultural Fest"))}
    bk, cn, at, bid = [], [], [], 0
    sched_rows = []
    d = t0 - timedelta(days=days_back)
    while d <= t0 + timedelta(days=3):
        for meal in MEALS:
            s = MealSchedule(institution_id=inst.id, date=d, meal_type=meal, cutoff_at=default_cutoff(d, meal, cfg), is_holiday=d in holidays, event=events.get(d),
                             service_status="planned"); db.add(s); db.flush()
            for n in MENU[meal][d.weekday()]:
                db.add(ScheduleDish(schedule_id=s.id, menu_item_id=items[n].id))
            sched_rows.append(s)
            if s.is_holiday:
                if d < t0: s.headcount, s.service_status = 0, "closed"
                continue
            share = {"breakfast": .55, "lunch": .85, "snacks": .45, "dinner": .8}[meal]
            f = [1, 1, 1, 1, .92, .82, .78][d.weekday()] * (.9 if (meal == "dinner" and d.weekday() == 4) else 1) * (1.12 if s.event else 1)
            want = np.clip(share * f * taste, 0, .98)
            intends = rng.random(n_students) < want
            booked = rng.random(n_students) < np.where(intends, book_p, .08 * book_p)
            canc = booked & (rng.random(n_students) < .07)
            active = booked & ~canc
            attended = (active & intends & (rng.random(n_students) < .97)) | (~active & intends & (rng.random(n_students) < np.where(canc, .15, .9)))
            for k in np.nonzero(booked)[0]:
                bid += 1
                created = s.cutoff_at - timedelta(hours=float(rng.uniform(1, 20)))
                bk.append(dict(id=bid, schedule_id=s.id, student_id=sids[k], status="cancelled" if canc[k] else "booked", created_at=created, updated_at=created))
                if canc[k]:
                    cn.append(dict(booking_id=bid, reason="Plans changed", cancelled_at=created + timedelta(hours=1)))
            if d < t0:
                s.headcount = int(attended.sum()); s.service_status = "closed"
                start = meal_start(d, meal, {**cfg})
                for k in np.nonzero(attended)[0]:
                    at.append(dict(schedule_id=s.id, student_id=sids[k], was_booked=bool(active[k]), marked_at=start))
                est = int(active.sum() * 1.05) + 8  # naive manager estimate (bookings + buffer)
                for n in MENU[meal][d.weekday()]:
                    it, (_c, _d, portion, _cost, upt, over, pop) = items[n], DISHES[n]
                    prep = round(est * portion * over * float(rng.lognormal(0, .04)), 2)
                    cons = round(min(prep, s.headcount * portion * upt * float(rng.lognormal(0, .06))), 2)
                    left = round(prep - cons, 2); edible = round(left * rnd.uniform(.55, .9), 2)
                    db.add(PreparationRecord(schedule_id=s.id, menu_item_id=it.id, prepared_qty=prep, available_qty=prep, recorded_by=kt.id))
                    db.add(ConsumptionRecord(schedule_id=s.id, menu_item_id=it.id, consumed_qty=cons, recorded_by=kt.id))
                    db.add(WasteRecord(schedule_id=s.id, menu_item_id=it.id, leftover_qty=left, edible_qty=edible, inedible_qty=round(left - edible, 2), source="manual", recorded_by=kt.id))
                    pool = np.nonzero(attended)[0]
                    if len(pool) and rnd.random() < .5:
                        k = int(rng.choice(pool))
                        db.add(Rating(student_id=sids[k], menu_item_id=it.id, schedule_id=s.id, rating=int(np.clip(round(rng.normal(pop, .9)), 1, 5)), comment=rnd.choice(COMMENTS) if rnd.random() < .12 else None))
        db.flush()
        d += timedelta(days=1)
    db.bulk_insert_mappings(Booking, bk); db.bulk_insert_mappings(BookingCancellation, cn); db.bulk_insert_mappings(Attendance, at)
    db.commit()
    # surplus history (collected) + current listings
    past = [s for s in sched_rows if s.date < t0 and not s.is_holiday]
    for s in rnd.sample(past, min(30, len(past))):
        w = db.query(WasteRecord).filter_by(schedule_id=s.id).order_by(WasteRecord.edible_qty.desc()).first()
        if not w or w.edible_qty < 2: continue
        m = db.get(MenuItem, w.menu_item_id); st = meal_start(s.date, s.meal_type, cfg) + timedelta(hours=1)
        l = SurplusListing(institution_id=inst.id, schedule_id=s.id, menu_item_id=m.id, food_name=m.name, category="cooked", quantity_kg=w.edible_qty, portions=int(w.edible_qty / m.portion_kg),
                           prepared_at=st, storage_condition="hot_held", storage_temp_c=66, use_by=st + timedelta(hours=8), status="collected", auto_check=[], verified_by=mg.id, verified_at=st + timedelta(minutes=20), created_by=kt.id, created_at=st)
        db.add(l); db.flush()
        r = RedistributionRequest(listing_id=l.id, partner_id=n1.id, status="delivered", pickup_time=st + timedelta(hours=1), decided_by=mg.id, created_at=st + timedelta(minutes=30)); db.add(r); db.flush()
        kg = round(w.edible_qty * .9, 2)
        db.add(CollectionRecord(request_id=r.id, collected_kg=kg, portions=int(kg / m.portion_kg), delivered_to="Community shelter (demo)", collected_at=st + timedelta(hours=1, minutes=30)))
    n = local_now()
    db.add(SurplusListing(institution_id=inst.id, food_name="Veg Biryani (demo)", category="cooked", quantity_kg=6.0, portions=20, prepared_at=n - timedelta(hours=1), storage_condition="hot_held", storage_temp_c=68,
                          use_by=n + timedelta(hours=5), status="eligible", verified_by=mg.id, verified_at=n, created_by=kt.id, auto_check=[]))
    db.add(SurplusListing(institution_id=inst.id, food_name="Chapati (demo)", category="cooked", quantity_kg=3.0, portions=30, prepared_at=n - timedelta(hours=1), storage_condition="hot_held", storage_temp_c=64,
                          use_by=n + timedelta(hours=4), status="pending_review", created_by=kt.id, auto_check=[]))
    db.commit()
    if train_model:
        from .services import forecast
        from .services.alerts_engine import generate
        m = forecast.train(db, inst.id)
        ids = [i for (i,) in db.query(MealSchedule.id).filter(MealSchedule.institution_id == inst.id, MealSchedule.date >= t0)]
        forecast.predict_schedules(db, inst.id, ids)
        generate(db, inst.id)
        if not quiet: print(f"Model: {m.algorithm}  test metrics: {(m.metrics or {}).get('test')}")
    if not quiet:
        print(f"Seeded SYNTHETIC demo data: {n_students} students, {len(sched_rows)} meal schedules, {len(bk)} bookings, {len(at)} attendance rows.")
        print(f"Demo password for all seeded accounts: {settings.seed_demo_password}")
        print("Logins: superadmin@ / manager@ / kitchen@ / ngo@ / student001@  (domain: platesense.demo or students.platesense.demo)")
    db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true"); ap.add_argument("--students", type=int, default=200); ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args()
    run(a.students, a.days, a.reset)
