"""Module 6 - image observation. Uses a transparent colour-histogram heuristic (no model download, no API key).
It is NOT a trained deep-learning model; results are suggestions that a human must confirm or correct.
It does not estimate weight and says nothing about food safety."""
import io
import uuid
from pathlib import Path

import numpy as np
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from ..config import settings

LABELS = ["rice", "dal_gravy", "vegetable_curry", "vegetables", "bread", "vegetarian_snack", "unknown"]
ALLOWED = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MODEL_NAME = "color-heuristic-v1"


def validate_and_open(data: bytes):
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Image too large (max {settings.max_upload_mb} MB)")
    if not data:
        raise HTTPException(400, "Empty file")
    try:
        probe = Image.open(io.BytesIO(data)); probe.verify()
        img = Image.open(io.BytesIO(data)); fmt = img.format
    except (UnidentifiedImageError, Exception):
        raise HTTPException(400, "File is not a valid image")
    if fmt not in ALLOWED:
        raise HTTPException(400, "Only JPEG, PNG or WEBP images are accepted")
    if img.width * img.height > 40_000_000:
        raise HTTPException(400, "Image dimensions too large")
    return img, fmt


def classify(img: Image.Image):
    arr = np.asarray(img.convert("RGB").resize((96, 96)).convert("HSV")).reshape(-1, 3).astype(float)
    h, s, v = arr[:, 0] * 360 / 255, arr[:, 1] / 255, arr[:, 2] / 255
    f = lambda m: float(m.mean())
    raw = {"rice": f((s < 0.2) & (v > 0.6)), "dal_gravy": f((h >= 35) & (h < 70) & (s >= 0.3) & (v > 0.4)) * 1.1,
           "vegetable_curry": f(((h < 20) | (h > 340)) & (s >= 0.3) & (v > 0.2)), "vegetables": f((h >= 70) & (h < 170) & (s >= 0.25) & (v > 0.2)) * 1.2,
           "bread": f((h >= 20) & (h < 40) & (s >= 0.2) & (s < 0.55) & (v > 0.5)), "vegetarian_snack": f((h >= 20) & (h < 35) & (s >= 0.55) & (v > 0.3)) * 0.9}
    tot = sum(raw.values())
    top = max(raw, key=raw.get)
    if tot < 0.08:
        return "unknown", 0.0, {k: 0.0 for k in raw}
    scores = {k: round(v_ / tot, 3) for k, v_ in raw.items()}
    return top, round(min(scores[top], 0.95), 3), scores


def save(data: bytes, fmt: str) -> str:
    d = Path(settings.upload_dir); d.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ALLOWED[fmt]}"
    (d / name).write_bytes(data)
    return name
