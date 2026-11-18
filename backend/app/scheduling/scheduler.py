"""Расстановка заказов 2 ступени на линии (диаграмма Ганта).

Время делится на слоты по 15 минут. Заказ занимает непрерывную цепочку рабочих слотов линии:
на ночь и выходные он «замирает», но другой заказ в его середину не встаёт.

Очередь на каждой линии собирается так:
1. Начатые в 1С этапы — первыми, в порядке фактического начала; их место не меняется.
2. Очередь, заданная планировщиком вручную (seq) — на своей линии, в заданном порядке.
3. Остальные — по приоритету (месяц, когда кончится запас ГП), на линию своей группы,
   где заказ раньше закончится; закреплённые за линией — только на неё.

Длительность = количество / производительность линии в час + 1 ч переналадки, если перед заказом
на этой линии стоял другой продукт (или ничего; начатый этап, стоящий первым, — без переналадки).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

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
    line_locked: bool = False  # линия закреплена вручную (или начатый этап — линия из 1С)
    seq: int | None = None  # место в ручной очереди линии
    in_progress: bool = False  # этап начат в 1С: стоит первым, без переналадки
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


def _needs_changeover(task: Task, before: str | None) -> bool:
    if before is None and task.in_progress:
        return False
    return before != task.item


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

    def order(t: Task):
        if t.in_progress:
            return (0, t.priority, 0, t.key)
        if t.seq is not None and t.line_locked:
            return (1, 0, t.seq, t.key)
        return (2, t.priority, 0, t.key)

    for t in sorted(tasks, key=order):
        lines = lines_in_group(t.group)
        if not lines:
            t.warnings.append(f"Неизвестная группа линий «{t.group}»")
            continue
        if t.line_locked:
            pinned = [ln for ln in lines if ln.code == t.line_code]
            if pinned:
                lines = pinned
            else:
                t.line_locked = False
                t.warnings.append("Закреплённая линия не из группы продукта — линия выбрана автоматически")
        best = None
        for line in lines:
            st = state(line)
            need_max = _slots_for(t, line, changeover=True)  # с запасом на переналадку
            pos = st.find(need_max, st.first_working_at(start))
            if pos is None:
                continue
            changeover = _needs_changeover(t, st.item_before(pos))
            need = need_max if changeover else _slots_for(t, line, changeover=False)
            end = st.time_of(st.working_idx[pos + need - 1] + 1)
            if best is None or end < best[0]:
                best = (end, line, pos, need, changeover)
        if best is None:
            t.start, t.end = None, None
            if not t.line_locked:
                t.line_code = None
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
