import base64
import hashlib
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx
import numpy as np
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from ..config import settings
from .storage import storage

log = logging.getLogger("shakambari.vision")

LABELS = ["rice", "dal_gravy", "vegetable_curry", "vegetables", "bread", "vegetarian_snack", "unknown"]
ALLOWED = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}

_vision_cache: Dict[str, Tuple[str, float, dict, str, str]] = {}


def validate_and_process(data: bytes) -> Tuple[Image.Image, str, bytes]:
    """Validates image, strips EXIF metadata, re-encodes, and caps maximum dimensions."""
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Image too large (max {settings.max_upload_mb} MB)")
    if not data:
        raise HTTPException(400, "Empty file")

    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
        img = Image.open(io.BytesIO(data))
        fmt = img.format or "JPEG"
    except (UnidentifiedImageError, Exception):
        raise HTTPException(400, "File is not a valid image")

    if fmt not in ALLOWED:
        raise HTTPException(400, "Only JPEG, PNG or WEBP images are accepted")

    if img.width * img.height > 40_000_000:
        raise HTTPException(400, "Image dimensions exceed 40 megapixels")

    # Re-encode and cap dimensions (max 2048px on longest side)
    img = img.convert("RGB")
    max_dim = 2048
    if max(img.width, img.height) > max_dim:
        scale = max_dim / max(img.width, img.height)
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    # Strip EXIF by saving to clean buffer without exif kwarg
    out_buf = io.BytesIO()
    img.save(out_buf, format="JPEG", quality=88, optimize=True)
    sanitized_bytes = out_buf.getvalue()

    return img, "JPEG", sanitized_bytes


class BaseClassifier:
    def classify(self, img: Image.Image, image_bytes: bytes) -> Tuple[str, float, dict, str, str]:
        raise NotImplementedError


class HeuristicClassifier(BaseClassifier):
    def classify(self, img: Image.Image, image_bytes: bytes) -> Tuple[str, float, dict, str, str]:
        arr = np.asarray(img.convert("RGB").resize((96, 96)).convert("HSV")).reshape(-1, 3).astype(float)
        h, s, v = arr[:, 0] * 360 / 255, arr[:, 1] / 255, arr[:, 2] / 255
        f = lambda m: float(m.mean())
        raw = {
            "rice": f((s < 0.2) & (v > 0.6)),
            "dal_gravy": f((h >= 35) & (h < 70) & (s >= 0.3) & (v > 0.4)) * 1.1,
            "vegetable_curry": f(((h < 20) | (h > 340)) & (s >= 0.3) & (v > 0.2)),
            "vegetables": f((h >= 70) & (h < 170) & (s >= 0.25) & (v > 0.2)) * 1.2,
            "bread": f((h >= 20) & (h < 40) & (s >= 0.2) & (s < 0.55) & (v > 0.5)),
            "vegetarian_snack": f((h >= 20) & (h < 35) & (s >= 0.55) & (v > 0.3)) * 0.9,
        }
        tot = sum(raw.values())
        top = max(raw, key=raw.get)
        if tot < 0.08:
            return "unknown", 0.0, {k: 0.0 for k in raw}, "heuristic", "color-heuristic-v1"
        scores = {k: round(v_ / tot, 3) for k, v_ in raw.items()}
        return top, round(min(scores[top], 0.95), 3), scores, "heuristic", "color-heuristic-v1"


class LLMClassifier(BaseClassifier):
    def __init__(self):
        self.heuristic = HeuristicClassifier()
        self.api_key = settings.vision_api_key
        self.model_name = settings.vision_model or "gemini-1.5-flash"

    def classify(self, img: Image.Image, image_bytes: bytes) -> Tuple[str, float, dict, str, str]:
        if not self.api_key:
            log.info("VISION_API_KEY not set; gracefully falling back to heuristic classifier")
            return self.heuristic.classify(img, image_bytes)

        # Check in-memory hash cache
        img_hash = hashlib.sha256(image_bytes).hexdigest()
        if img_hash in _vision_cache:
            return _vision_cache[img_hash]

        prompt = (
            "You are a food classifier for Shakambari AI, a strictly lacto-vegetarian dining hall system. "
            "Analyze the food in the image and choose exactly ONE label from: "
            "['rice', 'dal_gravy', 'vegetable_curry', 'vegetables', 'bread', 'vegetarian_snack', 'unknown']. "
            "CRITICAL FOOD-SAFETY & POLICY RULE: If the food appears to contain meat, fish, poultry, seafood, egg, "
            "or any non-vegetarian item, you MUST return 'unknown' with confidence 0.0 and reason 'Non-vegetarian food detected'. "
            "Return ONLY a valid JSON object matching: "
            '{"label": "<label>", "confidence": <float_between_0.0_and_1.0>, "reason": "<short_explanation>"}'
        )

        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": "image/jpeg", "data": b64_img}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                if not resp.is_success:
                    log.warning("LLM API returned status %s: %s; falling back to heuristic", resp.status_code, resp.text)
                    return self.heuristic.classify(img, image_bytes)

                data = resp.json()
                text_content = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text_content)

                lbl = str(parsed.get("label", "unknown")).lower().strip()
                if lbl not in LABELS:
                    lbl = "unknown"

                conf = float(parsed.get("confidence", 0.5))
                conf = round(max(0.0, min(0.99, conf)), 3)

                scores = {k: 0.05 for k in LABELS if k != "unknown"}
                if lbl in scores:
                    scores[lbl] = conf

                result = (lbl, conf, scores, "llm", self.model_name)
                _vision_cache[img_hash] = result
                return result

        except Exception as e:
            log.warning("LLM classifier encountered exception (%s); falling back to heuristic", e)
            return self.heuristic.classify(img, image_bytes)


def get_classifier() -> BaseClassifier:
    provider = (settings.vision_provider or "heuristic").lower().strip()
    if provider == "llm":
        return LLMClassifier()
    return HeuristicClassifier()


def save_image_file(data: bytes, fmt: str = "JPEG") -> str:
    ext = ALLOWED.get(fmt, ".jpg")
    name = f"{uuid.uuid4().hex}{ext}"
    storage.save_file(name, data, content_type=f"image/{fmt.lower()}")
    return name


def delete_image_file(filename: str) -> bool:
    return storage.delete_file(filename)
