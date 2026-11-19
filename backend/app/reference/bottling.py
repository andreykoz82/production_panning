"""Розлив — жидкие формы (Стоматофит, Бронхофитол, НЮДА).

Их нет в actual_items (линия розлива не планируется), но в анализе сроков годности ГП они нужны:
серии есть на складе, план продаж есть. Позиции розлива узнаются по наименованию в отчёте
«Остатки ГП со сроками годности» и в плане продаж; экспериментальные серии, образцы и брак — нет.
"""

from app.importers.common import norm_name

BOTTLING_MARKERS = ("Стоматофит", "Бронхофитол", "НЮДА", "сироп", "флакон")
NOT_BOTTLING_MARKERS = ("экспериментальн", "сэмпл", "брак")

_YES = tuple(norm_name(m) for m in BOTTLING_MARKERS)
_NO = tuple(norm_name(m) for m in NOT_BOTTLING_MARKERS)


def is_bottling(name: str | None) -> bool:
    if not name:
        return False
    key = norm_name(name)
    return any(m in key for m in _YES) and not any(m in key for m in _NO)
