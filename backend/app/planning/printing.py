"""Расход печатных материалов по полным месяцам плана продаж."""

import re

from app.importers.specs import analog_key
from app.planning.calendar import add_months
from app.reference.warehouses import GP_ROLES, MATERIALS


def material_group(name):
    if re.match(r"^(?:пачк|[бпс]-\d)", name, re.I):
        return "Пачки"
    for prefix, group in [("конверт", "Конверты"), ("ярлык", "Ярлыки"), ("вкладыш", "Вкладыши")]:
        if name.lower().startswith(prefix):
            return group
    return None


def print_requirements(data, calc_date, horizon, include_gp=False):
    start = calc_date.replace(day=1)
    months = [add_months(start, offset) for offset in range(1, horizon + 1)]
    plan = data.plan[data.plan.month.isin(months)]
    items = data.items[data.items.in_scope == True][["name", "spec"]]  # noqa: E712
    items = items[~items.name.str.contains(r"будь\s+здоров", case=False, na=False)]
    sales = plan.groupby("item").qty.sum()
    planned = items.merge(sales, left_on="name", right_index=True)
    missing_specs = planned.loc[~planned.spec.isin(data.specs.spec) & (planned.qty > 0), "name"].tolist()
    specs = data.specs.copy()
    specs["group"] = specs.component.map(material_group)
    printed = specs.component_kind.fillna("").isin(["", "Печатные материалы для производства"])
    specs = specs[printed & specs.group.notna() & (specs.qty_per_1000 > 0)]
    norms = items.merge(specs, on="spec")
    norms["key"] = norms.component.map(analog_key)
    norms = norms.groupby(["key", "name", "component", "group"], as_index=False).qty_per_1000.sum()
    future_plan = data.plan[data.plan.month >= months[0]]
    planned_months = set(future_plan.month)
    calendar = []
    period = months[0]
    while planned_months and period <= max(planned_months):
        calendar.append(period)
        period = add_months(period, 1)
    usage = norms.merge(future_plan, left_on="name", right_on="item", how="left")
    usage["demand"] = usage.qty.fillna(0) * usage.qty_per_1000 / 1000
    stock = data.stock[data.stock.role == MATERIALS]
    balances = stock.groupby(stock.name.map(analog_key)).available.sum()
    gp_by_material = {}
    if include_gp:
        gp = data.stock[data.stock.role.isin(GP_ROLES) & ~data.stock.is_defect]
        available = gp.groupby("item").available.sum().clip(lower=0)
        credited = norms[norms.group.isin(["Пачки", "Конверты", "Ярлыки"])].copy()
        credited["per_unit"] = credited.qty_per_1000 / 1000
        credited.loc[credited.group == "Пачки", "per_unit"] = 1
        credited["qty"] = credited.name.map(available).fillna(0) * credited.per_unit
        gp_by_material = credited.groupby("key").qty.sum()
    rows = []
    for key, parts in usage.groupby("key"):
        horizon_parts = parts[parts.month.isin(months)]
        monthly = parts.groupby("month").demand.sum()
        breakdown = horizon_parts.groupby(["name", "qty_per_1000"], as_index=False).agg(
            sales=("qty", "sum"), demand=("demand", "sum")
        )
        rows.append(
            dict(
                key=key,
                name=parts.component.iloc[0],
                group=parts.group.iloc[0],
                demand=round(float(horizon_parts.demand.sum()), 6),
                products=breakdown[breakdown.sales > 0].to_dict("records"),
                future=[float(monthly.get(m, 0)) if m in planned_months else None for m in calendar],
                monthly=monthly.reindex(months, fill_value=0).round(6).tolist(),
                gp_stock=float(gp_by_material.get(key, 0)),
                stock=float(balances.get(key, 0)) + float(gp_by_material.get(key, 0)),
            )
        )
    return dict(
        months=months,
        calendar=calendar,
        target=add_months(start, 2),
        rows=rows,
        missing_specs=missing_specs,
        missing_months=[m for m in months if m not in set(plan.month)],
    )
