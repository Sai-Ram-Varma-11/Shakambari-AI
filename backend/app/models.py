from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)

from .db import Base
from .util import local_now as now

ROLES = ("super_admin", "mess_admin", "student", "kitchen", "ngo")
MEALS = ("breakfast", "lunch", "snacks", "dinner")


def fk(t, **kw):
    return Column(Integer, ForeignKey(t, ondelete=kw.pop("ondelete", "CASCADE")), **kw)


class Institution(Base):
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    code = Column(String(40), unique=True, nullable=False)
    data_mode = Column(String(20), default="real", nullable=False)  # 'demo' = synthetic seed data, 'real'
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=True, index=True, ondelete="SET NULL")
    email = Column(String(254), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    password_hash = Column(String(300), nullable=False)
    role = Column(String(20), nullable=False, index=True)
    phone = Column(String(30))
    is_active = Column(Boolean, default=True, nullable=False)
    is_approved = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now)
    last_login = Column(DateTime)


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    user_id = fk("users.id", primary_key=True)
    diet = Column(String(20), default="veg")  # veg | egg | non_veg | vegan
    hostel = Column(String(80))
    dietary_notes = Column(String(300))


class NGOPartner(Base):
    __tablename__ = "ngo_partners"
    user_id = fk("users.id", primary_key=True)
    org_name = Column(String(200), nullable=False)
    registration_no = Column(String(80))  # self-declared, NOT verified by the system
    address = Column(String(300))
    verified = Column(Boolean, default=False, nullable=False)
    verified_by = Column(Integer)
    verified_at = Column(DateTime)


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False, index=True)
    name = Column(String(120), nullable=False)
    category = Column(String(30), default="other")
    diet = Column(String(20), default="veg")
    portion_kg = Column(Float, nullable=False, default=0.15)  # cooked weight per student portion
    cost_per_kg = Column(Float, nullable=False, default=100.0)
    is_active = Column(Boolean, default=True)


class MealSchedule(Base):
    __tablename__ = "meal_schedules"
    __table_args__ = (UniqueConstraint("institution_id", "date", "meal_type"), Index("ix_sched_date", "institution_id", "date"))
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False)
    date = Column(Date, nullable=False)
    meal_type = Column(String(20), nullable=False)
    cutoff_at = Column(DateTime, nullable=False)
    is_holiday = Column(Boolean, default=False)
    event = Column(String(120))
    headcount = Column(Integer)  # actual attendance (single source of truth once recorded)
    service_status = Column(String(20), default="planned")  # planned|preparing|served|closed


class ScheduleDish(Base):
    __tablename__ = "schedule_dishes"
    schedule_id = fk("meal_schedules.id", primary_key=True)
    menu_item_id = fk("menu_items.id", primary_key=True)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("schedule_id", "student_id"),)
    id = Column(Integer, primary_key=True)
    schedule_id = fk("meal_schedules.id", nullable=False, index=True)
    student_id = fk("users.id", nullable=False, index=True)
    status = Column(String(12), default="booked", nullable=False)  # booked|cancelled
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now)


class BookingCancellation(Base):
    __tablename__ = "booking_cancellations"
    id = Column(Integer, primary_key=True)
    booking_id = fk("bookings.id", nullable=False, index=True)
    reason = Column(String(200))
    cancelled_at = Column(DateTime, default=now)


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("schedule_id", "student_id"),)
    id = Column(Integer, primary_key=True)
    schedule_id = fk("meal_schedules.id", nullable=False, index=True)
    student_id = fk("users.id", nullable=False)
    was_booked = Column(Boolean, default=False)
    marked_by = Column(Integer)
    marked_at = Column(DateTime, default=now)


class DishPreference(Base):
    __tablename__ = "dish_preferences"
    __table_args__ = (UniqueConstraint("student_id", "menu_item_id"),)
    id = Column(Integer, primary_key=True)
    student_id = fk("users.id", nullable=False)
    menu_item_id = fk("menu_items.id", nullable=False)
    preference = Column(String(10), nullable=False)  # like|dislike


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("student_id", "menu_item_id", "schedule_id"),)
    id = Column(Integer, primary_key=True)
    student_id = fk("users.id", nullable=False)
    menu_item_id = fk("menu_items.id", nullable=False, index=True)
    schedule_id = fk("meal_schedules.id", nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(String(500))
    created_at = Column(DateTime, default=now)


class _Rec:
    id = Column(Integer, primary_key=True)


class PreparationRecord(Base):
    __tablename__ = "preparation_records"
    __table_args__ = (UniqueConstraint("schedule_id", "menu_item_id"),)
    id = Column(Integer, primary_key=True)
    schedule_id = fk("meal_schedules.id", nullable=False, index=True)
    menu_item_id = fk("menu_items.id", nullable=False)
    recommended_qty = Column(Float)
    prepared_qty = Column(Float, nullable=False)
    available_qty = Column(Float)
    recorded_by = Column(Integer)
    created_at = Column(DateTime, default=now)


class ConsumptionRecord(Base):
    __tablename__ = "consumption_records"
    __table_args__ = (UniqueConstraint("schedule_id", "menu_item_id"),)
    id = Column(Integer, primary_key=True)
    schedule_id = fk("meal_schedules.id", nullable=False, index=True)
    menu_item_id = fk("menu_items.id", nullable=False)
    consumed_qty = Column(Float, nullable=False)
    recorded_by = Column(Integer)
    created_at = Column(DateTime, default=now)


class WasteRecord(Base):
    __tablename__ = "waste_records"
    id = Column(Integer, primary_key=True)
    schedule_id = fk("meal_schedules.id", nullable=False, index=True)
    menu_item_id = fk("menu_items.id", nullable=False)
    leftover_qty = Column(Float, nullable=False)
    edible_qty = Column(Float, default=0)  # edible surplus (may be eligible for redistribution after review)
    inedible_qty = Column(Float, default=0)  # plate waste / unusable
    source = Column(String(10), default="manual")  # manual | image
    observation_id = Column(Integer)
    notes = Column(String(300))
    recorded_by = Column(Integer)
    created_at = Column(DateTime, default=now)


class SurplusListing(Base):
    __tablename__ = "surplus_listings"
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False, index=True)
    schedule_id = fk("meal_schedules.id", nullable=True, ondelete="SET NULL")
    menu_item_id = fk("menu_items.id", nullable=True, ondelete="SET NULL")
    food_name = Column(String(150), nullable=False)
    category = Column(String(30), nullable=False)  # cooked|packaged|fruit|bakery|raw|other
    quantity_kg = Column(Float, nullable=False)
    portions = Column(Integer, default=0)
    prepared_at = Column(DateTime, nullable=False)
    storage_condition = Column(String(20), nullable=False)  # hot_held|refrigerated|room_temp|frozen
    storage_temp_c = Column(Float)
    use_by = Column(DateTime)
    status = Column(String(20), default="pending_review", index=True)
    auto_check = Column(JSON, default=list)
    review_notes = Column(String(300))
    verified_by = Column(Integer)
    verified_at = Column(DateTime)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=now)


class RedistributionRequest(Base):
    __tablename__ = "redistribution_requests"
    id = Column(Integer, primary_key=True)
    listing_id = fk("surplus_listings.id", nullable=False, index=True)
    partner_id = fk("users.id", nullable=False, index=True)
    status = Column(String(12), default="pending")  # pending|approved|rejected|picked_up|delivered|cancelled
    pickup_time = Column(DateTime)
    message = Column(String(300))
    decided_by = Column(Integer)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now)


class CollectionRecord(Base):
    __tablename__ = "collection_records"
    id = Column(Integer, primary_key=True)
    request_id = fk("redistribution_requests.id", nullable=False, index=True)
    collected_kg = Column(Float, nullable=False)
    portions = Column(Integer, default=0)
    delivered_to = Column(String(200))
    collected_at = Column(DateTime, default=now)


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True)
    schedule_id = fk("meal_schedules.id", nullable=False, index=True)
    menu_item_id = fk("menu_items.id", nullable=True)
    kind = Column(String(12), nullable=False)  # attendance | dish
    value = Column(Float, nullable=False)
    lower = Column(Float)
    upper = Column(Float)
    active_bookings = Column(Integer)
    model_id = Column(Integer)
    created_at = Column(DateTime, default=now)


class MLModel(Base):
    __tablename__ = "ml_models"
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False, index=True)
    algorithm = Column(String(60), nullable=False)
    metrics = Column(JSON, default=dict)
    features = Column(JSON, default=list)
    n_train = Column(Integer, default=0)
    n_test = Column(Integer, default=0)
    path = Column(String(300))
    data_mode = Column(String(20), default="real")
    is_active = Column(Boolean, default=True)
    trained_at = Column(DateTime, default=now)


class MenuRecommendation(Base):
    __tablename__ = "menu_recommendations"
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False, index=True)
    menu_item_id = fk("menu_items.id", nullable=True, ondelete="SET NULL")
    kind = Column(String(30))
    message = Column(Text)
    evidence = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)


class ImageObservation(Base):
    __tablename__ = "image_observations"
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False, index=True)
    schedule_id = fk("meal_schedules.id", nullable=True, ondelete="SET NULL")
    menu_item_id = fk("menu_items.id", nullable=True, ondelete="SET NULL")
    file_name = Column(String(80), nullable=False)
    width = Column(Integer)
    height = Column(Integer)
    fmt = Column(String(10))
    size_bytes = Column(Integer)
    predicted_label = Column(String(40))
    confidence = Column(Float)
    scores = Column(JSON, default=dict)
    corrected_label = Column(String(40))
    quantity_kg = Column(Float)
    status = Column(String(12), default="pending")  # pending|confirmed
    created_by = Column(Integer)
    created_at = Column(DateTime, default=now)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False, index=True)
    kind = Column(String(40), nullable=False)
    severity = Column(String(10), default="info")  # info|warning|critical
    title = Column(String(200))
    what = Column(Text)
    evidence = Column(Text)
    why = Column(Text)
    action = Column(Text)
    is_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = fk("users.id", nullable=False, index=True)
    title = Column(String(200), nullable=False)
    body = Column(String(500))
    link = Column(String(120))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class SustainabilitySnapshot(Base):
    __tablename__ = "sustainability_snapshots"
    id = Column(Integer, primary_key=True)
    institution_id = fk("institutions.id", nullable=False, index=True)
    period = Column(String(10), nullable=False)
    data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    action = Column(String(60), nullable=False)
    entity = Column(String(60))
    entity_id = Column(Integer)
    detail = Column(String(500))
    created_at = Column(DateTime, default=now)
