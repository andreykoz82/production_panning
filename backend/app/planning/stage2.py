"""Расчёт потребности 2 ступени: что и сколько фасовать.

Правила (согласованы 16.11.2026):
1. Горизонт N месяцев задаёт пользователь. Продажи на горизонт = план текущего месяца × доля
   оставшихся рабочих дней + план следующих N−1 месяцев целиком. Страхового запаса нет.
2. К фасовке = продажи на горизонт − запас ГП (склад ГП + склад оптовой торговли, «Доступно», без брака)
   − открытые заказы 2 ступени. Не меньше минимальной партии (выпуск линии за 1 ч).
3. Приоритет — месяц, когда прогнозный запас ГП уходит в минус; при равенстве A → B → C.
4. НФП: партии с той же фракцией (характеристика из спецификации), целевым назначением ГП
   и «Фасовка = Да». Покупной НФП (есть только на складе лексырья) — по наименованию.
   НФП на карантине доступен через 5 рабочих дней и в «можно выпустить сейчас» не входит.
5. Материалы — по действующей спецификации; аналоги (обычный / импорт) суммируются.
   Отклонение до 10 % (на складе ≥ 90 % потребности) дефицитом не считается (17.11.2026).
6. НФП и общие материалы распределяются по позициям в порядке приоритета.
7. Задание 1 ступени по НФП округляется до 100 кг (17.11.2026).
8. СТМ («ТМ Будь здоров») производится только по письму клиента: план по СТМ — прогноз,
   а не задание. СТМ идёт после всех наших позиций (получает остаток НФП и упаковки),
   в сводку, дефицит материалов и задание 1 ступени не входит (18.11.2026).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.importers.specs import analog_key
from app.planning.calendar import add_months, add_workdays, month_end, workdays, workdays_in_month
from app.reference import warehouses as wh
from app.reference.lines import NFP_QUARANTINE_WORKDAYS, STAGE2_GROUPS, lines_in_group
from app.reference.stm import is_stm

ABC_ORDER = {"A": 0, "B": 1, "C": 2}
MATERIAL_TOLERANCE = 0.10  # нехватка материала до 10 % от потребности — не дефицит
NFP_ROUND_KG = 100
STOCKOUT_LOOKAHEAD_MONTHS = 24

STATUS_NOT_NEEDED = "Не требуется"
STATUS_FULL = "Можно фасовать"
STATUS_PARTIAL = "Частично"
STATUS_BLOCKED = "Нельзя"
STATUS_NO_SPEC = "Нет данных"


@dataclass
class PlanningData:
    """Снимок данных для расчёта (из ImportResult или из БД)."""

    items: pd.DataFrame  # name, abc, line_group, nfp, purpose, in_scope, spec
    stock: (
        pd.DataFrame
    )  # warehouse, name, item, characteristic, purpose, packing_allowed, available, is_defect
    specs: pd.DataFrame  # действующие версии: spec, component, characteristic, qty_per_1000
    plan: pd.DataFrame  # item, month, qty
    orders: pd.DataFrame  # number, item, qty, stage [, nfp, nfp_characteristic — для 1 ступени]


@dataclass
class Stage2Params:
    horizon_months: int
    calc_date: date

    def __post_init__(self):
        if not 1 <= self.horizon_months <= 24:
            raise ValueError("Горизонт — от 1 до 24 месяцев")


@dataclass
class Stage2Result:
    params: Stage2Params
    lines: pd.DataFrame
    materials: pd.DataFrame
    nfp: pd.DataFrame
    month_factors: dict[str, float] = field(default_factory=dict)
    warehouses: dict[str, list[str]] = field(default_factory=dict)

    @property
    def summary(self) -> dict:
        all_lines = self.lines
        stm = all_lines[all_lines["stm"]] if "stm" in all_lines.columns else all_lines.iloc[0:0]
        lines = all_lines[~all_lines.index.isin(stm.index)]
        needed = lines[lines["need"] > 0]
        return {
            "horizon_months": self.params.horizon_months,
            "calc_date": self.params.calc_date.isoformat(),
            "items": int(len(lines)),
            "items_needed": int(len(needed)),
            "items_full": int((lines["status"] == STATUS_FULL).sum()),
            "items_partial": int((lines["status"] == STATUS_PARTIAL).sum()),
            "items_blocked": int((lines["status"] == STATUS_BLOCKED).sum()),
            "need_units": float(needed["need"].sum()),
            "feasible_units": float(lines["feasible"].sum()),
            "materials_short": int((self.materials["shortage"] > 0).sum()) if len(self.materials) else 0,
            "nfp_shortage_kg": float(self.nfp["shortage_kg"].sum()) if len(self.nfp) else 0.0,
            "nfp_stage1_orders_kg": float(self.nfp["stage1_orders_kg"].sum()) if len(self.nfp) else 0.0,
            "nfp_uncovered_kg": float(self.nfp["uncovered_kg"].sum()) if len(self.nfp) else 0.0,
            "stm_items": int(len(stm)),
            "stm_needed": int((stm["need"] > 0).sum()),
            "stm_need_units": float(stm["need"].sum()),
            "stm_feasible_units": float(stm["feasible"].sum()),
            "month_factors": self.month_factors,
            "warehouses": self.warehouses,
        }


def _horizon_factors(calc_date: date, horizon: int) -> dict[date, float]:
    """Доля плана каждого месяца, входящая в горизонт. Текущий месяц — по оставшимся рабочим дням."""
    first = calc_date.replace(day=1)
    total = workdays_in_month(first)
    left = workdays(calc_date, month_end(calc_date))
    factors = {first: left / total if total else 0.0}
    for i in range(1, horizon):
        factors[add_months(first, i)] = 1.0
    return factors


def _min_batch(group: str | None) -> float:
    lines = lines_in_group(group) if group else []
    return min(line.min_batch for line in lines) if lines else 0.0


def _stockout_month(start_stock: float, plan_by_month: dict[date, float], calc_date: date) -> date | None:
    """Первый месяц, в котором прогнозный запас ГП уходит в минус."""
    first = calc_date.replace(day=1)
    left_share = workdays(calc_date, month_end(calc_date)) / max(workdays_in_month(first), 1)
    stock = start_stock
    for i in range(STOCKOUT_LOOKAHEAD_MONTHS):
        m = add_months(first, i)
        stock -= plan_by_month.get(m, 0.0) * (left_share if i == 0 else 1.0)
        if stock < 0:
            return m
    return None


class _Pool:
    """Остатки, которые распределяются между позициями по приоритету."""

    def __init__(self, amounts: dict):
        self.left = dict(amounts)

    def get(self, key) -> float:
        return max(self.left.get(key, 0.0), 0.0)

    def take(self, key, qty: float) -> None:
        self.left[key] = self.get(key) - qty


def calculate_stage2(data: PlanningData, params: Stage2Params) -> Stage2Result:
    calc_date = params.calc_date
    factors = _horizon_factors(calc_date, params.horizon_months)
    quarantine_ready = add_workdays(calc_date, NFP_QUARANTINE_WORKDAYS)

    items = data.items[data.items["in_scope"]].copy()
    plan = data.plan[data.plan["item"].notna()]
    plan_by_item: dict[str, dict[date, float]] = {}
    for item, month, qty in plan[["item", "month", "qty"]].itertuples(index=False):
        plan_by_item.setdefault(item, {})[month] = plan_by_item.get(item, {}).get(month, 0.0) + qty

    stock = data.stock if "role" in data.stock.columns else wh.with_roles(data.stock)
    gp = stock[stock["role"].isin(wh.GP_ROLES) & ~stock["is_defect"] & stock["item"].notna()]
    gp_stock = gp.groupby("item")["available"].sum()
    gp_cert = gp[gp["role"] == wh.GP_CERT].groupby("item")["available"].sum()
    orders = data.orders[(data.orders["stage"] == 2) & data.orders["item"].notna()]
    open_orders = orders.groupby("item")["qty"].sum()

    # --- НФП: пулы по (наименование, фракция, назначение)
    nfp_rows = stock[stock["role"] == wh.NFP]
    key_cols = ["name", "characteristic", "purpose"]
    released = nfp_rows[nfp_rows["packing_allowed"] == True]  # noqa: E712 — None означает «не указано»
    unreleased = nfp_rows[nfp_rows["packing_allowed"] != True]  # noqa: E712
    quarantine = stock[stock["role"] == wh.NFP_QUARANTINE]
    nfp_pool = _Pool(released.groupby(key_cols, dropna=False)["available"].sum().to_dict())
    nfp_unreleased = unreleased.groupby(key_cols, dropna=False)["available"].sum().to_dict()
    nfp_quarantine = quarantine.groupby(key_cols, dropna=False)["available"].sum().to_dict()
    nfp_names_on_nfp_wh = set(nfp_rows["name"]) | set(quarantine["name"])
    raw = stock[stock["role"] == wh.RAW]
    purchased_pool = _Pool(raw.groupby("name")["available"].sum().to_dict())

    # --- Материалы: пулы по ключу аналогов
    mats = stock[stock["role"] == wh.MATERIALS]
    mat_pool = _Pool(mats.assign(k=mats["name"].map(analog_key)).groupby("k")["available"].sum().to_dict())
    mat_names: dict[str, str] = {}

    specs = data.specs
    spec_by_name = {s: g for s, g in specs.groupby("spec")}

    # --- Строки потребности
    rows = []
    for it in items.itertuples(index=False):
        p = plan_by_item.get(it.name, {})
        plan_h = sum(p.get(m, 0.0) * f for m, f in factors.items())
        stock_gp = float(gp_stock.get(it.name, 0.0))
        orders_q = float(open_orders.get(it.name, 0.0))
        raw_need = plan_h - stock_gp - orders_q
        mb = _min_batch(it.line_group)
        need = 0.0 if raw_need <= 0 else float(max(math.ceil(raw_need), math.ceil(mb)))
        rows.append(
            {
                "item": it.name,
                "stm": is_stm(it.name),
                "abc": it.abc,
                "line_group": it.line_group,
                "spec": it.spec,
                "nfp": it.nfp,
                "purpose": it.purpose,
                "plan_horizon": round(plan_h, 1),
                "gp_stock": stock_gp,
                "gp_on_certification": float(gp_cert.get(it.name, 0.0)),
                "open_orders": orders_q,
                "need": need,
                "min_batch": round(mb, 1),
                "stockout_month": _stockout_month(stock_gp + orders_q, p, calc_date),
            }
        )
    lines = pd.DataFrame(rows)
    far = date(9999, 1, 1)
    lines["_order"] = lines.apply(
        lambda r: (r["stm"], r["stockout_month"] or far, ABC_ORDER.get(r["abc"], 3), -r["need"]), axis=1
    )
    lines = lines.sort_values("_order", kind="stable").drop(columns="_order").reset_index(drop=True)
    lines.insert(0, "priority", range(1, len(lines) + 1))

    # --- Распределение НФП и материалов по приоритету
    out_cols = {
        k: []
        for k in (
            "feasible",
            "limit",
            "status",
            "nfp_characteristic",
            "nfp_norm_kg",
            "nfp_need_kg",
            "nfp_available_kg",
            "nfp_quarantine_kg",
            "nfp_unreleased_kg",
            "nfp_shortage_kg",
            "nfp_source",
        )
    }
    material_need: dict[str, float] = {}
    material_items: dict[str, set[str]] = {}
    nfp_by_key: dict[tuple, dict] = {}
    nfp_initial = dict(nfp_pool.left)

    # допуск по материалам: если на складе не меньше 90 % общей потребности, считаем, что хватает
    total_mat_need: dict[str, float] = {}
    for row in lines.itertuples(index=False):
        spec = spec_by_name.get(row.spec)
        if row.stm or row.need <= 0 or spec is None or not row.nfp or row.line_group not in STAGE2_GROUPS:
            continue
        for m in spec[(spec["component"] != row.nfp) & (spec["qty_per_1000"] > 0)].itertuples(index=False):
            k = analog_key(m.component)
            total_mat_need[k] = total_mat_need.get(k, 0.0) + row.need * m.qty_per_1000 / 1000
    for k, q in total_mat_need.items():
        if (1 - MATERIAL_TOLERANCE) * q <= mat_pool.get(k) < q:
            mat_pool.left[k] = q

    for row in lines.itertuples(index=False):
        spec = spec_by_name.get(row.spec)
        res = {k: None for k in out_cols}
        res.update(
            feasible=0.0,
            nfp_need_kg=0.0,
            nfp_available_kg=0.0,
            nfp_quarantine_kg=0.0,
            nfp_unreleased_kg=0.0,
            nfp_shortage_kg=0.0,
        )
        if row.need <= 0:
            res.update(status=STATUS_NOT_NEEDED)
        elif spec is None or not row.nfp or row.line_group not in STAGE2_GROUPS:
            res.update(status=STATUS_NO_SPEC, limit="нет спецификации, НФП или линии")
        else:
            comp = spec[spec["component"] == row.nfp]
            norm = float(comp["qty_per_1000"].max()) / 1000 if len(comp) else 0.0
            char = comp["characteristic"].iloc[0] if len(comp) else None
            purchased = row.nfp not in nfp_names_on_nfp_wh and purchased_pool.get(row.nfp) > 0
            key = (row.nfp, char, row.purpose)
            need_kg = row.need * norm
            avail_kg = purchased_pool.get(row.nfp) if purchased else nfp_pool.get(key)
            limits: dict[str, float] = {}
            if norm > 0:
                limits["НФП"] = avail_kg / norm
            # материалы
            materials = spec[(spec["component"] != row.nfp) & (spec["qty_per_1000"] > 0)]
            for m in materials.itertuples(index=False):
                k = analog_key(m.component)
                mat_names.setdefault(k, m.component)
                per_unit = m.qty_per_1000 / 1000
                if not row.stm:  # СТМ — прогноз, в дефицит упаковки не входит
                    material_need[k] = material_need.get(k, 0.0) + row.need * per_unit
                    material_items.setdefault(k, set()).add(row.item)
                limits[m.component] = mat_pool.get(k) / per_unit
            cap = min(limits.values()) if limits else row.need
            feasible = float(min(row.need, math.floor(cap)))
            if feasible < row.min_batch:
                feasible = 0.0
            limit_name = None
            if feasible < row.need and limits:
                limit_name = min(limits, key=limits.get)
            # списываем то, что реально выпустим
            if purchased:
                purchased_pool.take(row.nfp, feasible * norm)
            else:
                nfp_pool.take(key, feasible * norm)
            for m in materials.itertuples(index=False):
                mat_pool.take(analog_key(m.component), feasible * m.qty_per_1000 / 1000)

            quarantine_kg = 0.0 if purchased else float(nfp_quarantine.get(key, 0.0))
            unreleased_kg = 0.0 if purchased else float(nfp_unreleased.get(key, 0.0))
            shortage = max(need_kg - avail_kg, 0.0)
            if not purchased and not row.stm:
                agg = nfp_by_key.setdefault(key, {"need_kg": 0.0, "items": []})
                agg["need_kg"] += need_kg
                agg["items"].append(row.item)
            status = (
                STATUS_FULL if feasible >= row.need else STATUS_PARTIAL if feasible > 0 else STATUS_BLOCKED
            )
            res.update(
                feasible=feasible,
                limit=limit_name,
                status=status,
                nfp_characteristic=char,
                nfp_norm_kg=round(norm, 5),
                nfp_need_kg=round(need_kg, 2),
                nfp_available_kg=round(avail_kg, 2),
                nfp_quarantine_kg=round(quarantine_kg, 2),
                nfp_unreleased_kg=round(unreleased_kg, 2),
                nfp_shortage_kg=round(shortage, 2),
                nfp_source="склад лексырья (покупной)" if purchased else "склад НФП",
            )
        for k in out_cols:
            out_cols[k].append(res[k])

    for k, v in out_cols.items():
        lines[k] = v

    # --- Сводка по материалам
    mat_available = mats.assign(k=mats["name"].map(analog_key)).groupby("k")["available"].sum()
    mat_records = []
    for k, q in material_need.items():
        available = float(mat_available.get(k, 0.0))
        missing = max(q - available, 0.0)
        within = missing > 0 and available >= (1 - MATERIAL_TOLERANCE) * q
        mat_records.append(
            {
                "material": mat_names[k],
                "need": round(q, 3),
                "available": available,
                "shortage": 0.0 if within else round(missing, 3),
                "deviation_pct": round(missing / q * 100, 1) if q and missing else 0.0,
                "within_tolerance": within,
                "items": len(material_items[k]),
                "item_names": "; ".join(sorted(material_items[k])),
            }
        )
    materials = pd.DataFrame(
        mat_records,
        columns=[
            "material",
            "need",
            "available",
            "shortage",
            "deviation_pct",
            "within_tolerance",
            "items",
            "item_names",
        ],
    ).sort_values(
        ["shortage", "deviation_pct", "material"], ascending=[False, False, True], ignore_index=True
    )

    # --- Дефицит НФП → вход для 1 ступени
    nfp_records = []
    for k, v in nfp_by_key.items():
        available = max(float(nfp_initial.get(k, 0.0)), 0.0)
        in_quarantine = float(nfp_quarantine.get(k, 0.0))
        if v["need_kg"] <= available:
            continue
        nfp_records.append(
            {
                "nfp": k[0],
                "characteristic": k[1],
                "purpose": k[2],
                "need_kg": round(v["need_kg"], 2),
                "available_kg": round(available, 2),
                "quarantine_kg": round(in_quarantine, 2),
                "quarantine_ready": quarantine_ready if in_quarantine > 0 else None,
                "unreleased_kg": round(float(nfp_unreleased.get(k, 0.0)), 2),
                "shortage_kg": round(max(v["need_kg"] - available - in_quarantine, 0.0), 2),
                "items": "; ".join(v["items"]),
            }
        )
    _apply_stage1_orders(nfp_records, data.orders)
    for r in nfp_records:  # задание 1 ступени — круглыми цифрами
        r["shortage_kg"] = round_kg(r["shortage_kg"])
        r["uncovered_kg"] = round_kg(r["uncovered_kg"])
    nfp = pd.DataFrame(
        nfp_records,
        columns=[
            "nfp",
            "characteristic",
            "purpose",
            "need_kg",
            "available_kg",
            "quarantine_kg",
            "quarantine_ready",
            "unreleased_kg",
            "shortage_kg",
            "stage1_orders_kg",
            "uncovered_kg",
            "items",
        ],
    ).sort_values("shortage_kg", ascending=False, ignore_index=True)

    return Stage2Result(
        params=params,
        lines=lines,
        materials=materials,
        nfp=nfp,
        month_factors={m.isoformat(): round(f, 4) for m, f in factors.items()},
        warehouses={
            role: sorted(set(stock.loc[stock["role"] == role, "warehouse"]))
            for role in wh.ROLES
            if role != wh.IGNORE and (stock["role"] == role).any()
        },
    )


def _apply_stage1_orders(records: list[dict], orders: pd.DataFrame) -> None:
    """Открытые заказы 1 ступени покрывают дефицит НФП той же фракции.

    Назначение в заказе 1 ступени не указано, поэтому объём заказов по (НФП, фракция)
    распределяется по строкам дефицита с разными назначениями, начиная с большего дефицита.
    """
    for r in records:
        r["stage1_orders_kg"], r["uncovered_kg"] = 0.0, r["shortage_kg"]
    if "nfp" not in orders.columns:
        return
    st1 = orders[(orders["stage"] == 1) & orders["nfp"].notna()]
    left = st1.groupby(["nfp", "nfp_characteristic"], dropna=False)["qty"].sum().to_dict()
    for r in sorted(records, key=lambda r: -r["shortage_kg"]):
        key = (r["nfp"], r["characteristic"])
        take = min(left.get(key, 0.0), r["shortage_kg"])
        if take > 0:
            left[key] -= take
            r["stage1_orders_kg"] = round(take, 2)
            r["uncovered_kg"] = round(r["shortage_kg"] - take, 2)


def round_kg(kg: float, step: int = NFP_ROUND_KG) -> float:
    """До ближайших 100 кг (4 543,2 → 4 500); ненулевой дефицит — не меньше 100 кг."""
    if kg <= 0:
        return 0.0
    return float(max(step, math.floor(kg / step + 0.5) * step))
