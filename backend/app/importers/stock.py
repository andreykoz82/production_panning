"""Отчёт «Остатки по складам» из 1С ERP.

Отчёт иерархический: строка-группа с наименованием номенклатуры, под ней строки по складам.
Берём только строки с заполненной колонкой «Номенклатура» во второй строке шапки.
"""

from pathlib import Path

import pandas as pd

from app.importers.common import (
    ReportFormatError,
    clean,
    date_in_text,
    find_row,
    read_raw,
    to_float,
)

WAREHOUSE_GP = "Склад готовой продукции"
WAREHOUSE_WHOLESALE = "Склад оптовой торговли ЛС"
WAREHOUSE_NFP = "Склад нерасфасованных продуктов"
WAREHOUSE_NFP_QUARANTINE = "Склад НФП (карантинное хранение)"
WAREHOUSE_BYPRODUCTS = "Склад продуктов обработки сырья (скл. НФП)"
WAREHOUSE_RAW = "Склад лексырья"
WAREHOUSE_MATERIALS = "Материальный склад"

GP_WAREHOUSES = (WAREHOUSE_GP, WAREHOUSE_WHOLESALE)

_FIELDS = {
    "Склад": "warehouse",
    "Номенклатура": "name",
    "Характеристика": "characteristic",
    "Серия": "series",
    "Целевое назначение": "purpose",
    "Фасовка": "packing",
    "В наличии": "on_hand",
    "В резерве": "reserved",
    "К отгрузке": "to_ship",
    "Доступно": "available",
}


def parse_stock(path: Path | str) -> pd.DataFrame:
    raw = read_raw(path)
    second = find_row(raw, lambda r: r[0] == "Склад" and "Номенклатура" in r, "Склад / Номенклатура")
    if second == 0:
        raise ReportFormatError("Остатки: нет первой строки шапки")
    first = second - 1

    # Шапка в две строки; вторая важнее (в первой «Номенклатура» — колонка строк-групп)
    cols: dict[str, int] = {}
    for header_row in (first, second):
        for idx, value in enumerate(raw.iloc[header_row]):
            if clean(value) in _FIELDS:
                cols[clean(value)] = idx
    missing = [c for c in ("Склад", "Номенклатура", "В наличии", "Доступно") if c not in cols]
    if missing:
        raise ReportFormatError(f"Остатки: нет колонок {', '.join(missing)}")

    rows = []
    for values in raw.iloc[second + 1 :].itertuples(index=False):
        name = clean(values[cols["Номенклатура"]])
        warehouse = clean(values[cols["Склад"]])
        if not name or not warehouse:
            continue

        def get(field: str, row=values):
            return row[cols[field]] if field in cols else None

        packing = clean(get("Фасовка"))
        series = clean(get("Серия"))
        rows.append(
            {
                "warehouse": warehouse,
                "name": name,
                "characteristic": clean(get("Характеристика")),
                "series": series,
                "expiry": date_in_text(series),
                "purpose": clean(get("Целевое назначение")),
                "packing_allowed": {"Да": True, "Нет": False}.get(packing),
                "on_hand": to_float(get("В наличии")),
                "reserved": to_float(get("В резерве")),
                "to_ship": to_float(get("К отгрузке")),
                "available": to_float(get("Доступно")),
                "is_defect": "(брак)" in name.lower(),
            }
        )
    return pd.DataFrame(rows, columns=STOCK_COLUMNS)


STOCK_COLUMNS = [
    "warehouse",
    "name",
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
