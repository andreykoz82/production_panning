"""Расход печатных материалов по полным месяцам плана продаж."""

import re

from app.importers.specs import analog_key
from app.planning.calendar import add_months
from app.reference.warehouses import MATERIALS


def material_group(name):
    if re.match(r"^(?:пачк|[бпс]-\d)", name, re.I):
        return "Пачки"
    for prefix, group in [("конверт", "Конверты"), ("ярлык", "Ярлыки"), ("вкладыш", "Вкладыши")]:
        if name.lower().startswith(prefix):
            return group
    return None


def print_requirements(data, calc_date, horizon):
    start = calc_date.replace(day=1)
    months = [add_months(start, offset) for offset in range(1, horizon + 1)]
    plan = data.plan[data.plan.month.isin(months)]
    items = data.items[data.items.in_scope == True][["name", "spec"]]  # noqa: E712
    sales = plan.groupby("item").qty.sum()
    planned = items.merge(sales, left_on="name", right_index=True)
    missing_specs = planned.loc[~planned.spec.isin(data.specs.spec) & (planned.qty > 0), "name"].tolist()
    specs = data.specs.copy()
    specs["group"] = specs.component.map(material_group)
    printed = specs.component_kind.fillna("").isin(["", "Печатные материалы для производства"])
    specs = specs[printed & specs.group.notna() & (specs.qty_per_1000 > 0)]
    usage = items.merge(specs, on="spec").merge(sales, left_on="name", right_index=True, how="left")
    usage["key"] = usage.component.map(analog_key)
    usage["demand"] = usage.qty.fillna(0) * usage.qty_per_1000 / 1000
    stock = data.stock[data.stock.role == MATERIALS]
    balances = stock.groupby(stock.name.map(analog_key)).available.sum()
    rows = []
    for key, parts in usage.groupby("key"):
        rows.append(
            dict(
                key=key,
                name=parts.component.iloc[0],
                group=parts.group.iloc[0],
                demand=round(float(parts.demand.sum()), 6),
                stock=float(balances.get(key, 0)),
            )
        )
    return dict(
        months=months,
        target=add_months(start, 2),
        rows=rows,
        missing_specs=missing_specs,
        missing_months=[m for m in months if m not in set(plan.month)],
    )
