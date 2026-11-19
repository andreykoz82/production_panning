"""«Остатки ГП со сроками годности» (ведомость по товарам на складах ГП и опта, по сериям).

Колонки: «Серия.Номер», «Серия.Дата производства», «Серия.Годен до», «Номенклатура»,
«Номенклатура.Срок годности» (мес.), «Номенклатура.Марка (бренд)», «Конечный остаток»,
«Остаточный срок годности на дату расхода» (%). Строка «Итого» пропускается.
"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError, clean, find_row, read_raw, to_date, to_float

LOT_COLUMNS = [
    "name",
    "series",
    "production_date",
    "expiry",
    "shelf_life_months",
    "brand",
    "qty",
    "residual_pct",
    "report_date",
]

_HEADERS = {
    "series": "Серия.Номер",
    "production_date": "Серия.Дата производства",
    "expiry": "Серия.Годен до",
    "name": "Номенклатура",
    "shelf_life_months": "Номенклатура.Срок годности",
    "brand": "Номенклатура.Марка (бренд)",
    "qty": "Конечный остаток",
    "residual_pct": "Остаточный срок годности на дату расхода",
    "report_date": "Период, день",
}
_REQUIRED = ("name", "expiry", "qty")


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean(value)
    return to_date(text.split(" ")[0]) if text else None


def parse_gp_lots(path: Path | str) -> pd.DataFrame:
    raw = read_raw(path)
    head = find_row(raw, lambda r: "Серия.Годен до" in r and "Конечный остаток" in r, "Серия.Годен до")
    header = [clean(v) or "" for v in raw.iloc[head]]
    cols = {key: header.index(h) for key, h in _HEADERS.items() if h in header}
    missing = [_HEADERS[k] for k in _REQUIRED if k not in cols]
    if missing:
        raise ReportFormatError(f"Остатки ГП со сроками годности: нет колонок {', '.join(missing)}")

    def get(values, key):
        return values[cols[key]] if key in cols else None

    rows = []
    for values in raw.iloc[head + 1 :].itertuples(index=False):
        name = clean(get(values, "name"))
        expiry = _date(get(values, "expiry"))
        qty = to_float(get(values, "qty"))
        if not name or not expiry or qty <= 0:
            continue  # «Итого» и пустые строки
        shelf = to_float(get(values, "shelf_life_months"))
        rows.append(
            {
                "name": name,
                "series": clean(get(values, "series")),
                "production_date": _date(get(values, "production_date")),
                "expiry": expiry,
                "shelf_life_months": shelf or None,
                "brand": clean(get(values, "brand")),
                "qty": qty,
                "residual_pct": to_float(get(values, "residual_pct")) if "residual_pct" in cols else None,
                "report_date": _date(get(values, "report_date")),
            }
        )
    return pd.DataFrame(rows, columns=LOT_COLUMNS)
