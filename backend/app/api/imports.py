"""API импорта выгрузок 1С."""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import get_session
from app.importers.common import ReportFormatError
from app.importers.loader import import_folder
from app.services.snapshots import save_snapshot

router = APIRouter(prefix="/api/imports", tags=["Импорт"])
SessionDep = Annotated[Session, Depends(get_session)]


class SnapshotOut(BaseModel):
    id: int
    created_at: datetime
    source: str
    files: dict
    summary: dict


class IssueOut(BaseModel):
    severity: str
    area: str
    item: str | None
    message: str


class ItemOut(BaseModel):
    name: str
    abc: str
    line_group: str | None
    form: str | None
    nfp: str | None
    nfp_source: str | None
    in_scope: bool
    spec: str | None
    spec_method: str | None
    spec_score: float
    spec_needs_confirmation: bool
    kind: str | None = None
    min_series: float | None = None
    max_series: float | None = None
    stm: bool = False


def _run_import(session: Session, folder: Path, source: str) -> models.ImportSnapshot:
    try:
        result = import_folder(folder)
    except ReportFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return save_snapshot(session, result, source=source)


@router.post("/from-folder", response_model=SnapshotOut)
def import_from_folder(session: SessionDep):
    """Загрузить выгрузки из папки на сервере (PP_DATA_DIR, по умолчанию «Исходные данные»)."""
    if not settings.data_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Папка {settings.data_dir} не найдена")
    return _run_import(session, settings.data_dir, source="folder")


@router.post("/upload", response_model=SnapshotOut)
def import_upload(session: SessionDep, files: Annotated[list[UploadFile], File()]):
    """Загрузить файлы из браузера. Тип файла определяется по имени, как в папке."""
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            name = Path(f.filename or "file.xlsx").name
            with open(Path(tmp) / name, "wb") as out:
                shutil.copyfileobj(f.file, out)
        return _run_import(session, Path(tmp), source="upload")


@router.get("", response_model=list[SnapshotOut])
def list_snapshots(session: SessionDep):
    return session.scalars(select(models.ImportSnapshot).order_by(models.ImportSnapshot.id.desc())).all()


def _get_snapshot(session: Session, snapshot_id: int) -> models.ImportSnapshot:
    snap = session.get(models.ImportSnapshot, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Снимок не найден")
    return snap


@router.get("/{snapshot_id}", response_model=SnapshotOut)
def get_snapshot(snapshot_id: int, session: SessionDep):
    return _get_snapshot(session, snapshot_id)


@router.get("/{snapshot_id}/issues", response_model=list[IssueOut])
def get_issues(
    snapshot_id: int,
    session: SessionDep,
    severity: Annotated[str | None, Query(pattern="^(error|warning|info)$")] = None,
):
    _get_snapshot(session, snapshot_id)
    q = select(models.ImportIssue).where(models.ImportIssue.snapshot_id == snapshot_id)
    if severity:
        q = q.where(models.ImportIssue.severity == severity)
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(session.scalars(q).all(), key=lambda i: (order[i.severity], i.area, i.item or ""))


@router.get("/{snapshot_id}/items", response_model=list[ItemOut])
def get_items(snapshot_id: int, session: SessionDep):
    _get_snapshot(session, snapshot_id)
    q = select(models.Item).where(models.Item.snapshot_id == snapshot_id).order_by(models.Item.name)
    return session.scalars(q).all()
