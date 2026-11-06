import copy
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import settings

DEFAULT_SETTINGS = {
    "booking_cutoff_hours": 6,
    "waste_alert_pct": 15,
    "prep_buffer_pct": 5,
    "currency": "INR",
    "meal_times": {"breakfast": "07:30", "lunch": "12:30", "snacks": "16:30", "dinner": "19:30"},
    # ILLUSTRATIVE defaults. Your food-safety officer / local regulator must review and set the real values.
    "eligibility": {"max_hours_since_prep": 4, "hot_min_temp_c": 60, "cold_max_temp_c": 5, "room_temp_max_hours": 2,
                    "min_hours_before_use_by": 2, "allowed_categories": ["cooked", "packaged", "fruit", "bakery"]},
}


def local_now() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return local_now().date()


def merged_settings(inst) -> dict:
    out = copy.deepcopy(DEFAULT_SETTINGS)
    for k, v in (inst.settings or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def meal_start(d: date, meal: str, cfg: dict) -> datetime:
    h, m = map(int, cfg["meal_times"][meal].split(":"))
    return datetime.combine(d, time(h, m))


def default_cutoff(d: date, meal: str, cfg: dict) -> datetime:
    return meal_start(d, meal, cfg) - timedelta(hours=cfg["booking_cutoff_hours"])


def audit(db, user, action, entity=None, entity_id=None, detail=None):
    from .models import AuditLog
    db.add(AuditLog(user_id=getattr(user, "id", user), action=action, entity=entity, entity_id=entity_id,
                    detail=(detail or "")[:500]))


def notify(db, user_ids, title, body="", link=None, dedup_key=None):
    from .models import Notification
    for uid in set(user_ids):
        if dedup_key:
            user_dedup = f"{dedup_key}:{uid}"
            exists = db.query(Notification).filter_by(user_id=uid, dedup_key=user_dedup).first()
            if exists:
                continue
            db.add(Notification(user_id=uid, title=title[:200], body=body[:500], link=link, dedup_key=user_dedup))
        else:
            db.add(Notification(user_id=uid, title=title[:200], body=body[:500], link=link))


def staff_ids(db, inst_id, roles=("mess_admin",)):
    from .models import User
    return [u for (u,) in db.query(User.id).filter(User.institution_id == inst_id, User.role.in_(roles), User.is_active == True)]  # noqa: E712
