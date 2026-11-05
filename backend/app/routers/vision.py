from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ImageObservation, MealSchedule, MenuItem, PreparationRecord, WasteRecord
from ..security import Ctx, need
from ..services import vision as V
from ..util import audit

router = APIRouter(prefix="/vision", tags=["image-recognition"])


def out(o):
    return {"id": o.id, "schedule_id": o.schedule_id, "menu_item_id": o.menu_item_id, "width": o.width, "height": o.height, "format": o.fmt,
            "predicted_label": o.predicted_label, "confidence": o.confidence, "scores": o.scores, "corrected_label": o.corrected_label,
            "final_label": o.corrected_label or o.predicted_label, "quantity_kg": o.quantity_kg, "status": o.status, "created_at": o.created_at,
            "model": V.MODEL_NAME,
            "disclaimer": "Colour-based suggestion. Confidence is classification confidence only - not weight and not a food-safety judgement."}


@router.get("/labels")
def labels(ctx: Ctx = Depends(need("mess_admin", "kitchen"))):
    return V.LABELS


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...), schedule_id: Optional[int] = Form(None), menu_item_id: Optional[int] = Form(None),
                 ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    img, fmt = V.validate_and_open(data)
    if schedule_id:
        s = db.get(MealSchedule, schedule_id)
        if not s or s.institution_id != ctx.inst_id:
            raise HTTPException(404, "Schedule not found")
    if menu_item_id:
        m = db.get(MenuItem, menu_item_id)
        if not m or m.institution_id != ctx.inst_id:
            raise HTTPException(404, "Dish not found")
    label, conf, scores = V.classify(img)
    o = ImageObservation(institution_id=ctx.inst_id, schedule_id=schedule_id, menu_item_id=menu_item_id, file_name=V.save(data, fmt), width=img.width,
                         height=img.height, fmt=fmt, size_bytes=len(data), predicted_label=label, confidence=conf, scores=scores, created_by=ctx.user.id)
    db.add(o); audit(db, ctx.user, "upload_image", "image_observation", None); db.commit()
    return out(o)


@router.get("")
def list_obs(ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    return [out(o) for o in db.query(ImageObservation).filter_by(institution_id=ctx.inst_id).order_by(ImageObservation.id.desc()).limit(100)]


def _get(db, ctx, oid):
    o = db.get(ImageObservation, oid)
    if not o or o.institution_id != ctx.inst_id:
        raise HTTPException(404, "Observation not found")
    return o


@router.get("/{oid}/image")
def image(oid: int, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    o = _get(db, ctx, oid)
    p = Path(settings.upload_dir) / o.file_name
    if not p.exists():
        raise HTTPException(404, "File missing")
    return FileResponse(p)


class CorrectIn(BaseModel):
    label: str


@router.patch("/{oid}/correct")
def correct(oid: int, b: CorrectIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    o = _get(db, ctx, oid)
    if b.label not in V.LABELS:
        raise HTTPException(422, "Unsupported label")
    if o.status == "confirmed":
        raise HTTPException(409, "Already confirmed")
    o.corrected_label = b.label
    audit(db, ctx.user, "correct_image_label", "image_observation", o.id, b.label); db.commit()
    return out(o)


class ConfirmIn(BaseModel):
    quantity_kg: float = Field(gt=0, le=1000)  # entered by a person or read from a calibrated scale - never inferred from the photo
    edible_kg: float = Field(default=0, ge=0)


@router.post("/{oid}/confirm")
def confirm(oid: int, b: ConfirmIn, ctx: Ctx = Depends(need("mess_admin", "kitchen")), db: Session = Depends(get_db)):
    """Module 6 -> 2: a confirmed observation with a manually entered quantity becomes a waste record."""
    o = _get(db, ctx, oid)
    if o.status == "confirmed":
        raise HTTPException(409, "Already confirmed")
    if b.edible_kg > b.quantity_kg:
        raise HTTPException(422, "Edible quantity cannot exceed the quantity")
    o.quantity_kg, o.status = b.quantity_kg, "confirmed"
    if o.schedule_id and o.menu_item_id:
        db.add(WasteRecord(schedule_id=o.schedule_id, menu_item_id=o.menu_item_id, leftover_qty=b.quantity_kg, edible_qty=b.edible_kg,
                           inedible_qty=b.quantity_kg - b.edible_kg, source="image", observation_id=o.id, recorded_by=ctx.user.id,
                           notes=f"image: {o.corrected_label or o.predicted_label}"))
    audit(db, ctx.user, "confirm_image", "image_observation", o.id); db.commit()
    return out(o)
