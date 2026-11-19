"""Календари линий и диаграмма Ганта 2 ступени: загрузка, синхронизация с 1С, перепланирование."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models
from app.planning.calendar import add_workdays, is_workday
from app.reference import warehouses as wh
from app.reference.lines import (
    GP_CERTIFICATION_DAYS,
    LINE_BY_CODE,
    LINE_TITLES,
    LINES,
    NFP_QUARANTINE_WORKDAYS,
    STAGE2_GROUPS,
    line_from_1c,
)
from app.scheduling.calendars import LineCalendar, validate
from app.scheduling.scheduler import DEFAULT_HORIZON_DAYS, Task, schedule
from app.services.planning import load_planning_data

STAGE2_LINES = [line.code for line in LINES if line.stage == 2]
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


# ---------- календари


def load_calendars(session: Session) -> dict[str, LineCalendar]:
    cals = {line.code: LineCalendar() for line in LINES}
    for t in session.scalars(select(models.LineTemplate)):
        if t.line_code in cals:
            cals[t.line_code].mode, cals[t.line_code].shifts = t.mode, t.shifts
    for d in session.scalars(select(models.LineDay)):
        if d.line_code in cals:
            cals[d.line_code].overrides[d.day] = d.shifts
    return cals


def set_template(session: Session, line_code: str, mode: str, shifts: int) -> None:
    validate(mode, shifts)
    _check_line(line_code)
    session.merge(models.LineTemplate(line_code=line_code, mode=mode, shifts=shifts))
    session.commit()


def set_days(session: Session, changes: list[dict]) -> None:
    """changes: [{line_code, day, shifts | None, reason}]; shifts=None — вернуть день к шаблону."""
    for ch in changes:
        _check_line(ch["line_code"])
        if ch.get("shifts") is None:
            session.execute(
                delete(models.LineDay).where(
                    models.LineDay.line_code == ch["line_code"], models.LineDay.day == ch["day"]
                )
            )
            continue
        validate("5/2", ch["shifts"])
        day = models.LineDay(
            line_code=ch["line_code"], day=ch["day"], shifts=ch["shifts"], reason=ch.get("reason")
        )
        session.merge(day)
    session.commit()


def reset_month(session: Session, line_code: str | None, month: date) -> None:
    first = month.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    q = delete(models.LineDay).where(models.LineDay.day >= first, models.LineDay.day < nxt)
    if line_code:
        q = q.where(models.LineDay.line_code == line_code)
    session.execute(q)
    session.commit()


def month_grid(session: Session, month: date) -> dict:
    cals = load_calendars(session)
    reasons = {(d.line_code, d.day): d.reason for d in session.scalars(select(models.LineDay))}
    first = month.replace(day=1)
    days = []
    d = first
    while d.month == first.month:
        days.append(d)
        d += timedelta(days=1)
    lines = []
    for line in LINES:
        cal = cals[line.code]
        lines.append(
            {
                "line_code": line.code,
                "title": LINE_TITLES.get(line.code, line.code),
                "stage": line.stage,
                "group": line.group,
                "mode": cal.mode,
                "template_shifts": cal.shifts,
                "days": [
                    {
                        "day": day,
                        "shifts": cal.shifts_on(day),
                        "template": cal.template_shifts(day),
                        "manual": day in cal.overrides,
                        "reason": reasons.get((line.code, day)),
                    }
                    for day in days
                ],
                "hours": sum(cal.hours_on(day) for day in days),
            }
        )
    return {"month": first, "days": [{"day": x, "workday": is_workday(x)} for x in days], "lines": lines}


def capacity(session: Session, first_month: date, months: int = 3, today: date | None = None) -> dict:
    """Сколько выпустят группы линий при текущих календарях: по месяцам и итого.

    Текущий месяц — с сегодняшнего дня. Для 2 ступени рядом — что предстоит выпустить:
    потребность к фасовке из последнего расчёта (на его горизонт) + остаток открытых этапов.
    """
    today = today or date.today()
    cals = load_calendars(session)
    run = latest_stage2_run(session)
    need_by_group: dict[str, float] = {}
    for r in run.lines if run else []:
        need_by_group[r.get("line_group")] = need_by_group.get(r.get("line_group"), 0.0) + (
            r.get("need") or 0.0
        )
    orders_by_group: dict[str, float] = {}
    for t in session.scalars(select(models.ScheduleTask).where(models.ScheduleTask.stage == 2)):
        orders_by_group[t.line_group] = orders_by_group.get(t.line_group, 0.0) + t.qty

    month_starts = []
    m = first_month.replace(day=1)
    for _ in range(months):
        month_starts.append(m)
        m = (m + timedelta(days=32)).replace(day=1)

    groups: dict[str, dict] = {}
    for line in LINES:
        g = groups.setdefault(
            line.group,
            {
                "group": line.group,
                "stage": line.stage,
                "unit": "шт" if line.stage == 2 else "кг",
                "lines": [],
                "months": [{"month": ms, "hours": 0.0, "output": 0.0} for ms in month_starts],
                "need": round(need_by_group[line.group]) if line.group in need_by_group else None,
                "open_orders": round(orders_by_group.get(line.group, 0.0)) if line.stage == 2 else None,
            },
        )
        g["lines"].append(LINE_TITLES.get(line.code, line.code))
        cal = cals[line.code]
        for cell, ms in zip(g["months"], month_starts, strict=True):
            d = max(ms, today)
            hours = 0
            while d.month == ms.month:
                hours += cal.hours_on(d)
                d += timedelta(days=1)
            cell["hours"] += hours
            cell["output"] += hours * line.per_hour
    for g in groups.values():
        for cell in g["months"]:
            cell["output"] = round(cell["output"])
        g["total_hours"] = sum(c["hours"] for c in g["months"])
        g["total"] = sum(c["output"] for c in g["months"])
    return {
        "months": month_starts,
        "from": max(first_month.replace(day=1), today),
        "horizon_months": run.params.get("horizon_months") if run else None,
        "groups": list(groups.values()),
    }


def _check_line(code: str) -> None:
    if code not in {line.code for line in LINES}:
        raise ValueError(f"Нет линии {code}")


# ---------- заказы и Гант


def latest_snapshot_id(session: Session) -> int | None:
    return session.scalar(select(models.ImportSnapshot.id).order_by(models.ImportSnapshot.id.desc()).limit(1))


def latest_stage2_run(session: Session, snapshot_id: int | None = None) -> models.PlanRun | None:
    q = select(models.PlanRun).where(models.PlanRun.stage == 2)
    if snapshot_id:
        q = q.where(models.PlanRun.snapshot_id == snapshot_id)
    return session.scalar(q.order_by(models.PlanRun.id.desc()).limit(1))


STARTED = "Начат"
SOURCE_1C, SOURCE_MANUAL, SOURCE_AUTO = "1c", "manual", "auto"
STM_PRIORITY = 0  # раньше любого нашего продукта (их приоритеты — с 1)


def sync_orders(session: Session, snapshot_id: int | None = None) -> dict:
    """Открытые этапы 2 ступени из снимка → задачи Ганта (по номеру этапа 1С).

    На Гант попадает остаток «запланировано − выполнено». Линия из 1С — начальная;
    у начатых этапов она закрепляется (если планировщик не закрепил свою), остальные
    расставляются автоматически внутри группы линий.
    """
    snapshot_id = snapshot_id or latest_snapshot_id(session)
    if not snapshot_id:
        raise LookupError("Нет снимка данных — сначала загрузите выгрузки 1С")
    item_rows = session.execute(
        select(models.Item.name, models.Item.line_group, models.Item.stm).where(
            models.Item.snapshot_id == snapshot_id
        )
    ).all()
    groups = {name: group for name, group, _ in item_rows}
    stm_items = {name for name, _, stm in item_rows if stm}
    orders = session.scalars(
        select(models.ProductionOrder).where(
            models.ProductionOrder.snapshot_id == snapshot_id,
            models.ProductionOrder.stage == 2,
            models.ProductionOrder.qty > 0,
        )
    ).all()
    existing = {t.number: t for t in session.scalars(select(models.ScheduleTask))}
    added = updated = 0
    seen = set()
    for o in orders:
        item = o.item or o.name
        group = groups.get(item)
        line_1c = o.line_code if o.line_code and LINE_BY_CODE[o.line_code].group == group else None
        started = o.status == STARTED
        seen.add(o.number)
        task = existing.get(o.number)
        if task is None:
            task = models.ScheduleTask(number=o.number, item=item, warnings=[])
            session.add(task)
            added += 1
        else:
            changed = (task.qty, task.item, task.status, task.qty_done) != (o.qty, item, o.status, o.qty_done)
            updated += changed
        task.qty, task.item, task.line_group = o.qty, item, group
        task.status, task.line_1c, task.started_at = o.status, o.line_1c, o.started_at
        # линия — как в 1С, пока планировщик не выбрал другую; начатый этап — всегда как в 1С
        if started or task.line_source in (None, SOURCE_1C):
            _apply_1c(task, line_1c)
        task.qty_plan, task.qty_done = o.qty_plan, o.qty_done
        task.stm = item in stm_items
    removed = [n for n in existing if n not in seen]
    if removed:
        session.execute(delete(models.ScheduleTask).where(models.ScheduleTask.number.in_(removed)))
    session.commit()
    return {"added": added, "updated": updated, "removed": len(removed), "total": len(seen)}


def _month_label(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}"


def _nfp_warnings(
    session: Session, snapshot_id: int, tasks: list[Task], today: date, started: set[str] = frozenset()
) -> None:
    """Хватит ли НФП к старту этапа.

    Диспетчер, оформляя этап в 1С, резервирует под него НФП — на складе НФП или на карантине.
    Поэтому этап сначала берёт зарезервированный НФП (где бы он ни лежал), затем свободный
    с «Фасовка = Да», затем свободный с карантина, если этап начнётся после его окончания
    (5 рабочих дней). Начатые этапы НФП уже получили — их не проверяем и из остатка не вычитаем.
    """
    data = load_planning_data(session, snapshot_id, with_reserve=True)
    items = data.items.set_index("name")
    specs = data.specs
    stock = data.stock
    key_cols = ["name", "characteristic", "purpose"]
    released = stock["packing_allowed"] == True  # noqa: E712 — None значит «не указано»
    is_nfp = stock["role"].isin((wh.NFP, wh.NFP_QUARANTINE))
    reserved = stock[is_nfp].groupby(key_cols, dropna=False)["reserved"].sum().to_dict()
    free = (
        stock[(stock["role"] == wh.NFP) & released]
        .groupby(key_cols, dropna=False)["available"]
        .sum()
        .to_dict()
    )
    q_free = (
        stock[stock["role"] == wh.NFP_QUARANTINE].groupby(key_cols, dropna=False)["available"].sum().to_dict()
    )
    raw_stock = stock[stock["role"] == wh.RAW]
    raw = (raw_stock["available"] + raw_stock["reserved"]).groupby(raw_stock["name"]).sum().to_dict()
    on_nfp_wh = set(stock.loc[is_nfp, "name"])
    q_ready = add_workdays(today, NFP_QUARANTINE_WORKDAYS)

    def take(pool: dict, key, amount: float) -> float:
        got = min(max(pool.get(key, 0.0), 0.0), amount)
        pool[key] = pool.get(key, 0.0) - got
        return got

    for t in sorted((t for t in tasks if t.start and t.key not in started), key=lambda t: t.start):
        if t.item not in items.index:
            continue
        it = items.loc[t.item]
        comp = specs[(specs["spec"] == it["spec"]) & (specs["component"] == it["nfp"])]
        if comp.empty:
            continue
        norm = float(comp["qty_per_1000"].max()) / 1000
        need = t.qty * norm
        if it["nfp"] not in on_nfp_wh and raw.get(it["nfp"], 0) > 0:
            have = take(raw, it["nfp"], need)
        else:
            key = (it["nfp"], comp["characteristic"].iloc[0], it["purpose"])
            have = take(reserved, key, need)
            have += take(free, key, need - have)
            if need > have and t.start.date() >= q_ready:
                have += take(q_free, key, need - have)
        # допуск 1 %: резерв в 1С округлён, нормы в спецификации — тоже
        if need - have > max(0.01 * need, 1.0):
            can = math.floor(have / norm) if norm else 0
            t.warnings.append(
                f"НФП к старту хватит на {_n(can)} шт из {_n(t.qty)}: нужно {_n(need)} кг, есть {_n(have)}"
            )


def _n(x: float) -> str:
    return f"{x:,.0f}".replace(",", "\u00a0")


def replan(session: Session, now: datetime | None = None, horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
    now = now or datetime.now()
    start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    db_tasks = session.scalars(select(models.ScheduleTask).where(models.ScheduleTask.stage == 2)).all()
    for db in db_tasks:  # задачи, созданные до 19.11.2026: ручная очередь остаётся, остальные — как в 1С
        if db.line_source is None:
            if db.seq is not None:
                db.line_source = SOURCE_MANUAL
            else:
                _apply_1c(db)
    snapshot_id = latest_snapshot_id(session)
    run = latest_stage2_run(session, snapshot_id) or latest_stage2_run(session)
    run_lines = {r["item"]: r for r in (run.lines if run else [])}

    # начатые в 1С этапы идут первыми, в порядке фактического начала
    started = sorted(
        (db for db in db_tasks if db.status == STARTED), key=lambda db: (db.started_at or now, db.number)
    )
    started_rank = {db.number: i - len(started) for i, db in enumerate(started)}

    tasks = []
    for db in db_tasks:
        r = run_lines.get(db.item, {})
        tasks.append(
            Task(
                key=db.number,
                item=db.item,
                qty=db.qty,
                group=db.line_group or "",
                # СТМ ставят в 1С по письму клиента — такой заказ ждёт, его делаем раньше наших
                priority=started_rank.get(db.number, STM_PRIORITY if db.stm else r.get("priority", math.inf)),
                line_code=db.line_code,
                start=db.start,
                line_locked=db.line_locked,
                seq=None if db.number in started_rank else db.seq,
                in_progress=db.number in started_rank,
            )
        )
    schedule(tasks, load_calendars(session), start, horizon_days)
    for t in tasks:
        if t.group not in STAGE2_GROUPS:
            t.warnings.append("Позиции нет в actual_items или у неё нет линии 2 ступени")
        stockout = run_lines.get(t.item, {}).get("stockout_month")
        if t.end and stockout:
            ready = t.end.date() + timedelta(days=GP_CERTIFICATION_DAYS)
            month = date.fromisoformat(stockout)
            if ready > month:
                t.warnings.append(
                    f"ГП будет доступна к продаже {ready:%d.%m.%Y}, а запас кончается в {_month_label(month)}"
                )
    if snapshot_id:
        _nfp_warnings(session, snapshot_id, tasks, now.date(), set(started_rank))

    by_key = {t.key: t for t in tasks}
    for db in db_tasks:
        t = by_key[db.number]
        db.line_code, db.start, db.end = t.line_code, t.start, t.end
        db.hours, db.changeover, db.line_locked = t.hours, t.changeover, t.line_locked
        stockout = run_lines.get(t.item, {}).get("stockout_month")
        db.stockout_month = date.fromisoformat(stockout) if stockout else None
        db.available_from = t.end.date() + timedelta(days=GP_CERTIFICATION_DAYS) if t.end else None
        db.warnings = t.warnings
    session.commit()
    return {
        "tasks": len(tasks),
        "scheduled": sum(1 for t in tasks if t.end),
        "with_warnings": sum(1 for t in tasks if t.warnings),
        "run_id": run.id if run else None,
    }


def _editable(task: models.ScheduleTask) -> None:
    if task.status == STARTED:
        raise ValueError(f"Этап {task.number} начат в 1С — его линия и место в очереди не меняются")


def _line_1c(task: models.ScheduleTask) -> str | None:
    """Линия из 1С в кодах приложения, если она из группы линий этого ГП."""
    code = line_from_1c(task.line_1c)
    return code if code and LINE_BY_CODE[code].group == task.line_group else None


def _apply_1c(task: models.ScheduleTask, code: str | None = None) -> None:
    """Линия как в 1С; если в 1С линия не указана или чужой группы — по загрузке."""
    code = code if code is not None else _line_1c(task)
    if code != task.line_code or not task.line_locked:
        task.seq = None
    task.line_source = SOURCE_1C
    if code:
        task.line_code, task.line_locked = code, True
    else:
        task.line_locked = False


def move_task(
    session: Session,
    task_id: int,
    line_code: str | None,
    pin_line: bool | None,
    from_1c: bool = False,
    now=None,
) -> None:
    """Выбор линии у заказа: line_code + pin_line=True — вручную (в конец очереди линии),
    pin_line=False — по загрузке, from_1c=True — как в 1С."""
    task = session.get(models.ScheduleTask, task_id)
    if task is None:
        raise LookupError("Заказ не найден")
    _editable(task)
    if from_1c:
        _apply_1c(task)
    else:
        if line_code is not None:
            _check_group(task, line_code)
            if line_code != task.line_code:
                task.seq = None
            task.line_code = line_code
        if pin_line is not None:
            task.line_locked = pin_line
            task.line_source = SOURCE_MANUAL if pin_line else SOURCE_AUTO
            if not pin_line:
                task.seq = None
    session.commit()
    replan(session, now)


def _check_group(task: models.ScheduleTask, line_code: str) -> None:
    line = LINE_BY_CODE.get(line_code)
    if line is None or line.group != task.line_group:
        raise ValueError(f"Заказ {task.number} можно ставить только на линии группы «{task.line_group}»")


def set_queues(session: Session, queues: dict[str, list[int]], now=None) -> None:
    """Ручная очередь: для каждой переданной линии — заказы в нужном порядке (без начатых).

    Заказы закрепляются за линией и получают место в очереди. Заказы, которые раньше стояли
    в очереди этой линии, но в списке их нет, возвращаются на автоматическую расстановку.
    """
    seen: set[int] = set()
    for line_code, ids in queues.items():
        if line_code not in LINE_BY_CODE:
            raise ValueError(f"Неизвестная линия {line_code}")
        for i, task_id in enumerate(ids):
            task = session.get(models.ScheduleTask, task_id)
            if task is None:
                raise LookupError(f"Заказ {task_id} не найден")
            if task_id in seen:
                raise ValueError(f"Заказ {task.number} указан в нескольких очередях")
            seen.add(task_id)
            _editable(task)
            _check_group(task, line_code)
            if (task.line_code, task.seq) != (line_code, i) or task.line_source != SOURCE_1C:
                task.line_source = SOURCE_MANUAL
            task.line_code, task.line_locked, task.seq = line_code, True, i
    stale = session.scalars(
        select(models.ScheduleTask).where(
            models.ScheduleTask.line_code.in_(list(queues)), models.ScheduleTask.seq.is_not(None)
        )
    ).all()
    for task in stale:
        if task.id not in seen:
            _apply_1c(task)
    session.commit()
    replan(session, now)


def reset_queue(session: Session, line_code: str, now=None) -> None:
    """Вернуть незапущенные заказы линии к линиям из 1С и порядку по приоритету."""
    tasks = session.scalars(select(models.ScheduleTask).where(models.ScheduleTask.line_code == line_code))
    for task in tasks:
        if task.status != STARTED:
            _apply_1c(task)
            task.seq = None
    session.commit()
    replan(session, now)


# ---------- склады


def warehouse_list(session: Session) -> list[dict]:
    """Склады последнего снимка: роль, сколько строк и остатка."""
    from sqlalchemy import func

    snapshot_id = latest_snapshot_id(session)
    overrides = dict(session.execute(select(models.WarehouseRole.warehouse, models.WarehouseRole.role)).all())
    rows = []
    if snapshot_id:
        q = (
            select(models.StockRow.warehouse, func.count(), func.sum(models.StockRow.available))
            .where(models.StockRow.snapshot_id == snapshot_id)
            .group_by(models.StockRow.warehouse)
        )
        rows = session.execute(q).all()
    names = {r[0] for r in rows} | set(overrides)
    stats = {r[0]: (r[1], r[2] or 0.0) for r in rows}
    return [
        {
            "warehouse": name,
            "role": wh.role_of(name, overrides),
            "default_role": wh.role_of(name),
            "manual": name in overrides,
            "known": name in wh.DEFAULT_ROLES,
            "rows": stats.get(name, (0, 0.0))[0],
            "available": stats.get(name, (0, 0.0))[1],
            "in_snapshot": name in stats,
        }
        for name in sorted(names)
    ]


def set_warehouse_role(session: Session, warehouse: str, role: str | None) -> None:
    """role=None — вернуть роль по умолчанию."""
    if role is not None and role not in wh.ROLES:
        raise ValueError(f"Нет роли {role}")
    session.execute(delete(models.WarehouseRole).where(models.WarehouseRole.warehouse == warehouse))
    if role is not None and role != wh.role_of(warehouse):
        session.add(models.WarehouseRole(warehouse=warehouse, role=role))
    session.commit()


def timeline(session: Session, date_from: date, date_to: date) -> dict:
    cals = load_calendars(session)
    db_tasks = session.scalars(select(models.ScheduleTask).where(models.ScheduleTask.stage == 2)).all()
    off = []
    for code in STAGE2_LINES:
        cal = cals[code]
        cursor = datetime.combine(date_from, datetime.min.time())
        d = date_from
        while d <= date_to:
            for a, b in cal.working_intervals(d):
                if a > cursor:
                    off.append({"line_code": code, "start": cursor, "end": a})
                cursor = b
            d += timedelta(days=1)
        end = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        if end > cursor:
            off.append({"line_code": code, "start": cursor, "end": end})
    return {
        "lines": [
            {
                "code": ln.code,
                "title": LINE_TITLES.get(ln.code, ln.code),
                "group": ln.group,
                "per_hour": ln.per_hour,
            }
            for ln in LINES
            if ln.stage == 2
        ],
        "tasks": db_tasks,
        "off": off,
    }
