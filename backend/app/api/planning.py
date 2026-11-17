"""API расчёта потребности."""

from datetime import date, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import get_session
from app.exporters.stage2_xlsx import build_stage2_workbook
from app.services.planning import run_stage2

router = APIRouter(prefix="/api/planning", tags=["Планирование"])
SessionDep = Annotated[Session, Depends(get_session)]


class Stage2Request(BaseModel):
    snapshot_id: int | None = Field(None, description="Снимок данных; по умолчанию — последний")
    horizon_months: int = Field(3, ge=1, le=24)
    calc_date: date | None = Field(None, description="Дата расчёта; по умолчанию — сегодня")


class RunOut(BaseModel):
    id: int
    snapshot_id: int
    created_at: datetime
    stage: int
    params: dict
    summary: dict


class RunDetail(RunOut):
    lines: list[dict]
    materials: list[dict]
    nfp: list[dict]


@router.post("/stage2", response_model=RunDetail)
def calculate(req: Stage2Request, session: SessionDep):
    snapshot_id = req.snapshot_id or session.scalar(
        select(models.ImportSnapshot.id).order_by(models.ImportSnapshot.id.desc()).limit(1)
    )
    if not snapshot_id or not session.get(models.ImportSnapshot, snapshot_id):
        raise HTTPException(404, "Нет снимка данных — сначала загрузите выгрузки 1С")
    return run_stage2(session, snapshot_id, req.horizon_months, req.calc_date or date.today())


@router.get("/runs", response_model=list[RunOut])
def list_runs(session: SessionDep):
    return session.scalars(select(models.PlanRun).order_by(models.PlanRun.id.desc()).limit(50)).all()


def _get_run(session: Session, run_id: int) -> models.PlanRun:
    run = session.get(models.PlanRun, run_id)
    if not run:
        raise HTTPException(404, "Расчёт не найден")
    return run


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, session: SessionDep):
    return _get_run(session, run_id)


@router.get("/runs/{run_id}/export")
def export_run(run_id: int, session: SessionDep):
    run = _get_run(session, run_id)
    name = f"Потребность 2 ступени №{run.id} от {run.params['calc_date']}.xlsx"
    return Response(
        content=build_stage2_workbook(run),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )
