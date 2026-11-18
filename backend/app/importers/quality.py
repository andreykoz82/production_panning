"""Отчёт о качестве данных после импорта.

error — без исправления позиция не попадёт в расчёт;
warning — расчёт пойдёт, но результат стоит проверить;
info — для сведения.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import TYPE_CHECKING

from app.reference import warehouses as wh
from app.reference.lines import STAGE2_GROUPS

if TYPE_CHECKING:
    from app.importers.loader import ImportResult

MAX_EXAMPLES = 10


@dataclass
class Issue:
    severity: str  # error | warning | info
    area: str  # items | specs | stock | plan | orders
    item: str | None
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _months_ahead(today: date, n: int) -> tuple[date, date]:
    start = today.replace(day=1)
    year, month = divmod(start.month - 1 + n, 12)
    return start, date(start.year + year, month + 1, 1)


def _n(v: float) -> str:
    return f"{v:,.0f}".replace(",", "\u00a0")


def _empty(v) -> bool:
    return v is None or v != v  # None или NaN


def check_quality(r: ImportResult, today: date) -> list[Issue]:
    issues: list[Issue] = []
    add = lambda *a: issues.append(Issue(*a))  # noqa: E731
    items = r.items
    scope = items[items["in_scope"]]

    # --- Справочник ГП и спецификации
    for row in items[~items["in_scope"]].itertuples():
        add("info", "items", row.name, f"Не планируется: {row.line_group}")
    has_series = "min_series" in items.columns and items[["min_series", "max_series"]].notna().any().any()
    if not has_series:
        add(
            "warning",
            "items",
            None,
            "В actual_items нет минимальной/максимальной серии — учитывается только партия 1 ч",
        )
    for row in scope.itertuples():
        if has_series and row.kind == "ЛС" and (_empty(row.min_series) or _empty(row.max_series)):
            add("warning", "items", row.name, "Лекарственный продукт без минимальной или максимальной серии")
        if (
            has_series
            and not _empty(row.min_series)
            and not _empty(row.max_series)
            and row.min_series > row.max_series
        ):
            add(
                "error",
                "items",
                row.name,
                f"Минимальная серия {_n(row.min_series)} больше максимальной {_n(row.max_series)}",
            )
        if row.line_group not in STAGE2_GROUPS:
            add("error", "items", row.name, f"Неизвестная группа линий «{row.line_group}»")
        if row.spec is None or row.spec != row.spec:  # None или NaN
            add("error", "specs", row.name, "Действующая спецификация не найдена")
        elif row.spec_method == "fuzzy":
            add(
                "warning",
                "specs",
                row.name,
                f"Спецификация найдена по похожему имени «{row.spec}» (сходство {row.spec_score:.0f}%) — "
                "подтвердите связь",
            )
        elif row.spec_method == "printed_material":
            add("info", "specs", row.name, f"Спецификация найдена по печатному материалу: «{row.spec}»")
        elif row.spec_method == "normalized":
            add("info", "specs", row.name, f"В спецификациях имя записано иначе: «{row.spec}»")
        if not row.nfp or row.nfp != row.nfp:
            add("error", "items", row.name, "НФП не указан ни в actual_items, ни в спецификации")
        elif row.nfp_source == "spec":
            add(
                "warning",
                "items",
                row.name,
                f"НФП не заполнен в actual_items, взят из спецификации: {row.nfp}",
            )

    if "products" in r.specs_effective.columns:
        produced: dict[str, list[str]] = {}
        for spec, products in (
            r.specs_effective[["spec", "products"]].drop_duplicates().itertuples(index=False)
        ):
            for p in products.split("; ") if isinstance(products, str) else []:
                produced.setdefault(p, []).append(spec)
        chosen = items.set_index("name")["spec"]
        for name, specs in produced.items():
            if len(specs) > 1 and name in chosen.index:
                others = "; ".join(s for s in sorted(specs) if s != chosen[name])
                add(
                    "info",
                    "specs",
                    name,
                    f"ГП выпускают {len(specs)} действующие спецификации, взята «{chosen[name]}», "
                    f"есть ещё: {others}",
                )

    multi = r.specs_effective.groupby("spec")["versions_active"].first()
    multi = multi[multi > 1]
    if len(multi):
        add(
            "info",
            "specs",
            None,
            f"У {len(multi)} спецификаций несколько действующих версий — взята версия "
            "с максимальной нормой НФП, материалы-аналоги из других версий взаимозаменяемы",
        )
    closed = r.specs[r.specs["status"].notna() & (r.specs["status"] != "Действует")]
    if len(closed):
        add(
            "info",
            "specs",
            None,
            f"Не учитываются {closed['spec'].nunique()} спецификаций со статусом "
            f"«Закрыта» / «В разработке» (без действующей версии: "
            f"{len(set(closed['spec']) - set(r.specs_effective['spec']))})",
        )

    # --- План продаж
    start, end = _months_ahead(today, 12)
    plan = r.sales_plan
    ahead = plan[(plan["month"] >= start) & (plan["month"] < end) & plan["item"].notna()]
    planned = set(ahead.loc[ahead["qty"] > 0, "item"])
    for name in scope["name"]:
        if name not in planned:
            add("warning", "plan", name, "Нет плана продаж на ближайшие 12 месяцев")
    unknown = sorted(set(plan.loc[plan["item"].isna(), "name"]))
    if unknown:
        add(
            "info",
            "plan",
            None,
            f"{len(unknown)} позиций плана продаж нет в actual_items (НФП, сырьё, снятые позиции): "
            + "; ".join(unknown[:MAX_EXAMPLES])
            + (" …" if len(unknown) > MAX_EXAMPLES else ""),
        )

    # --- Остатки
    stock = wh.with_roles(r.stock)
    for name in sorted(set(stock["warehouse"]) - set(wh.DEFAULT_ROLES)):
        add(
            "warning",
            "stock",
            None,
            f"Новый склад «{name}» пока не учитывается в расчёте — назначьте роль в разделе «Склады»",
        )
    defect = stock[stock["is_defect"] & stock["role"].isin(wh.GP_ROLES)]
    if len(defect):
        add(
            "info",
            "stock",
            None,
            f"Исключено строк брака на складах ГП: {len(defect)} "
            f"({defect['on_hand'].sum():,.0f} шт.)".replace(",", " "),
        )
    nfp_stock = set(stock.loc[stock["role"].isin((wh.NFP, wh.NFP_QUARANTINE)), "name"])
    raw_stock = set(stock.loc[stock["role"] == wh.RAW, "name"])
    for row in scope.itertuples():
        if not row.nfp or row.nfp != row.nfp or row.nfp in nfp_stock:
            continue
        if row.nfp in raw_stock:
            add("info", "stock", row.name, f"НФП «{row.nfp}» лежит на складе лексырья (покупной)")
        else:
            add("info", "stock", row.name, f"НФП «{row.nfp}» нет на складах — понадобится 1 ступень")

    # --- Заказы
    all_orders = r.orders
    orders = all_orders[all_orders["stage"] == 2]
    for row in orders[orders["item"].isna()].itertuples():
        add("error", "orders", row.name, f"Заказ {row.number}: позиции нет в actual_items")
    out = set(items.loc[~items["in_scope"], "name"])
    for row in orders[orders["item"].isin(out)].itertuples():
        add("warning", "orders", row.name, f"Заказ {row.number}: позиция не планируется")
    for number in all_orders.loc[all_orders["number"].duplicated(), "number"].unique():
        add("error", "orders", None, f"Номер заказа {number} встречается несколько раз")
    if "line_1c" in all_orders.columns:
        unknown = all_orders[all_orders["line_1c"].notna() & all_orders["line_code"].isna()]
        for line in sorted(unknown["line_1c"].unique()):
            add("warning", "orders", None, f"Линия 1С «{line}» не сопоставлена с линиями приложения")
        if has_series:
            limits = scope.set_index("name")[["min_series", "max_series"]]
            for row in orders[orders["item"].isin(limits.index)].itertuples():
                lo, hi = limits.loc[row.item, "min_series"], limits.loc[row.item, "max_series"]
                if not _empty(hi) and row.qty_plan > hi:
                    add(
                        "info",
                        "orders",
                        row.item,
                        f"Заказ {row.number}: {_n(row.qty_plan)} шт больше максимальной серии {_n(hi)}",
                    )
                elif not _empty(lo) and row.qty_plan < lo:
                    add(
                        "info",
                        "orders",
                        row.item,
                        f"Заказ {row.number}: {_n(row.qty_plan)} шт меньше минимальной серии {_n(lo)}",
                    )
        done = orders[(orders["qty_plan"] > 0) & (orders["qty"] <= 0)]
        for row in done.itertuples():
            add("info", "orders", row.name, f"Заказ {row.number}: выполнен полностью, на Ганте его нет")
        stage1 = all_orders[all_orders["stage"] == 1]
        for row in stage1[stage1["nfp"].isna()].itertuples():
            add("info", "orders", row.name, f"Заказ 1 ступени {row.number}: не найден НФП в справочнике")

    return issues
