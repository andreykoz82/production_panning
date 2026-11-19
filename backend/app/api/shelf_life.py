"""API анализа сроков годности ГП."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.planning.shelf_life import DEFAULT_THRESHOLD_PCT, ShelfLifeParams
from app.services.shelf_life import shelf_life_analysis

router = APIRouter(prefix="/api/shelf-life", tags=["Сроки годности"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def get_shelf_life(
    session: SessionDep,
    horizon_months: Annotated[int, Query(ge=1, le=24)] = 12,
    fulfillment_pct: Annotated[
        float, Query(ge=0, le=300, description="Процент выполнения плана продаж")
    ] = 100,
    threshold_pct: Annotated[
        float, Query(ge=0, le=100, description="Ниже — неликвид")
    ] = DEFAULT_THRESHOLD_PCT,
    replenish: Annotated[bool, Query(description="Учитывать будущую наработку")] = True,
    cover_months: Annotated[float, Query(ge=0.5, le=12)] = 3,
    bottling: Annotated[bool, Query(description="Включать розлив")] = True,
    calc_date: date | None = None,
    item: str | None = Query(None, description="ГП для подробностей"),
):
    params = ShelfLifeParams(
        calc_date=calc_date or date.today(),
        horizon_months=horizon_months,
        fulfillment_pct=fulfillment_pct,
        threshold_pct=threshold_pct,
        replenish=replenish,
        cover_months=cover_months,
        bottling=bottling,
    )
    try:
        return shelf_life_analysis(session, params, item)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
