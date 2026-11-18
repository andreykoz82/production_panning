"""Загрузка всех выгрузок 1С из папки и сверка между ними."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError
from app.importers.items import parse_items
from app.importers.matching import match_items_to_specs, match_to_catalog
from app.importers.orders import ORDER_COLUMNS, link_stage1_orders, parse_orders
from app.importers.quality import Issue, check_quality
from app.importers.sales_plan import parse_sales_plan
from app.importers.specs import effective_specs, is_nfp_component, parse_specs, spec_products
from app.importers.stock import parse_stock

# Как узнаём файл по имени (без учёта регистра)
FILE_PATTERNS = {
    "items": "actual_items",
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

    @classmethod
    def from_folder(cls, folder: Path | str) -> "SourceFiles":
        files = [p for p in Path(folder).iterdir() if p.suffix.lower() in (".xlsx", ".xls")]
        found: dict[str, list[Path]] = {k: [] for k in FILE_PATTERNS}
        for path in sorted(files):
            low = path.name.lower()
            for key, pattern in FILE_PATTERNS.items():
                if pattern in low:
                    found[key].append(path)
        missing = [k for k in ("items", "stock", "specs", "sales_plan") if not found[k]]
        if missing:
            raise ReportFormatError(f"В папке {folder} нет файлов: {', '.join(missing)}")
        return cls(
            items=found["items"][0],
            stock=found["stock"][0],
            specs=found["specs"][0],
            sales_plan=found["sales_plan"],
            orders=found["orders"][0] if found["orders"] else None,
        )


@dataclass
class ImportResult:
    items: pd.DataFrame
    stock: pd.DataFrame
    specs: pd.DataFrame  # все строки всех версий
    specs_effective: pd.DataFrame  # одна версия на спецификацию
    sales_plan: pd.DataFrame
    orders: pd.DataFrame
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
            "warehouses": sorted(self.stock["warehouse"].unique().tolist()),
            "issues": {
                sev: sum(1 for i in self.issues if i.severity == sev) for sev in ("error", "warning", "info")
            },
        }


def import_sources(files: SourceFiles, today: date | None = None) -> ImportResult:
    items = parse_items(files.items)
    stock = parse_stock(files.stock)
    specs = parse_specs(files.specs)
    specs_eff = effective_specs(specs)
    plan = parse_sales_plan(files.sales_plan)
    orders = parse_orders(files.orders) if files.orders else pd.DataFrame(columns=ORDER_COLUMNS)

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

    result = ImportResult(
        items=items,
        stock=stock,
        specs=specs,
        specs_effective=specs_eff,
        sales_plan=plan,
        orders=orders,
        files={
            "items": files.items.name,
            "stock": files.stock.name,
            "specs": files.specs.name,
            "sales_plan": ", ".join(p.name for p in files.sales_plan),
            "orders": files.orders.name if files.orders else "",
        },
    )
    result.issues = check_quality(result, today=today or date.today())
    return result


def import_folder(folder: Path | str, today: date | None = None) -> ImportResult:
    return import_sources(SourceFiles.from_folder(folder), today=today)
