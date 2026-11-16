"""Справочник актуальной номенклатуры ГП (actual_items.xlsx)."""

from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError, clean, to_float
from app.reference.lines import EXCLUDED_GROUPS

COLUMNS = {
    "Наименование": "name",
    "Группа": "abc",
    "Масса": "mass_g",
    "Производственная линия": "line_group",
    "Форма": "form",
    "Тип": "kind",
    "GTIN": "gtin",
    "НФП": "nfp",
    "Целевое назначение": "purpose",
    "Печатный материал": "printed_material",
}


def parse_items(path: Path | str) -> pd.DataFrame:
    raw = pd.read_excel(path, dtype=object)
    missing = [c for c in COLUMNS if c not in raw.columns]
    if missing:
        raise ReportFormatError(f"В actual_items нет колонок: {', '.join(missing)}")

    rows = []
    for rec in raw[list(COLUMNS)].to_dict("records"):
        row = {COLUMNS[k]: clean(v) for k, v in rec.items()}
        if not row["name"]:
            continue
        row["mass_g"] = to_float(rec["Масса"])
        row["abc"] = (row["abc"] or "C").upper()
        row["in_scope"] = row["line_group"] not in EXCLUDED_GROUPS
        rows.append(row)
    return pd.DataFrame(rows, columns=[*COLUMNS.values(), "in_scope"])
