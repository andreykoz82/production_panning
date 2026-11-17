from datetime import date

import pytest

from app.planning.calendar import add_workdays, is_workday, workdays, workdays_in_month

# Нормы по производственному календарю (пятидневка)
WORKDAYS_2026 = [15, 19, 21, 22, 19, 21, 23, 21, 22, 22, 20, 22]
WORKDAYS_2027 = [15, 19, 22, 22, 19, 21, 22, 22, 22, 21, 20, 22]


@pytest.mark.parametrize(("year", "expected"), [(2026, WORKDAYS_2026), (2027, WORKDAYS_2027)])
def test_month_norms(year, expected):
    assert [workdays_in_month(date(year, m, 1)) for m in range(1, 13)] == expected
    assert sum(expected) == 247


def test_transfers():
    assert not is_workday(date(2026, 1, 9))  # перенос с 3 января
    assert not is_workday(date(2026, 12, 31))  # перенос с 4 января
    assert is_workday(date(2027, 2, 20))  # рабочая суббота
    assert not is_workday(date(2027, 2, 22))
    assert not is_workday(date(2027, 11, 5))


def test_remaining_workdays_and_quarantine():
    assert workdays(date(2026, 11, 17), date(2026, 11, 30)) == 10
    # карантин 5 рабочих дней: из пятницы 30.10.2026 через праздник 4 ноября
    assert add_workdays(date(2026, 10, 30), 5) == date(2026, 11, 9)
