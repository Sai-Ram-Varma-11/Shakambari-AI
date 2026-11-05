from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.food_migrations import apply_food_policy_migrations
from app.util import today


def test_legacy_food_migration_preserves_history_and_guards_future_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE menu_items (
                id INTEGER PRIMARY KEY, name TEXT, diet TEXT, is_active BOOLEAN
            )
        """))
        connection.execute(text("""
            CREATE TABLE meal_schedules (
                id INTEGER PRIMARY KEY, date DATE
            )
        """))
        connection.execute(text("""
            CREATE TABLE schedule_dishes (
                schedule_id INTEGER, menu_item_id INTEGER
            )
        """))
        connection.execute(text("""
            CREATE TABLE surplus_listings (
                id INTEGER PRIMARY KEY, menu_item_id INTEGER, food_name TEXT, status TEXT
            )
        """))
        connection.execute(text("CREATE TABLE bookings (id INTEGER PRIMARY KEY, schedule_id INTEGER)"))
        connection.execute(text("INSERT INTO menu_items VALUES (1, 'Chicken Curry', 'non_veg', 1)"))
        connection.execute(text("INSERT INTO meal_schedules VALUES (1, :past), (2, :future)"),
                           {"past": (today() - timedelta(days=1)).isoformat(), "future": (today() + timedelta(days=1)).isoformat()})
        connection.execute(text("INSERT INTO schedule_dishes VALUES (1, 1), (2, 1)"))
        connection.execute(text(
            "INSERT INTO surplus_listings VALUES (1, 1, 'Chicken Curry', 'eligible'), "
            "(2, 1, 'Chicken Curry', 'collected')"
        ))
        connection.execute(text("INSERT INTO bookings VALUES (1, 1)"))

    apply_food_policy_migrations(engine)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT is_active FROM menu_items WHERE id = 1")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM schedule_dishes WHERE schedule_id = 1")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM schedule_dishes WHERE schedule_id = 2")).scalar_one() == 0
        listing = connection.execute(text("SELECT diet, status FROM surplus_listings WHERE id = 1")).one()
        assert listing == ("legacy_unverified", "ineligible")
        historical_listing = connection.execute(
            text("SELECT diet, status FROM surplus_listings WHERE id = 2")
        ).one()
        assert historical_listing == ("legacy_unverified", "collected")
        assert connection.execute(text("SELECT COUNT(*) FROM bookings")).scalar_one() == 1

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO menu_items (id, name, diet, is_active)
                VALUES (2, 'Egg Curry', 'egg', 1)
            """))

    engine.dispose()
