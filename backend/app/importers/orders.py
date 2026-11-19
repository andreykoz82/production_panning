"""Список активных заказов на производство (отчёт 1С).

Основной формат — выгрузка документов «Этап производства» (1 и 2 ступень в одном файле):
номер этапа, статус, спецификация, подразделение (ступень), основной ВРЦ (линия),
фактическое начало, запланировано и выполнено. «Выполнено» заполняется только для 2 ступени —
выпущенная продукция уже лежит на складе ГП, поэтому открытым считаем остаток «план − выполнено».

С 19.11.2026 в отчёте есть альтернативные виды рабочих центров: «Альтернативные виды рабочих центров.Вид
рабочего центра» и «….Использовать» (да/нет). У этапа с несколькими альтернативами — несколько строк.
Линия этапа: альтернативный ВРЦ из строки, где «Использовать» = «Да»; если такой нет — основной ВРЦ.

Старый формат («Заказ на производство» с колонками «Номер», «Комментарий», «Количество»)
по-прежнему читается — все строки считаются заказами указанной ступени.
"""

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError, clean, find_row, norm_name, read_raw, to_date, to_float
from app.reference.lines import line_from_1c

ORDER_COLUMNS = [
    "number",
    "stage",
    "name",
    "qty",  # открытый остаток: для 2 ступени план − выполнено, для 1 ступени — план
    "qty_plan",
    "qty_done",
    "status",
    "line_1c",
    "line_code",
    "started_at",
    "production_date",
    "doc_date",
]

_STAGE_DOC = re.compile(r"(КЛ\d{2}-[\d.]+)\s+от\s+(\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)")


def _datetime(value) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    d = to_date(text)
    return datetime.combine(d, datetime.min.time()) if d else None


def _stage_of(department: str | None) -> int | None:
    low = (department or "").lower()
    if "перв" in low or low.startswith("1"):
        return 1
    if "втор" in low or low.startswith("2"):
        return 2
    return None


def parse_orders(path: Path | str, stage: int = 2) -> pd.DataFrame:
    raw = read_raw(path)
    head = find_row(
        raw,
        lambda r: "Количество" in r or ("Запланировано" in r and "Этап производства" in r),
        "«Этап производства» и «Запланировано» (или «Количество»)",
    )
    header = [clean(v) or "" for v in raw.iloc[head]]
    if "Запланировано" in header:
        return _parse_stage_docs(raw, head, header)
    return _parse_legacy(raw, head, header, stage)


def _parse_stage_docs(raw: pd.DataFrame, head: int, header: list[str]) -> pd.DataFrame:
    def col(*names: str) -> int | None:
        """Колонка по точному имени, иначе по началу («Основной ВРЦ» → «Основной ВРЦ.Наименование»)."""
        for n in names:
            if n in header:
                return header.index(n)
        for n in names:
            found = next((i for i, h in enumerate(header) if h.startswith(n)), None)
            if found is not None:
                return found
        return None

    c_doc = col("Этап производства")
    c_spec = col("Спецификация", "Этап")
    c_plan = col("Запланировано")
    c_dep = col("Подразделение-исполнитель", "Ответственное подразделение")
    if None in (c_doc, c_spec, c_plan, c_dep):
        raise ReportFormatError(
            "Заказы: нужны колонки «Этап производства», «Спецификация», "
            "«Подразделение-исполнитель», «Запланировано»"
        )
    c_done, c_status = col("Выполнено"), col("Статус")
    c_line, c_start, c_prod = col("Основной ВРЦ"), col("Фактическое начало этапа"), col("Дата производства")
    c_alt = col("Альтернативные виды рабочих центров.Вид рабочего центра")
    c_alt_use = col("Альтернативные виды рабочих центров.Использовать")

    def get(values, c):
        return values[c] if c is not None else None

    rows: dict[str, dict] = {}  # номер этапа → строка; у этапа может быть несколько строк (альтернативы ВРЦ)
    for values in raw.iloc[head + 1 :].itertuples(index=False):
        doc = clean(values[c_doc])
        m = _STAGE_DOC.search(doc or "")
        name = clean(values[c_spec])
        stage = _stage_of(clean(values[c_dep]))
        if not m or not name or stage is None:
            continue  # «Итого» и пустые строки
        alt = clean(get(values, c_alt))
        use_alt = bool(alt) and _yes(get(values, c_alt_use))
        if m[1] in rows:
            if use_alt and not rows[m[1]]["_alt"]:
                rows[m[1]].update(line_1c=alt, line_code=line_from_1c(alt), _alt=True)
            continue
        plan = to_float(values[c_plan])
        # факт выпуска актуален только для 2 ступени
        done = to_float(get(values, c_done)) if stage == 2 else 0.0
        line_1c = alt if use_alt else clean(get(values, c_line))
        rows[m[1]] = {
            "number": m[1],
            "stage": stage,
            "name": name,
            "qty": max(plan - done, 0.0),
            "qty_plan": plan,
            "qty_done": done,
            "status": clean(get(values, c_status)),
            "line_1c": line_1c,
            "line_code": line_from_1c(line_1c),
            "started_at": _datetime(get(values, c_start)),
            "production_date": to_date(get(values, c_prod)),
            "doc_date": _datetime(m[2]),
            "_alt": use_alt,
        }
    return pd.DataFrame(list(rows.values()), columns=ORDER_COLUMNS)


def _yes(value) -> bool:
    return (clean(value) or "").strip().lower() in {"да", "yes", "истина", "true", "1"}


def _parse_legacy(raw: pd.DataFrame, head: int, header: list[str], stage: int) -> pd.DataFrame:
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
        qty = to_float(values[qty_col])
        rows.append({"number": number, "name": name, "qty": qty, "qty_plan": qty, "qty_done": 0.0})
        rows[-1]["stage"] = stage
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)


# Технологические пометки в названии этапа 1 ступени, которые не входят в наименование НФП
_STAGE1_NOISE = re.compile(
    r"\b(тритек|конус\s*\+\s*муссон|для\s+смешивания|смешивание|2\s+или\s+более\s+продуктов|цельное\s*\+\s*рпс)\b",
    re.IGNORECASE,
)
_PARENS = re.compile(r"\(([^()]*)\)")


def stage1_nfp(name: str, characteristics: dict[str, str]) -> tuple[str, str | None]:
    """«Ромашка цветки (крупный порошок) Тритек» → («Ромашка цветки», «Крупный порошок»).

    characteristics — словарь norm_name(фракция) → фракция как в отчёте остатков.
    Скобки с фракцией и технологические пометки убираем, остальные скобки — часть названия
    («Ноготки (календула) цветки»).
    """
    fraction = None

    def drop(m: re.Match) -> str:
        nonlocal fraction
        inner = m[1].strip()
        key = norm_name(inner)
        if key in characteristics:
            fraction = fraction or characteristics[key]
            return " "
        if _STAGE1_NOISE.fullmatch(inner.strip()):
            return " "
        return m[0]

    base = _PARENS.sub(drop, name)
    base = _STAGE1_NOISE.sub(" ", base)
    base = re.sub(r"[()\s]+$", "", re.sub(r"\(\s*\)", " ", base))
    return re.sub(r"\s+", " ", base).strip(), fraction


def link_stage1_orders(
    orders: pd.DataFrame,
    nfp_catalog: list[str],
    characteristics: list[str],
    products: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Заказам 1 ступени — НФП и фракция.

    НФП — изделие спецификации этапа (в написании справочника НФП, если там есть), иначе по
    наименованию этапа + «НФП». Фракция — из скобок в наименовании этапа.
    """
    chars = {norm_name(c): c for c in characteristics if c}
    by_norm = {norm_name(n): n for n in nfp_catalog}
    products = products or {}
    orders = orders.copy()
    orders["nfp"] = None
    orders["nfp_characteristic"] = None
    for idx in orders.index[orders["stage"] == 1]:
        name = orders.at[idx, "name"]
        base, fraction = stage1_nfp(name, chars)
        produced = [by_norm.get(norm_name(p), p) for p in products.get(name, [])]
        orders.at[idx, "nfp"] = produced[0] if produced else by_norm.get(norm_name(f"{base} НФП"))
        orders.at[idx, "nfp_characteristic"] = fraction
    return orders
