"""Расстановка заказов 2 ступени на линии (диаграмма Ганта).

Время делится на слоты по 15 минут. Заказ занимает непрерывную цепочку рабочих слотов линии:
на ночь и выходные он «замирает», но другой заказ в его середину не встаёт.

Правила:
- Длительность = количество / производительность линии в час + 1 ч переналадки,
  если перед заказом на этой линии стоял другой продукт (или ничего).
- Заказ ставится только на линии своей группы; выбирается линия, где он раньше закончится.
- Зафиксированные заказы (перетащенные вручную) остаются на месте, остальные расставляются
  вокруг них по приоритету.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from app.reference.lines import CHANGEOVER_HOURS, LineSpec, lines_in_group
from app.scheduling.calendars import LineCalendar

SLOT = timedelta(minutes=15)
SLOTS_PER_HOUR = 4
DEFAULT_HORIZON_DAYS = 180


@dataclass
class Task:
    key: str  # номер заказа 1С
    item: str
    qty: float
    group: str
    priority: float = math.inf
    line_code: str | None = None
    start: datetime | None = None
    locked: bool = False
    # результат
    end: datetime | None = None
    changeover: bool = False
    hours: float = 0.0
    warnings: list[str] = field(default_factory=list)


class _LineState:
    def __init__(self, line: LineSpec, calendar: LineCalendar, origin: datetime, n_slots: int):
        self.line = line
        self.origin = origin
        working = np.zeros(n_slots, dtype=bool)
        days = n_slots // (24 * SLOTS_PER_HOUR)
        for d in range(days):
            day = origin.date() + timedelta(days=d)
            for a, b in calendar.working_intervals(day):
                working[self._slot(a) : self._slot(b)] = True
        self.working_idx = np.flatnonzero(working)  # номера рабочих слотов
        self.busy = np.zeros(len(self.working_idx), dtype=bool)  # занятость по рабочим слотам
        self.owner: list[str | None] = [None] * len(self.working_idx)

    def _slot(self, t: datetime) -> int:
        return int((t - self.origin) / SLOT)

    def time_of(self, slot: int) -> datetime:
        return self.origin + slot * SLOT

    def first_working_at(self, t: datetime) -> int:
        return int(np.searchsorted(self.working_idx, max(self._slot(t), 0)))

    def item_before(self, pos: int) -> str | None:
        for p in range(pos - 1, -1, -1):
            if self.owner[p] is not None:
                return self.owner[p]
        return None

    def find(self, need: int, from_pos: int) -> int | None:
        """Первая позиция ≥ from_pos, где подряд need свободных рабочих слотов."""
        n = len(self.working_idx)
        if need <= 0 or from_pos + need > n:
            return None
        free = (~self.busy[from_pos:]).astype(np.int32)
        window = np.convolve(free, np.ones(need, dtype=np.int32), mode="valid")
        hits = np.flatnonzero(window == need)
        return from_pos + int(hits[0]) if len(hits) else None

    def occupy(self, pos: int, need: int, key: str, item: str) -> None:
        self.busy[pos : pos + need] = True
        for p in range(pos, pos + need):
            self.owner[p] = item

    def span(self, pos: int, need: int) -> tuple[datetime, datetime]:
        return self.time_of(self.working_idx[pos]), self.time_of(self.working_idx[pos + need - 1] + 1)


def _slots_for(task: Task, line: LineSpec, changeover: bool) -> int:
    hours = task.qty / line.per_hour + (CHANGEOVER_HOURS[2] if changeover else 0)
    task.hours = round(hours, 2)
    return max(1, math.ceil(hours * SLOTS_PER_HOUR))


def schedule(
    tasks: list[Task],
    calendars: dict[str, LineCalendar],
    start: datetime,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> list[Task]:
    """Расставляет задачи; меняет их на месте и возвращает тот же список."""
    origin = datetime.combine(start.date(), datetime.min.time())
    n_slots = horizon_days * 24 * SLOTS_PER_HOUR
    states: dict[str, _LineState] = {}

    def state(line: LineSpec) -> _LineState:
        if line.code not in states:
            states[line.code] = _LineState(line, calendars.get(line.code, LineCalendar()), origin, n_slots)
        return states[line.code]

    for t in tasks:
        t.warnings = []
        t.end = None

    # 1. Зафиксированные — на своих местах
    for t in sorted((t for t in tasks if t.locked and t.line_code and t.start), key=lambda t: t.start):
        line = next((ln for ln in lines_in_group(t.group) if ln.code == t.line_code), None)
        if line is None:
            t.locked = False
            t.warnings.append("Линия не из группы этого продукта — заказ расставлен заново")
            continue
        st = state(line)
        pos = st.first_working_at(t.start)
        changeover = st.item_before(pos) != t.item
        need = _slots_for(t, line, changeover)
        if pos + need > len(st.working_idx):
            t.warnings.append(f"Не помещается в горизонт {horizon_days} дней")
            continue
        if st.busy[pos : pos + need].any():
            t.warnings.append("Пересекается с другим зафиксированным заказом")
        st.occupy(pos, need, t.key, t.item)
        t.start, t.end = st.span(pos, need)
        t.changeover = changeover

    # 2. Остальные — по приоритету, на линию группы, где закончится раньше
    placed_locked = {id(t) for t in tasks if t.locked and t.end is not None}
    for t in sorted((t for t in tasks if id(t) not in placed_locked), key=lambda t: (t.priority, t.key)):
        lines = lines_in_group(t.group)
        if not lines:
            t.warnings.append(f"Неизвестная группа линий «{t.group}»")
            continue
        best = None
        for line in lines:
            st = state(line)
            need_max = _slots_for(t, line, changeover=True)  # с запасом на переналадку
            pos = st.find(need_max, st.first_working_at(start))
            if pos is None:
                continue
            changeover = st.item_before(pos) != t.item
            need = need_max if changeover else _slots_for(t, line, changeover=False)
            end = st.time_of(st.working_idx[pos + need - 1] + 1)
            if best is None or end < best[0]:
                best = (end, line, pos, need, changeover)
        t.locked = False
        if best is None:
            t.line_code, t.start, t.end = None, None, None
            t.warnings.append(f"Не помещается в горизонт {horizon_days} дней — добавьте смены в календарь")
            continue
        _, line, pos, need, changeover = best
        st = state(line)
        st.occupy(pos, need, t.key, t.item)
        t.line_code = line.code
        t.start, t.end = st.span(pos, need)
        t.changeover = changeover
        _slots_for(t, line, changeover)  # часы в задаче — по фактической переналадке
    return tasks


def week_load(
    tasks: list[Task],
    calendars: dict[str, LineCalendar],
    line_codes: list[str],
    first_day: date,
    weeks: int,
) -> list[dict]:
    """Загрузка линий по неделям: часы заказов / рабочие часы календаря."""
    monday = first_day - timedelta(days=first_day.weekday())
    rows = []
    for code in line_codes:
        cal = calendars.get(code, LineCalendar())
        for w in range(weeks):
            ws = datetime.combine(monday + timedelta(weeks=w), datetime.min.time())
            we = ws + timedelta(weeks=1)
            avail = busy = 0.0
            for d in range(7):
                for a, b in cal.working_intervals((ws + timedelta(days=d)).date()):
                    avail += (b - a).total_seconds() / 3600
                    for t in tasks:
                        if t.line_code == code and t.start and t.end:
                            lo, hi = max(a, t.start), min(b, t.end)
                            if hi > lo:
                                busy += (hi - lo).total_seconds() / 3600
            rows.append(
                {
                    "line_code": code,
                    "week_start": ws.date(),
                    "available_hours": avail,
                    "busy_hours": round(busy, 2),
                    "load": round(busy / avail, 3) if avail else None,
                    "_end": we,
                }
            )
    for r in rows:
        r.pop("_end")
    return rows
