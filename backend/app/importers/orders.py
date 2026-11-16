"""Список открытых заказов на производство (отчёт 1С по документу «Заказ на производство»)."""

from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError, clean, find_row, read_raw, to_float

ORDER_COLUMNS = ["number", "name", "qty", "stage"]


def parse_orders(path: Path | str, stage: int = 2) -> pd.DataFrame:
    raw = read_raw(path)
    head = find_row(raw, lambda r: "Количество" in r, "Количество")
    header = [clean(v) or "" for v in raw.iloc[head]]
    qty_col = header.index("Количество")
    num_col = next((i for i, h in enumerate(header) if "Номер" in h), None)
    # Наименование ГП диспетчер пишет в «Комментарий»; в других выгрузках может быть «Номенклатура»
    name_col = next((i for i, h in enumerate(header) if h in ("Номенклатура", "Комментарий")), None)
    if name_col is None or num_col is None:
        raise ReportFormatError("Заказы: нужны колонки «Номенклатура»/«Комментарий» и «Номер»")

    rows = []
    for values in raw.iloc[head + 1 :].itertuples(index=False):
        name, number = clean(values[name_col]), clean(values[num_col])
        if not name or not number:
            continue
        rows.append({"number": number, "name": name, "qty": to_float(values[qty_col]), "stage": stage})
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)
