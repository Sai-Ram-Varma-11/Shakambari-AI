from datetime import timedelta


def evaluate(cfg: dict, category, prepared_at, storage_condition, storage_temp_c, use_by, now):
    """Configurable, conservative screening. It NEVER certifies food as safe: a human must still review and approve."""
    r = cfg["eligibility"]
    checks = []
    add = lambda rule, ok, detail: checks.append({"rule": rule, "passed": bool(ok), "detail": detail})
    add("Category allowed for redistribution", category in r["allowed_categories"], f"'{category}' (allowed: {', '.join(r['allowed_categories'])})")
    hrs = (now - prepared_at).total_seconds() / 3600
    add("Not held too long since preparation", 0 <= hrs <= r["max_hours_since_prep"], f"{hrs:.1f} h since preparation (max {r['max_hours_since_prep']} h)")
    if storage_condition == "hot_held":
        add("Hot holding temperature", storage_temp_c is not None and storage_temp_c >= r["hot_min_temp_c"], f"{storage_temp_c} C recorded (min {r['hot_min_temp_c']} C)")
    elif storage_condition == "refrigerated":
        add("Cold holding temperature", storage_temp_c is not None and storage_temp_c <= r["cold_max_temp_c"], f"{storage_temp_c} C recorded (max {r['cold_max_temp_c']} C)")
    elif storage_condition == "room_temp":
        add("Room-temperature time limit", hrs <= r["room_temp_max_hours"], f"{hrs:.1f} h at room temperature (max {r['room_temp_max_hours']} h)")
    if use_by is not None:
        left = (use_by - now).total_seconds() / 3600
        add("Sufficient time before use-by", left >= r["min_hours_before_use_by"], f"{left:.1f} h until use-by (min {r['min_hours_before_use_by']} h)")
    return checks
