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
    LINES,
    NFP_QUARANTINE_WORKDAYS,
    STAGE2_GROUPS,
)
from app.scheduling.calendars import LineCalendar, validate
from app.scheduling.scheduler import DEFAULT_HORIZON_DAYS, Task, schedule, week_load
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


def sync_orders(session: Session, snapshot_id: int | None = None) -> dict:
    """Открытые заказы 2 ступени из снимка → задачи Ганта (по номеру заказа 1С)."""
    snapshot_id = snapshot_id or latest_snapshot_id(session)
    if not snapshot_id:
        raise LookupError("Нет снимка данных — сначала загрузите выгрузки 1С")
    groups = dict(
        session.execute(
            select(models.Item.name, models.Item.line_group).where(models.Item.snapshot_id == snapshot_id)
        ).all()
    )
    orders = session.scalars(
        select(models.ProductionOrder).where(
            models.ProductionOrder.snapshot_id == snapshot_id, models.ProductionOrder.stage == 2
        )
    ).all()
    existing = {t.number: t for t in session.scalars(select(models.ScheduleTask))}
    added = updated = 0
    seen = set()
    for o in orders:
        item = o.item or o.name
        seen.add(o.number)
        task = existing.get(o.number)
        if task is None:
            session.add(
                models.ScheduleTask(
                    number=o.number, item=item, qty=o.qty, line_group=groups.get(item), warnings=[]
                )
            )
            added += 1
        elif task.qty != o.qty or task.item != item:
            task.qty, task.item, task.line_group = o.qty, item, groups.get(item)
            updated += 1
    removed = [n for n in existing if n not in seen]
    if removed:
        session.execute(delete(models.ScheduleTask).where(models.ScheduleTask.number.in_(removed)))
    session.commit()
    return {"added": added, "updated": updated, "removed": len(removed), "total": len(seen)}


def _month_label(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}"


def _nfp_warnings(session: Session, snapshot_id: int, tasks: list[Task], today: date) -> None:
    """Хватит ли НФП к старту заказа. Резерв на складе НФП считаем заготовленным под открытые заказы."""
    data = load_planning_data(session, snapshot_id, with_reserve=True)
    items = data.items.set_index("name")
    specs = data.specs
    stock = data.stock.assign(qty=data.stock["available"] + data.stock["reserved"])
    key_cols = ["name", "characteristic", "purpose"]
    released = stock["packing_allowed"] == True  # noqa: E712 — None значит «не указано»
    nfp_wh = stock[(stock["role"] == wh.NFP) & released]
    quarantine = stock[stock["role"] == wh.NFP_QUARANTINE]
    raw = stock[stock["role"] == wh.RAW].groupby("name")["qty"].sum().to_dict()
    pool = nfp_wh.groupby(key_cols, dropna=False)["qty"].sum().to_dict()
    q_pool = quarantine.groupby(key_cols, dropna=False)["qty"].sum().to_dict()
    on_nfp_wh = set(stock.loc[stock["role"].isin((wh.NFP, wh.NFP_QUARANTINE)), "name"])
    q_ready = add_workdays(today, NFP_QUARANTINE_WORKDAYS)

    for t in sorted((t for t in tasks if t.start), key=lambda t: t.start):
        if t.item not in items.index:
            continue
        it = items.loc[t.item]
        comp = specs[(specs["spec"] == it["spec"]) & (specs["component"] == it["nfp"])]
        if comp.empty:
            continue
        norm = float(comp["qty_per_1000"].max()) / 1000
        need = t.qty * norm
        if it["nfp"] not in on_nfp_wh and raw.get(it["nfp"], 0) > 0:
            have = raw.get(it["nfp"], 0.0)
            raw[it["nfp"]] = have - min(have, need)
        else:
            key = (it["nfp"], comp["characteristic"].iloc[0], it["purpose"])
            have = max(pool.get(key, 0.0), 0.0)
            use = min(have, need)
            pool[key] = have - use
            if need > have and t.start.date() >= q_ready:
                extra = min(max(q_pool.get(key, 0.0), 0.0), need - have)
                q_pool[key] = q_pool.get(key, 0.0) - extra
                have += extra
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
    snapshot_id = latest_snapshot_id(session)
    run = latest_stage2_run(session, snapshot_id) or latest_stage2_run(session)
    run_lines = {r["item"]: r for r in (run.lines if run else [])}

    tasks = []
    for db in db_tasks:
        r = run_lines.get(db.item, {})
        tasks.append(
            Task(
                key=db.number,
                item=db.item,
                qty=db.qty,
                group=db.line_group or "",
                priority=r.get("priority", math.inf),
                line_code=db.line_code,
                start=db.start,
                locked=db.locked,
                line_locked=db.line_locked,
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
        _nfp_warnings(session, snapshot_id, tasks, now.date())

    by_key = {t.key: t for t in tasks}
    for db in db_tasks:
        t = by_key[db.number]
        db.line_code, db.start, db.end = t.line_code, t.start, t.end
        db.hours, db.changeover, db.locked, db.line_locked = t.hours, t.changeover, t.locked, t.line_locked
        db.available_from = t.end.date() + timedelta(days=GP_CERTIFICATION_DAYS) if t.end else None
        db.warnings = t.warnings
    session.commit()
    return {
        "tasks": len(tasks),
        "scheduled": sum(1 for t in tasks if t.end),
        "with_warnings": sum(1 for t in tasks if t.warnings),
        "run_id": run.id if run else None,
    }


def move_task(
    session: Session,
    task_id: int,
    line_code: str | None,
    start: datetime | None,
    locked: bool | None,
    pin_line: bool | None = None,
    now: datetime | None = None,
) -> None:
    """Ручная правка заказа.

    - перетаскивание (start, line_code) — фиксирует время и линию;
    - выбор линии (line_code + pin_line=True) — закрепляет только линию, время считается автоматически;
    - pin_line=False — снять закрепление линии; locked=False — снять фиксацию времени.
    """
    task = session.get(models.ScheduleTask, task_id)
    if task is None:
        raise LookupError("Заказ не найден")
    if line_code is not None:
        line = next((ln for ln in LINES if ln.code == line_code), None)
        if line is None or line.group != task.line_group:
            raise ValueError(f"Заказ {task.number} можно ставить только на линии группы «{task.line_group}»")
        task.line_code = line_code
    if start is not None:
        task.start = start
    if pin_line is not None:
        task.line_locked = pin_line
    if locked is not None:
        task.locked = locked
    elif start is not None:
        task.locked = True  # перетащили вручную — фиксируем время и линию
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
    sched = [
        Task(
            key=t.number,
            item=t.item,
            qty=t.qty,
            group=t.line_group or "",
            line_code=t.line_code,
            start=t.start,
            locked=t.locked,
            end=t.end,
        )
        for t in db_tasks
    ]
    weeks = max(1, ((date_to - date_from).days // 7) + 1)
    return {
        "lines": [
            {"code": ln.code, "group": ln.group, "per_hour": ln.per_hour} for ln in LINES if ln.stage == 2
        ],
        "tasks": db_tasks,
        "off": off,
        "load": week_load(sched, cals, STAGE2_LINES, date_from, weeks),
    }
