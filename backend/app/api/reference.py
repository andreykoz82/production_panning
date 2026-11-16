from fastapi import APIRouter
from pydantic import BaseModel

from app.reference import lines as ref

router = APIRouter(prefix="/api/reference", tags=["Справочники"])


class LineOut(BaseModel):
    code: str
    stage: int
    group: str
    capacity: float
    unit: str
    per_hour: float
    min_batch: float | None
    setters: int
    workers: int
    note: str


@router.get("/lines", response_model=list[LineOut])
def get_lines():
    return [
        LineOut(
            **line.__dict__,
            per_hour=round(line.per_hour, 2),
            min_batch=round(line.min_batch, 1) if line.min_batch else None,
        )
        for line in ref.LINES
    ]


@router.get("/rules")
def get_rules():
    """Правила планирования, согласованные 16.11.2026."""
    return {
        "shift_hours": ref.SHIFT_HOURS,
        "max_shifts_per_day": ref.MAX_SHIFTS_PER_DAY,
        "changeover_hours": ref.CHANGEOVER_HOURS,
        "nfp_quarantine_workdays": ref.NFP_QUARANTINE_WORKDAYS,
        "gp_certification_days": ref.GP_CERTIFICATION_DAYS,
        "excluded_groups": sorted(ref.EXCLUDED_GROUPS),
    }
