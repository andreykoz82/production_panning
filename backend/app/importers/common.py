"""Общие функции разбора отчётов 1С, выгруженных в Excel."""

import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Латинские буквы, которые в 1С иногда попадают в русские слова (например «плoды» с латинской o)
_LATIN_TO_CYR = str.maketrans("aceopxykmthb", "асеорхукмтнв")
_NON_ALNUM = re.compile(r"[^0-9a-zа-я.]+")
_DATE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")


class ReportFormatError(ValueError):
    """Файл не похож на ожидаемый отчёт 1С (не найдены заголовки)."""


def read_raw(path: Path | str) -> pd.DataFrame:
    """Читает первый лист без заголовков: отчёты 1С начинаются с блока параметров."""
    return pd.read_excel(path, header=None, dtype=object)


def find_row(df: pd.DataFrame, predicate: Callable[[list], bool], what: str) -> int:
    for idx, row in enumerate(df.itertuples(index=False)):
        if predicate([clean(v) for v in row]):
            return idx
    raise ReportFormatError(f"Не найдена строка заголовка: {what}")


def clean(value) -> str | None:
    """Строка без пробелов по краям; пустые ячейки и NaN → None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def to_float(value) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_date(value) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def date_in_text(text: str | None) -> date | None:
    """Первая дата вида ДД.ММ.ГГГГ в строке (срок годности в номере серии)."""
    if not text:
        return None
    m = _DATE.search(text)
    if not m:
        return None
    day, month, year = map(int, m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def norm_name(name: str | None) -> str:
    """Ключ для сравнения наименований из разных отчётов 1С.

    Убирает регистр, ®, кавычки, пробелы и пунктуацию, приводит «*» и «x» к «х»,
    десятичную запятую к точке и латинские буквы-двойники к кириллице.
    """
    if not name:
        return ""
    text = name.lower().replace("ё", "е").replace("®", "").replace("*", "х")
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = text.translate(_LATIN_TO_CYR)
    return _NON_ALNUM.sub("", text)
