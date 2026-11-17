"""Календари линий: сколько смен работает линия в конкретный день.

У каждой линии есть шаблон — «5/2» (смены только в рабочие дни производственного календаря РФ)
или «24/7» (каждый день) и число смен в день. Поверх шаблона можно задать любой день вручную:
0–3 смены, в том числе в выходной или праздник.

Смены: 1 — 08:00–16:00, 2 — 16:00–24:00, 3 — 00:00–08:00 (смена 8 ч).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.planning.calendar import is_workday
from app.reference.lines import MAX_SHIFTS_PER_DAY, SHIFT_HOURS

MODE_5_2 = "5/2"
MODE_24_7 = "24/7"
DEFAULT_TEMPLATE = (MODE_5_2, 1)

# Начало смен в часах от полуночи, в порядке добавления смен
SHIFT_STARTS = {1: [8], 2: [8, 16], 3: [0, 8, 16]}


@dataclass
class LineCalendar:
    """Шаблон линии + ручные правки по дням."""

    mode: str = DEFAULT_TEMPLATE[0]
    shifts: int = DEFAULT_TEMPLATE[1]
    overrides: dict[date, int] = field(default_factory=dict)

    def template_shifts(self, day: date) -> int:
        if self.mode == MODE_24_7:
            return self.shifts
        return self.shifts if is_workday(day) else 0

    def shifts_on(self, day: date) -> int:
        n = self.overrides.get(day, self.template_shifts(day))
        return max(0, min(MAX_SHIFTS_PER_DAY, n))

    def hours_on(self, day: date) -> int:
        return self.shifts_on(day) * SHIFT_HOURS

    def working_intervals(self, day: date) -> list[tuple[datetime, datetime]]:
        """Рабочие интервалы дня, соседние смены склеены."""
        n = self.shifts_on(day)
        if n == 0:
            return []
        base = datetime.combine(day, datetime.min.time())
        spans = sorted((h, h + SHIFT_HOURS) for h in SHIFT_STARTS[n])
        merged: list[list[int]] = []
        for a, b in spans:
            if merged and merged[-1][1] == a:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        return [(base + timedelta(hours=a), base + timedelta(hours=b)) for a, b in merged]


def validate(mode: str, shifts: int) -> None:
    if mode not in (MODE_5_2, MODE_24_7):
        raise ValueError("Режим — «5/2» или «24/7»")
    if not 0 <= shifts <= MAX_SHIFTS_PER_DAY:
        raise ValueError(f"Смен в день — от 0 до {MAX_SHIFTS_PER_DAY}")
