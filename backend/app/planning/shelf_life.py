"""Анализ сроков годности ГП: что успеем продать, а что уйдёт в неликвид.

Модель по дням для каждого ГП:
- запас — серии со склада ГП и опта (дата производства, годен до, количество);
- серия неликвидна, когда остаточный срок годности опускается ниже порога
  (по умолчанию 70 %): с даты «годен до − порог × срок годности»;
- продажи — план продаж × процент выполнения, равномерно по дням месяца;
  отгружаем FEFO — сначала серии с меньшим сроком годности, неликвид не продаём;
- производство — открытые этапы 2 ступени (дата окончания по графику + сертификация)
  и, по желанию, будущая наработка: когда ликвидного запаса с учётом уже идущего производства
  не хватает на время производства, выпускаем серию на N месяцев продаж
  (не меньше минимальной серии). СТМ — по прогнозу, как если бы письма клиента пришли по плану.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

DEFAULT_THRESHOLD_PCT = 70.0
DEFAULT_SHELF_LIFE_MONTHS = 36.0
LEAD_DAYS = 14  # от решения о фасовке до продажи: производство + сертификация
SAFETY_DAYS = 7  # наработку запускаем с запасом в неделю продаж
CHART_STEP_DAYS = 7


@dataclass
class ShelfLifeParams:
    calc_date: date
    horizon_months: int = 12
    fulfillment_pct: float = 100.0  # процент выполнения плана продаж
    threshold_pct: float = DEFAULT_THRESHOLD_PCT  # ниже — неликвид
    replenish: bool = True  # учитывать будущую наработку
    cover_months: float = 3.0  # на сколько месяцев продаж нарабатываем серию
    bottling: bool = True  # включать розлив (Стоматофит, Бронхофитол, НЮДА)


@dataclass
class Lot:
    series: str
    qty: float
    production: date
    expiry: date
    available: date  # с какой даты можно продавать
    source: str  # «склад», «заказ КЛ00-…», «наработка»
    initial: float = 0.0
    sold: float = 0.0
    illiquid_qty: float = 0.0
    illiquid_date: date | None = None
    sold_out: date | None = None

    def __post_init__(self):
        self.initial = self.qty

    def illiquid_from(self, threshold: float) -> date:
        span = (self.expiry - self.production).days
        return self.expiry - timedelta(days=math.ceil(span * threshold))

    def residual_pct(self, day: date) -> float:
        span = (self.expiry - self.production).days or 1
        return max(0.0, min(100.0, (self.expiry - day).days / span * 100))


@dataclass
class ItemResult:
    item: str
    stm: bool
    shelf_life_months: float | None
    lots: list[Lot]
    stock: float
    illiquid_now: float
    illiquid_forecast: float  # уйдёт в неликвид в горизонте (кроме уже неликвидного)
    first_illiquid: date | None
    sales: float
    demand: float
    lost_sales: float
    produced_orders: float
    produced_planned: float
    monthly_demand: float
    points: list[dict] = field(default_factory=list)
    months: dict[date, dict] = field(default_factory=dict)
    bottling: bool = False


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _month(d: date) -> date:
    return d.replace(day=1)


def simulate_item(
    item: str,
    lots: pd.DataFrame,
    plan: dict[date, float],
    orders: list[dict],
    p: ShelfLifeParams,
    *,
    stm: bool = False,
    min_series: float | None = None,
    shelf_life: float | None = None,
) -> ItemResult:
    threshold = p.threshold_pct / 100
    end = add_months(p.calc_date, p.horizon_months)
    shelf = shelf_life or (lots["shelf_life_months"].dropna().max() if len(lots) else None) or None
    shelf_days = round((shelf or DEFAULT_SHELF_LIFE_MONTHS) * 30.4375)

    all_lots: list[Lot] = []
    for r in lots.itertuples(index=False):
        prod = r.production_date if isinstance(r.production_date, date) else None
        if prod is None:
            prod = r.expiry - timedelta(days=shelf_days)
        all_lots.append(Lot(str(r.series or ""), float(r.qty), prod, r.expiry, p.calc_date, "склад"))
    stock = sum(lot.qty for lot in all_lots)

    # уже неликвидное на дату расчёта
    illiquid_now = 0.0
    for lot in all_lots:
        if lot.illiquid_from(threshold) <= p.calc_date:
            lot.illiquid_qty, lot.illiquid_date, lot.qty = lot.qty, p.calc_date, 0.0
            illiquid_now += lot.illiquid_qty

    # открытые этапы: серия выпускается в день окончания, продаётся после сертификации
    pending: list[Lot] = []
    for o in orders:
        made = o["produced"]
        expiry = o.get("expiry") or made + timedelta(days=shelf_days)
        pending.append(Lot(o["number"], float(o["qty"]), made, expiry, o["available"], "заказ"))
    produced_orders = sum(lot.qty for lot in pending if lot.available < end)

    def daily(d: date) -> float:
        return plan.get(_month(d), 0.0) * p.fulfillment_pct / 100 / calendar.monthrange(d.year, d.month)[1]

    def demand_between(a: date, b: date) -> float:
        total, d = 0.0, a
        while d < b:
            month_end = min(b, add_months(_month(d), 1))
            total += daily(d) * (month_end - d).days
            d = month_end
        return total

    months_in_plan = [m for m in plan if _month(p.calc_date) <= m < end]
    monthly_demand = (
        sum(plan[m] for m in months_in_plan) / len(months_in_plan) * p.fulfillment_pct / 100
        if months_in_plan
        else 0.0
    )

    res = ItemResult(
        item=item,
        stm=stm,
        shelf_life_months=shelf,
        lots=all_lots,
        stock=stock,
        illiquid_now=illiquid_now,
        illiquid_forecast=0.0,
        first_illiquid=None,
        sales=0.0,
        demand=0.0,
        lost_sales=0.0,
        produced_orders=produced_orders,
        produced_planned=0.0,
        monthly_demand=monthly_demand,
    )

    def month_cell(d: date) -> dict:
        return res.months.setdefault(
            _month(d),
            {"sales": 0.0, "demand": 0.0, "orders": 0.0, "planned": 0.0, "illiquid": 0.0, "lost": 0.0},
        )

    illiquid_total = illiquid_now
    period = {"arrived": 0.0, "sold": 0.0, "lost": 0.0}  # с прошлой точки графика
    res.points.append(_point(p.calc_date, all_lots, illiquid_total, period))
    d = p.calc_date
    batch = 0
    while d < end:
        # приход: заказы и наработка, доступные к продаже с этого дня
        for lot in [x for x in pending if x.available <= d]:
            pending.remove(lot)
            all_lots.append(lot)
            month_cell(d)["orders" if lot.source == "заказ" else "planned"] += lot.qty
            period["arrived"] += lot.qty
            if lot.source == "наработка":
                res.produced_planned += lot.qty

        # стало неликвидом
        for lot in all_lots:
            if lot.qty > 0 and lot.illiquid_date is None and lot.illiquid_from(threshold) <= d:
                lot.illiquid_qty, lot.illiquid_date, lot.qty = lot.qty, d, 0.0
                res.illiquid_forecast += lot.illiquid_qty
                illiquid_total += lot.illiquid_qty
                month_cell(d)["illiquid"] += lot.illiquid_qty
                res.first_illiquid = res.first_illiquid or d

        # будущая наработка: запаса, который останется ликвидным, и идущего производства
        # не хватит на время производства (+ неделя запаса)
        if p.replenish and daily(d) > 0:
            horizon = d + timedelta(days=LEAD_DAYS)
            liquid = sum(
                lot.qty for lot in all_lots if lot.qty > 0 and lot.illiquid_from(threshold) > horizon
            )
            coming = sum(lot.qty for lot in pending)
            if liquid + coming < demand_between(d, horizon + timedelta(days=SAFETY_DAYS)):
                arrive = d + timedelta(days=LEAD_DAYS)
                qty = demand_between(arrive, arrive + timedelta(days=round(p.cover_months * 30.4375)))
                qty = math.ceil(max(qty, min_series or 0.0))  # больше максимальной — несколько серий
                if qty > 0:
                    batch += 1
                    made = arrive - timedelta(days=7)
                    pending.append(
                        Lot(
                            f"наработка {batch}",
                            qty,
                            made,
                            made + timedelta(days=shelf_days),
                            arrive,
                            "наработка",
                        )
                    )

        # продажи FEFO из ликвидного
        need = daily(d)
        res.demand += need
        cell = month_cell(d)
        cell["demand"] += need
        for lot in sorted((x for x in all_lots if x.qty > 0), key=lambda x: (x.expiry, x.production)):
            if need <= 0:
                break
            take = min(lot.qty, need)
            lot.qty -= take
            lot.sold += take
            need -= take
            res.sales += take
            cell["sales"] += take
            period["sold"] += take
            if lot.qty <= 1e-9:
                lot.qty, lot.sold_out = 0.0, d
        if need > 0:
            res.lost_sales += need
            cell["lost"] += need
            period["lost"] += need
        cell["liquid_end"] = sum(lot.qty for lot in all_lots if lot.qty > 0)
        cell["illiquid_end"] = illiquid_total

        if (d - p.calc_date).days % CHART_STEP_DAYS == CHART_STEP_DAYS - 1:
            res.points.append(_point(d, all_lots, illiquid_total, period))
        d += timedelta(days=1)
    if any(period.values()):
        res.points.append(_point(end, all_lots, illiquid_total, period))
    res.lots = all_lots + pending
    return res


def _point(d: date, lots: list[Lot], illiquid_total: float, period: dict) -> dict:
    """Точка графика на конец недели: запас и что произошло за неделю."""
    point = {
        "date": d,
        "liquid": round(sum(lot.qty for lot in lots if lot.qty > 0)),
        "illiquid": round(illiquid_total),
        **{k: round(v) for k, v in period.items()},
    }
    for k in period:
        period[k] = 0.0
    return point


def analyze(
    items: pd.DataFrame,
    lots: pd.DataFrame,
    plan: pd.DataFrame,
    orders: list[dict],
    p: ShelfLifeParams,
) -> dict:
    """items: name, stm, min_series, max_series; lots: item + колонки серии; plan: item, month, qty;
    orders: item, number, qty, produced, available."""
    plan_by_item: dict[str, dict[date, float]] = {}
    for r in plan.itertuples(index=False):
        if r.item:
            m = _month(r.month)
            plan_by_item.setdefault(r.item, {})[m] = plan_by_item.get(r.item, {}).get(m, 0.0) + float(r.qty)
    lots_by_item = dict(list(lots.groupby("item"))) if len(lots) else {}
    orders_by_item: dict[str, list[dict]] = {}
    for o in orders:
        orders_by_item.setdefault(o["item"], []).append(o)

    results = []
    for it in items.itertuples(index=False):
        item_lots = lots_by_item.get(it.name, lots.iloc[0:0])
        item_plan = plan_by_item.get(it.name, {})
        if item_lots.empty and not item_plan and it.name not in orders_by_item:
            continue
        results.append(
            simulate_item(
                it.name,
                item_lots,
                item_plan,
                orders_by_item.get(it.name, []),
                p,
                stm=bool(getattr(it, "stm", False)),
                min_series=_num(getattr(it, "min_series", None)),
            )
        )
    return {"params": p, "results": results}


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 and not math.isnan(f) else None
