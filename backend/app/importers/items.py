"""Справочник актуальной номенклатуры ГП (actual_items.xlsx).

Кроме обязательных колонок читаются необязательные (18.11.2026):
- минимальная и максимальная серия, шт («min», «max», «Мин. серия», «Макс. серия» …);
- признак СТМ «да/нет». Если колонки нет или ячейка пустая — СТМ определяется по наименованию.
"""

import re
from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError, clean, to_float
from app.reference.lines import EXCLUDED_GROUPS
from app.reference.stm import is_stm

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


OPTIONAL = {
    "min_series": re.compile(r"^(min|мин)\b|миним", re.IGNORECASE),
    "max_series": re.compile(r"^(max|макс)\b|максим", re.IGNORECASE),
    "stm_flag": re.compile(r"стм|stm", re.IGNORECASE),
}
_YES = {"да", "yes", "y", "1", "true", "истина", "+"}
_NO = {"нет", "no", "n", "0", "false", "ложь", "-"}


def _flag(value) -> bool | None:
    text = (clean(value) or "").strip().lower()
    if text in _YES:
        return True
    if text in _NO:
        return False
    return None


def _series(value) -> float | None:
    if clean(value) is None:
        return None
    qty = to_float(value)
    return qty if qty > 0 else None


def parse_items(path: Path | str) -> pd.DataFrame:
    raw = pd.read_excel(path, dtype=object)
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = [c for c in COLUMNS if c not in raw.columns]
    if missing:
        raise ReportFormatError(f"В actual_items нет колонок: {', '.join(missing)}")
    optional = {
        key: next((c for c in raw.columns if c not in COLUMNS and rx.search(c)), None)
        for key, rx in OPTIONAL.items()
    }

    rows = []
    for rec in raw.to_dict("records"):
        row = {COLUMNS[k]: clean(rec[k]) for k in COLUMNS}
        if not row["name"]:
            continue
        row["mass_g"] = to_float(rec["Масса"])
        row["abc"] = (row["abc"] or "C").upper()
        row["in_scope"] = row["line_group"] not in EXCLUDED_GROUPS
        row["min_series"] = _series(rec[optional["min_series"]]) if optional["min_series"] else None
        row["max_series"] = _series(rec[optional["max_series"]]) if optional["max_series"] else None
        flag = _flag(rec[optional["stm_flag"]]) if optional["stm_flag"] else None
        row["stm"] = flag if flag is not None else is_stm(row["name"])
        rows.append(row)
    return pd.DataFrame(rows, columns=[*COLUMNS.values(), "in_scope", "min_series", "max_series", "stm"])
