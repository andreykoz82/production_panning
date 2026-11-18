"""Сохранение результата импорта в БД."""

import math

import pandas as pd
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app import models
from app.importers.loader import ImportResult


def _records(df: pd.DataFrame, columns: list[str], snapshot_id: int) -> list[dict]:
    out = []
    for rec in df[columns].to_dict("records"):
        row = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in rec.items()}
        row["snapshot_id"] = snapshot_id
        out.append(row)
    return out


def save_snapshot(session: Session, result: ImportResult, source: str) -> models.ImportSnapshot:
    snap = models.ImportSnapshot(source=source, files=result.files, summary=result.summary)
    session.add(snap)
    session.flush()
    sid = snap.id

    item_cols = [
        "name",
        "abc",
        "mass_g",
        "line_group",
        "form",
        "kind",
        "gtin",
        "nfp",
        "nfp_source",
        "purpose",
        "printed_material",
        "in_scope",
        "spec",
        "spec_method",
        "spec_score",
        "spec_needs_confirmation",
        "min_series",
        "max_series",
        "stm",
    ]
    items = result.items.astype(object).where(result.items.notna(), None)
    session.execute(insert(models.Item), _records(items, item_cols, sid))

    stock_cols = [
        "warehouse",
        "name",
        "item",
        "characteristic",
        "series",
        "expiry",
        "purpose",
        "packing_allowed",
        "on_hand",
        "reserved",
        "to_ship",
        "available",
        "is_defect",
    ]
    session.execute(insert(models.StockRow), _records(result.stock, stock_cols, sid))

    eff = result.specs_effective[["row_id", "analogs"]]
    specs = result.specs.merge(eff, on="row_id", how="left", indicator=True)
    specs["is_effective"] = specs["_merge"] == "both"
    spec_cols = [
        "spec",
        "status",
        "version",
        "component",
        "characteristic",
        "qty_per_1000",
        "is_effective",
        "analogs",
    ]
    session.execute(insert(models.SpecLine), _records(specs, spec_cols, sid))

    plan_cols = ["name", "item", "month", "qty", "amount", "source"]
    session.execute(insert(models.SalesPlanRow), _records(result.sales_plan, plan_cols, sid))

    if len(result.orders):
        order_cols = ["number", "stage", "name", "item", "qty", "qty_plan", "qty_done", "status", "line_1c"]
        order_cols += ["line_code", "started_at", "production_date", "doc_date", "nfp", "nfp_characteristic"]
        orders = result.orders.astype(object).where(result.orders.notna(), None)
        session.execute(insert(models.ProductionOrder), _records(orders, order_cols, sid))

    session.execute(
        insert(models.ImportIssue),
        [{**i.as_dict(), "snapshot_id": sid} for i in result.issues],
    )
    session.commit()
    return snap
