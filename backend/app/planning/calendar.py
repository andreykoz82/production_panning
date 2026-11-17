"""Производственный календарь РФ (пятидневка).

Праздники — ст. 112 ТК РФ. Переносы выходных — постановления Правительства РФ:
- 2026: № 1466 от 24.09.2025 (3 янв → 9 янв, 4 янв → 31 дек);
- 2027: № 1187 от 17.09.2026 (2 янв → 5 ноя, 3 янв → 31 дек, рабочая суббота 20 фев → выходной 22 фев).
Для других лет праздник, выпавший на выходной (кроме январских), переносится на следующий рабочий день.
Новый год — добавить сюда переносы из постановления, когда оно выйдет.
"""

from datetime import date, timedelta
from functools import cache

# (месяц, день) нерабочих праздничных дней
HOLIDAYS = [(1, d) for d in range(1, 9)] + [(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)]

# Переносы по постановлениям: дополнительные выходные и рабочие дни
EXTRA_DAYS_OFF = {
    2026: {date(2026, 1, 9), date(2026, 3, 9), date(2026, 5, 11), date(2026, 12, 31)},
    2027: {
        date(2027, 2, 22),
        date(2027, 5, 3),
        date(2027, 5, 10),
        date(2027, 6, 14),
        date(2027, 11, 5),
        date(2027, 12, 31),
    },
}
EXTRA_WORKDAYS = {
    2026: set(),
    2027: {date(2027, 2, 20)},
}


@cache
def _days_off(year: int) -> frozenset[date]:
    holidays = {date(year, m, d) for m, d in HOLIDAYS}
    off = set(holidays)
    if year in EXTRA_DAYS_OFF:
        off |= EXTRA_DAYS_OFF[year]
    else:
        # Общее правило ст. 112 ТК РФ без постановления
        for h in sorted(holidays):
            if h.month == 1 or h.weekday() < 5:
                continue
            d = h + timedelta(days=1)
            while d.weekday() >= 5 or d in off:
                d += timedelta(days=1)
            off.add(d)
    return frozenset(off)


def is_workday(d: date) -> bool:
    if d in EXTRA_WORKDAYS.get(d.year, set()):
        return True
    return d.weekday() < 5 and d not in _days_off(d.year)


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def month_end(d: date) -> date:
    return add_months(month_start(d), 1) - timedelta(days=1)


def workdays(start: date, end: date) -> int:
    """Рабочих дней с start по end включительно."""
    n, d = 0, start
    while d <= end:
        n += is_workday(d)
        d += timedelta(days=1)
    return n


def workdays_in_month(d: date) -> int:
    return workdays(month_start(d), month_end(d))


def add_workdays(d: date, n: int) -> date:
    """Дата через n рабочих дней после d (карантин НФП: 5 рабочих дней)."""
    while n > 0:
        d += timedelta(days=1)
        n -= is_workday(d)
    return d
