"""API календарей линий и диаграммы Ганта 2 ступени."""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.services import schedule as svc

router = APIRouter(tags=["Календари и Гант"])
SessionDep = Annotated[Session, Depends(get_session)]


def _month(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m").date()
    except ValueError as exc:
        raise HTTPException(422, "Месяц в формате ГГГГ-ММ") from exc


class TemplateIn(BaseModel):
    line_code: str
    mode: str = Field(description="«5/2» или «24/7»")
    shifts: int = Field(ge=0, le=3)


class DayChange(BaseModel):
    line_code: str
    day: date
    shifts: int | None = Field(None, ge=0, le=3, description="null — вернуть к шаблону")
    reason: str | None = None


class DaysIn(BaseModel):
    changes: list[DayChange]


class TaskOut(BaseModel):
    id: int
    number: str
    item: str
    qty: float
    line_group: str | None
    line_code: str | None
    start: datetime | None
    end: datetime | None
    hours: float
    changeover: bool
    locked: bool
    available_from: date | None
    warnings: list[str]


class TaskPatch(BaseModel):
    line_code: str | None = None
    start: datetime | None = None
    locked: bool | None = None


def _guard(fn, *args):
    try:
        return fn(*args)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------- календари


@router.get("/api/calendars")
def get_month(session: SessionDep, month: Annotated[str, Query(description="ГГГГ-ММ")]):
    return svc.month_grid(session, _month(month))


@router.put("/api/calendars/template")
def put_template(body: TemplateIn, session: SessionDep):
    _guard(svc.set_template, session, body.line_code, body.mode, body.shifts)
    return svc.replan(session)


@router.put("/api/calendars/days")
def put_days(body: DaysIn, session: SessionDep):
    _guard(svc.set_days, session, [c.model_dump() for c in body.changes])
    return svc.replan(session)


@router.delete("/api/calendars/month")
def reset_month(session: SessionDep, month: str, line_code: str | None = None):
    svc.reset_month(session, line_code, _month(month))
    return svc.replan(session)


# ---------- Гант


@router.post("/api/schedule/sync")
def sync(session: SessionDep, snapshot_id: int | None = None):
    stats = _guard(svc.sync_orders, session, snapshot_id)
    return {**stats, **svc.replan(session)}


@router.post("/api/schedule/replan")
def replan(session: SessionDep):
    return svc.replan(session)


@router.get("/api/schedule")
def get_schedule(
    session: SessionDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
):
    date_from = date_from or date.today() - timedelta(days=7)
    date_to = date_to or date_from + timedelta(days=90)
    if (date_to - date_from).days > 400:
        raise HTTPException(422, "Период — не больше 400 дней")
    data = svc.timeline(session, date_from, date_to)
    data["tasks"] = [TaskOut.model_validate(t, from_attributes=True) for t in data["tasks"]]
    return data


@router.patch("/api/schedule/tasks/{task_id}")
def patch_task(task_id: int, body: TaskPatch, session: SessionDep):
    _guard(svc.move_task, session, task_id, body.line_code, body.start, body.locked)
    return {"ok": True}
