"""Загрузка всех выгрузок 1С из папки и сверка между ними."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError
from app.importers.gp_lots import LOT_COLUMNS, parse_gp_lots
from app.importers.items import parse_items
from app.importers.matching import match_items_to_specs, match_to_catalog
from app.importers.orders import ORDER_COLUMNS, is_finished, link_stage1_orders, parse_orders
from app.importers.quality import Issue, check_quality
from app.importers.sales_plan import parse_sales_plan
from app.importers.specs import effective_specs, is_nfp_component, parse_specs, spec_products
from app.importers.stock import parse_stock
from app.reference.lines import GP_IN_TRANSIT_DAYS, GP_RELEASES_LOOKBACK_DAYS

# Как узнаём файл по имени (без учёта регистра)
FILE_PATTERNS = {
    "items": "actual_items",
    # «Остатки ГП со сроками годности» — отдельный отчёт по сериям, его проверяем раньше
    "gp_lots": "сроками годности",
    "stock": "остатки",
    "specs": "ресурсные спецификации",
    "sales_plan": "план продаж",
    # «Список активных заказов» — этапы 1 и 2 ступени в одном отчёте
    "orders": "заказов",
}


@dataclass
class SourceFiles:
    items: Path
    stock: Path
    specs: Path
    sales_plan: list[Path]
    orders: Path | None = None
    gp_lots: Path | None = None

    @classmethod
    def from_folder(cls, folder: Path | str) -> "SourceFiles":
        # «~$…» — файл блокировки, который Excel создаёт рядом с открытой книгой; «.…» — скрытые файлы
        files = [
            p
            for p in Path(folder).iterdir()
            if p.suffix.lower() in (".xlsx", ".xls") and not p.name.startswith(("~$", "."))
        ]
        found: dict[str, list[Path]] = {k: [] for k in FILE_PATTERNS}
        for path in sorted(files):
            low = path.name.lower()
            for key, pattern in FILE_PATTERNS.items():
                if pattern in low:
                    found[key].append(path)
                    break  # один файл — один отчёт
        missing = [k for k in ("items", "stock", "specs", "sales_plan") if not found[k]]
        if missing:
            raise ReportFormatError(f"В папке {folder} нет файлов: {', '.join(missing)}")
        return cls(
            items=found["items"][0],
            stock=found["stock"][0],
            specs=found["specs"][0],
            sales_plan=found["sales_plan"],
            orders=found["orders"][0] if found["orders"] else None,
            gp_lots=found["gp_lots"][0] if found["gp_lots"] else None,
        )


RELEASE_COLUMNS = [
    "number",
    "name",
    "item",
    "series",
    "expiry",
    "qty",
    "production_date",
    "line_code",
    "received",  # True/False; None — нет отчёта по сериям или серии в этапе, проверить нельзя
    "in_transit",  # выпущено, но не оприходовано: учитываем как запас «в пути на склад»
]


@dataclass
class ImportResult:
    items: pd.DataFrame
    stock: pd.DataFrame
    specs: pd.DataFrame  # все строки всех версий
    specs_effective: pd.DataFrame  # одна версия на спецификацию
    sales_plan: pd.DataFrame
    orders: pd.DataFrame
    gp_lots: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=[*LOT_COLUMNS, "item"]))
    # выпуск 2 ступени за последние недели: поступил ли на склад ГП (серия есть в остатках по сериям)
    releases: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=RELEASE_COLUMNS))
    issues: list[Issue] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> dict:
        items = self.items
        return {
            "items_total": int(len(items)),
            "items_in_scope": int(items["in_scope"].sum()),
            "items_stm": int((items["in_scope"] & items["stm"]).sum()),
            "items_with_spec": int((items["in_scope"] & items["spec"].notna()).sum()),
            "items_spec_to_confirm": int(items["spec_needs_confirmation"].sum()),
            "items_spec_by_product": int((items["spec_method"] == "product").sum()),
            "stock_rows": int(len(self.stock)),
            "specs_total": int(self.specs_effective["spec"].nunique()),
            "specs_with_products": int(self.specs_effective.dropna(subset=["products"])["spec"].nunique())
            if "products" in self.specs_effective.columns
            else 0,
            "specs_multi_version": int(
                (self.specs_effective.groupby("spec")["versions_active"].first() > 1).sum()
            ),
            "plan_rows": int(len(self.sales_plan)),
            "plan_from": str(self.sales_plan["month"].min()) if len(self.sales_plan) else None,
            "plan_to": str(self.sales_plan["month"].max()) if len(self.sales_plan) else None,
            "orders_stage1": int((self.orders["stage"] == 1).sum()),
            "orders_stage2": int((self.orders["stage"] == 2).sum()),
            "gp_lots": int(len(self.gp_lots)),
            "gp_releases": int(len(self.releases)),
            "gp_in_transit": int(self.releases["in_transit"].sum()) if len(self.releases) else 0,
            "gp_in_transit_qty": float(self.releases.loc[self.releases["in_transit"], "qty"].sum())
            if len(self.releases)
            else 0.0,
            "warehouses": sorted(self.stock["warehouse"].unique().tolist()),
            "issues": {
                sev: sum(1 for i in self.issues if i.severity == sev) for sev in ("error", "warning", "info")
            },
        }


def _read(parser, path, *args):
    """Разбор одного отчёта: любая ошибка чтения — понятное сообщение с именем файла, а не «Ошибка 500»."""
    try:
        return parser(path, *args)
    except ReportFormatError as exc:
        names = ", ".join(p.name for p in path) if isinstance(path, list) else Path(path).name
        raise ReportFormatError(f"{names}: {exc}") from exc
    except Exception as exc:
        names = ", ".join(p.name for p in path) if isinstance(path, list) else Path(path).name
        raise ReportFormatError(
            f"Не удалось прочитать {names}: {type(exc).__name__}: {exc}. "
            "Проверьте, что файл сохранён в формате .xlsx и не открыт в Excel."
        ) from exc


def import_sources(files: SourceFiles, today: date | None = None) -> ImportResult:
    items = _read(parse_items, files.items)
    stock = _read(parse_stock, files.stock)
    specs = _read(parse_specs, files.specs)
    specs_eff = effective_specs(specs)
    plan = _read(parse_sales_plan, files.sales_plan)
    orders = _read(parse_orders, files.orders) if files.orders else pd.DataFrame(columns=ORDER_COLUMNS)
    gp_lots = _read(parse_gp_lots, files.gp_lots) if files.gp_lots else pd.DataFrame(columns=LOT_COLUMNS)

    # ГП ↔ спецификация
    matches = match_items_to_specs(items, specs_eff).set_index("item")
    items["spec"] = items["name"].map(matches["spec"])
    items["spec_method"] = items["name"].map(matches["method"])
    items["spec_score"] = items["name"].map(matches["score"]).fillna(0.0)
    items["spec_needs_confirmation"] = items["name"].map(matches["needs_confirmation"]).fillna(False)

    # НФП: из actual_items, а если не заполнен — компонент-НФП из спецификации
    nfp_by_spec = (
        specs_eff[specs_eff["component"].map(is_nfp_component)]
        .sort_values("qty_per_1000", ascending=False)
        .drop_duplicates("spec")
        .set_index("spec")["component"]
    )
    items["nfp_source"] = items["nfp"].map(lambda v: "actual_items" if v else None)
    fill = items["nfp"].isna() & items["spec"].isin(nfp_by_spec.index)
    items.loc[fill, "nfp"] = items.loc[fill, "spec"].map(nfp_by_spec)
    items.loc[fill, "nfp_source"] = "spec"

    # Ссылки отчётов на справочник ГП
    catalog = items["name"]
    plan["item"] = match_to_catalog(plan["name"], catalog)
    # заказы: в отчёте — имя спецификации этапа; её изделие (если выгружено) точнее имени
    products = spec_products(specs)
    order_product = orders["name"].map(lambda s: (products.get(s) or [None])[0])
    by_product = match_to_catalog(order_product.fillna(""), catalog)
    by_name = match_to_catalog(orders["name"], catalog)
    # 2 ступень → ГП из справочника; 1 ступень → НФП и фракция
    orders["item"] = by_product.fillna(by_name).where(orders["stage"] == 2, None)
    nfp_catalog = (
        set(items["nfp"].dropna())
        | set(specs_eff.loc[specs_eff["component"].map(is_nfp_component), "component"])
        | set(stock.loc[stock["name"].str.contains("НФП", na=False), "name"])
    )
    fractions = stock["characteristic"].dropna().unique().tolist()
    orders = link_stage1_orders(orders, sorted(nfp_catalog), fractions, products)
    # ссылка на ГП для всех строк: какие склады считать запасом ГП, решают роли складов
    stock["item"] = match_to_catalog(stock["name"], catalog)
    gp_lots["item"] = match_to_catalog(gp_lots["name"], catalog)

    # Завершённые этапы — не заказы; по 2 ступени из них — выпуск, который мог не дойти до склада ГП
    finished = orders["status"].map(is_finished)
    releases = _releases(orders[finished & (orders["stage"] == 2)], gp_lots, catalog, today or date.today())
    orders = orders[~finished].reset_index(drop=True)

    result = ImportResult(
        items=items,
        stock=stock,
        specs=specs,
        specs_effective=specs_eff,
        sales_plan=plan,
        orders=orders,
        gp_lots=gp_lots,
        releases=releases,
        files={
            "items": files.items.name,
            "stock": files.stock.name,
            "specs": files.specs.name,
            "sales_plan": ", ".join(p.name for p in files.sales_plan),
            "orders": files.orders.name if files.orders else "",
            "gp_lots": files.gp_lots.name if files.gp_lots else "",
        },
    )
    result.issues = check_quality(result, today=today or date.today())
    for r in releases[releases["in_transit"]].itertuples(index=False):
        result.issues.append(
            Issue(
                "info",
                "orders",
                r.item or r.name,
                f"Этап {r.number} завершён {r.production_date:%d.%m.%Y}, серия {r.series} ({r.qty:,.0f} шт) "
                "ещё не поступила на склад ГП — в расчётах учтена как «не оприходовано»".replace(",", " "),
            )
        )
    return result


def _releases(finished: pd.DataFrame, gp_lots: pd.DataFrame, catalog: pd.Series, today: date) -> pd.DataFrame:
    """Выпуск 2 ступени за последние недели и поступил ли он на склад ГП.

    Поступил — серия этапа («Серия ГП») есть в отчёте «Остатки ГП со сроками годности».
    Нет серии в остатках и выпуск свежий (не старше GP_IN_TRANSIT_DAYS) — продукция выпущена,
    но не оприходована: в расчётах она считается запасом ГП «в пути на склад».
    """
    if not len(finished):
        return pd.DataFrame(columns=RELEASE_COLUMNS)
    day = finished["production_date"].where(
        finished["production_date"].notna(),
        finished["started_at"].map(lambda t: t.date() if pd.notna(t) else None),
    )
    recent = finished[day.map(lambda d: d is not None and (today - d).days <= GP_RELEASES_LOOKBACK_DAYS)]
    if not len(recent):
        return pd.DataFrame(columns=RELEASE_COLUMNS)
    day = day[recent.index]
    by_gp_name = match_to_catalog(recent["gp_name"].fillna(""), catalog)
    lot_series = set(gp_lots["series"].dropna().astype(str)) if len(gp_lots) else None
    out = pd.DataFrame(
        {
            "number": recent["number"],
            "name": recent["gp_name"].fillna(recent["name"]),
            "item": by_gp_name.fillna(recent["item"]),
            "series": recent["gp_series"],
            "expiry": recent["gp_expiry"],
            "qty": recent["qty_done"].where(recent["qty_done"] > 0, recent["qty_plan"]),
            "production_date": day,
            "line_code": recent["line_code"],
        }
    )
    out["received"] = [
        None if lot_series is None or pd.isna(s) or not s else s in lot_series for s in out["series"]
    ]
    out["in_transit"] = [
        r is False and (today - d).days <= GP_IN_TRANSIT_DAYS and q > 0
        for r, d, q in zip(out["received"], out["production_date"], out["qty"], strict=True)
    ]
    return out.sort_values(["production_date", "number"], ascending=[False, True]).reset_index(drop=True)


def import_folder(folder: Path | str, today: date | None = None) -> ImportResult:
    return import_sources(SourceFiles.from_folder(folder), today=today)
