"""Анализ сроков годности ГП по последнему снимку и графику производства."""

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.planning.shelf_life import ItemResult, ShelfLifeParams, analyze
from app.reference.bottling import is_bottling
from app.reference.lines import GP_CERTIFICATION_DAYS
from app.reference.stm import is_stm
from app.services.schedule import latest_snapshot_id

STATUS_ILLIQUID = "Неликвид есть"
STATUS_RISK = "Уйдёт в неликвид"
STATUS_SHORT = "Не хватит"
STATUS_OK = "Норма"


def _frame(session: Session, model, snapshot_id: int, cols: list[str]) -> pd.DataFrame:
    rows = session.execute(
        select(*[getattr(model, c) for c in cols]).where(model.snapshot_id == snapshot_id)
    ).all()
    return pd.DataFrame(rows, columns=cols)


def shelf_life_analysis(session: Session, p: ShelfLifeParams, item: str | None = None) -> dict:
    snapshot_id = latest_snapshot_id(session)
    if not snapshot_id:
        raise LookupError("Нет снимка данных — сначала загрузите выгрузки 1С")
    items = _frame(session, models.Item, snapshot_id, ["name", "in_scope", "stm", "min_series", "max_series"])
    # СТМ производится только по письму клиента — в анализ не входит
    items = items[items["in_scope"] & ~items["stm"].astype(bool)].assign(bottling=False)
    lots_all = _frame(
        session,
        models.GpLot,
        snapshot_id,
        [
            "name",
            "item",
            "series",
            "production_date",
            "expiry",
            "shelf_life_months",
            "brand",
            "qty",
            "report_date",
        ],
    )
    if lots_all.empty:
        raise LookupError(
            "В снимке нет отчёта «Остатки ГП со сроками годности» — добавьте его в папку и загрузите данные"
        )
    plan = _frame(session, models.SalesPlanRow, snapshot_id, ["name", "item", "month", "qty"])
    if p.bottling:
        items, lots_all, plan = _with_bottling(items, lots_all, plan)
    lots = lots_all[lots_all["item"].isin(items["name"])]

    orders = []
    for t in session.scalars(select(models.ScheduleTask).where(models.ScheduleTask.stage == 2)):
        produced = t.end.date() if t.end else p.calc_date
        available = t.available_from or produced + timedelta(days=GP_CERTIFICATION_DAYS)
        orders.append(
            {"item": t.item, "number": t.number, "qty": t.qty, "produced": produced, "available": available}
        )

    # выпущено, но ещё не оприходовано на склад ГП: серия уже есть, продаём после сертификации
    transit = session.scalars(
        select(models.GpRelease).where(
            models.GpRelease.snapshot_id == snapshot_id, models.GpRelease.in_transit.is_(True)
        )
    )
    for r in transit:
        made = r.production_date or p.calc_date
        orders.append(
            {
                "item": r.item,
                "number": f"{r.series or r.number} · не оприходовано",
                "qty": r.qty,
                "produced": made,
                "available": max(p.calc_date, made + timedelta(days=GP_CERTIFICATION_DAYS)),
                "expiry": r.expiry,
            }
        )

    result = analyze(items, lots, plan, orders, p)
    results: list[ItemResult] = result["results"]

    bottling = set(items.loc[items["bottling"], "name"])
    for r in results:
        r.bottling = r.item in bottling
    rows = [_item_row(r) for r in results]
    rows.sort(key=lambda r: (-(r["illiquid_now"] + r["illiquid_forecast"]), r["item"]))
    detail = next((r for r in results if r.item == item), None) if item else None
    report_date = lots_all["report_date"].dropna().max()
    return {
        "params": {
            "calc_date": p.calc_date,
            "horizon_months": p.horizon_months,
            "fulfillment_pct": p.fulfillment_pct,
            "threshold_pct": p.threshold_pct,
            "replenish": p.replenish,
            "cover_months": p.cover_months,
            "bottling": p.bottling,
        },
        "report_date": report_date if pd.notna(report_date) else None,
        "summary": _summary(results, lots_all, lots),
        "months": _months(results),
        "items": rows,
        "detail": _detail(detail, p) if detail else None,
    }


def _with_bottling(
    items: pd.DataFrame, lots: pd.DataFrame, plan: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Розлив: позиции нет в справочнике ГП — ссылка на ГП по точному наименованию в остатках и плане."""
    lot_names = lots.loc[lots["item"].isna(), "name"]
    free_plan = plan[plan["item"].isna()]
    plan_qty = free_plan.groupby("name")["qty"].sum()
    names = sorted(
        n
        for n in set(lot_names) | set(plan_qty.index)
        if is_bottling(n) and not is_stm(n) and (n in set(lot_names) or plan_qty.get(n, 0) > 0)
    )
    if not names:
        return items, lots, plan
    lots = lots.copy()
    plan = plan.copy()
    lots.loc[lots["item"].isna() & lots["name"].isin(names), "item"] = lots["name"]
    plan.loc[plan["item"].isna() & plan["name"].isin(names), "item"] = plan["name"]
    extra = pd.DataFrame({"name": names, "in_scope": True, "stm": False, "bottling": True})
    extra["min_series"] = extra["max_series"] = None
    return pd.concat([items, extra], ignore_index=True), lots, plan


def _status(r: ItemResult) -> str:
    if r.illiquid_now > 0:
        return STATUS_ILLIQUID
    if r.illiquid_forecast > 0:
        return STATUS_RISK
    if r.lost_sales > max(1.0, 0.01 * r.demand):
        return STATUS_SHORT
    return STATUS_OK


def _item_row(r: ItemResult) -> dict:
    return {
        "item": r.item,
        "bottling": r.bottling,
        "status": _status(r),
        "shelf_life_months": r.shelf_life_months,
        "stock": round(r.stock),
        "lots": sum(1 for lot in r.lots if lot.source == "склад"),
        "illiquid_now": round(r.illiquid_now),
        "illiquid_forecast": round(r.illiquid_forecast),
        "illiquid_total": round(r.illiquid_now + r.illiquid_forecast),
        "first_illiquid": r.first_illiquid,
        "monthly_demand": round(r.monthly_demand),
        "coverage_months": round(r.stock / r.monthly_demand, 1) if r.monthly_demand else None,
        "sales": round(r.sales),
        "demand": round(r.demand),
        "lost_sales": round(r.lost_sales),
        "produced_orders": round(r.produced_orders),
        "produced_planned": round(r.produced_planned),
    }


def _summary(results: list[ItemResult], lots_all: pd.DataFrame, lots: pd.DataFrame) -> dict:
    return {
        "items": len(results),
        "items_bottling": sum(1 for r in results if r.bottling),
        "lots": int(len(lots)),
        "lots_out_of_scope": int(len(lots_all) - len(lots)),
        "stock": round(sum(r.stock for r in results)),
        "illiquid_now": round(sum(r.illiquid_now for r in results)),
        "illiquid_forecast": round(sum(r.illiquid_forecast for r in results)),
        "items_illiquid_now": sum(1 for r in results if r.illiquid_now > 0),
        "items_at_risk": sum(1 for r in results if r.illiquid_forecast > 0),
        "sales": round(sum(r.sales for r in results)),
        "demand": round(sum(r.demand for r in results)),
        "lost_sales": round(sum(r.lost_sales for r in results)),
        "produced_orders": round(sum(r.produced_orders for r in results)),
        "produced_planned": round(sum(r.produced_planned for r in results)),
    }


def _months(results: list[ItemResult]) -> list[dict]:
    total: dict[date, dict] = {}
    for r in results:
        for m, cell in r.months.items():
            agg = total.setdefault(m, {})
            for k, v in cell.items():
                agg[k] = agg.get(k, 0.0) + v
    return [{"month": m, **{k: round(v) for k, v in total[m].items()}} for m in sorted(total)]


def _detail(r: ItemResult, p: ShelfLifeParams) -> dict:
    threshold = p.threshold_pct / 100
    # сначала серии с наибольшим неликвидом, дальше — по дате поступления
    lots = sorted(r.lots, key=lambda lot: (-round(lot.illiquid_qty), lot.available, lot.expiry))
    return {
        "item": r.item,
        "row": _item_row(r),
        "points": r.points,
        "months": [{"month": m, **{k: round(v) for k, v in c.items()}} for m, c in sorted(r.months.items())],
        "lots": [
            {
                "series": lot.series,
                "source": lot.source,
                "qty": round(lot.initial),
                "production": lot.production,
                "available": lot.available,
                "expiry": lot.expiry,
                "illiquid_from": lot.illiquid_from(threshold),
                "residual_pct": round(lot.residual_pct(p.calc_date), 1),
                "sold": round(lot.sold),
                "sold_out": lot.sold_out,
                "illiquid_qty": round(lot.illiquid_qty),
                "illiquid_date": lot.illiquid_date,
                "left": round(lot.qty),
            }
            for lot in lots
        ],
    }
