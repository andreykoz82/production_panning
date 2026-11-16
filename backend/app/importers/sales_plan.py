"""План продаж из 1С ERP: номенклатура × конец месяца × количество."""

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError, clean, to_date, to_float

PLAN_COLUMNS = ["name", "month", "qty", "amount", "source"]


def parse_sales_plan(paths: Iterable[Path | str]) -> pd.DataFrame:
    """Склеивает несколько файлов плана в одну помесячную ленту.

    Месяц хранится как первое число месяца. Если месяц есть в нескольких файлах,
    побеждает файл, переданный позже (новая версия плана).
    """
    frames = []
    for order, path in enumerate(paths):
        raw = pd.read_excel(path, dtype=object)
        cols = {c.strip(): c for c in raw.columns if isinstance(c, str)}
        name_col = cols.get("Номенклатура")
        month_col = next((cols[c] for c in cols if "Период" in c or "Месяц" in c), None)
        qty_col = cols.get("Количество")
        if not (name_col and month_col and qty_col):
            raise ReportFormatError(
                f"План продаж {Path(path).name}: нет колонок Номенклатура / Период / Количество"
            )
        rows = []
        for rec in raw.to_dict("records"):
            name = clean(rec[name_col])
            month = to_date(rec[month_col])
            if not name or name.lower().startswith("итого") or month is None:
                continue
            rows.append(
                {
                    "name": name,
                    "month": month.replace(day=1),
                    "qty": to_float(rec[qty_col]),
                    "amount": to_float(rec.get(cols.get("Сумма"))) if cols.get("Сумма") else 0.0,
                    "source": Path(path).name,
                    "_order": order,
                }
            )
        frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame(columns=PLAN_COLUMNS)
    plan = pd.concat(frames, ignore_index=True)
    latest = plan.groupby(["name", "month"])["_order"].transform("max")
    plan = plan[plan["_order"] == latest]
    plan = plan.groupby(["name", "month"], as_index=False).agg(
        qty=("qty", "sum"), amount=("amount", "sum"), source=("source", "last")
    )
    return plan[PLAN_COLUMNS].sort_values(["name", "month"], ignore_index=True)
