"""Загрузка снимка из БД для расчёта и сохранение результата."""

import math
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.planning.stage2 import PlanningData, Stage2Params, Stage2Result, calculate_stage2
from app.reference import warehouses as wh


def _frame(session: Session, model, snapshot_id: int, columns: list[str], *where) -> pd.DataFrame:
    q = select(*[getattr(model, c) for c in columns]).where(model.snapshot_id == snapshot_id, *where)
    return pd.DataFrame(session.execute(q).all(), columns=columns)


def warehouse_overrides(session: Session) -> dict[str, str]:
    return dict(session.execute(select(models.WarehouseRole.warehouse, models.WarehouseRole.role)).all())


def load_planning_data(session: Session, snapshot_id: int, with_reserve: bool = False) -> PlanningData:
    items = _frame(
        session,
        models.Item,
        snapshot_id,
        ["name", "abc", "line_group", "nfp", "purpose", "in_scope", "spec"],
    )
    stock_cols = ["warehouse", "name", "item", "characteristic", "purpose", "packing_allowed", "available"]
    stock_cols += ["is_defect"] + (["reserved"] if with_reserve else [])
    stock = wh.with_roles(
        _frame(session, models.StockRow, snapshot_id, stock_cols), warehouse_overrides(session)
    )
    specs = _frame(
        session,
        models.SpecLine,
        snapshot_id,
        ["spec", "component", "characteristic", "qty_per_1000"],
        models.SpecLine.is_effective.is_(True),
    )
    plan = _frame(session, models.SalesPlanRow, snapshot_id, ["item", "month", "qty"])
    orders = _frame(
        session,
        models.ProductionOrder,
        snapshot_id,
        ["number", "item", "qty", "stage", "nfp", "nfp_characteristic"],
    )
    return PlanningData(items=items, stock=stock, specs=specs, plan=plan, orders=orders)


def _jsonable(df: pd.DataFrame) -> list[dict]:
    out = []
    for rec in df.to_dict("records"):
        row = {}
        for k, v in rec.items():
            if isinstance(v, float) and math.isnan(v):
                v = None
            elif isinstance(v, date):
                v = v.isoformat()
            elif v is pd.NaT:
                v = None
            row[k] = v
        out.append(row)
    return out


def run_stage2(session: Session, snapshot_id: int, horizon_months: int, calc_date: date) -> models.PlanRun:
    params = Stage2Params(horizon_months=horizon_months, calc_date=calc_date)
    result: Stage2Result = calculate_stage2(load_planning_data(session, snapshot_id), params)
    run = models.PlanRun(
        snapshot_id=snapshot_id,
        stage=2,
        params={"horizon_months": horizon_months, "calc_date": calc_date.isoformat()},
        summary=result.summary,
        lines=_jsonable(result.lines),
        materials=_jsonable(result.materials),
        nfp=_jsonable(result.nfp),
    )
    session.add(run)
    session.commit()
    return run
