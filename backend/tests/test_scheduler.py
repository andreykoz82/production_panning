from datetime import date, datetime

from app.scheduling.calendars import MODE_24_7, LineCalendar
from app.scheduling.scheduler import Task, schedule, week_load

START = datetime(2026, 11, 17, 9, 0)  # вторник
BBL_SHIFT = 17283  # норма BBL за смену = 8 ч работы


def test_calendar_template_and_overrides():
    cal = LineCalendar()  # по умолчанию 5/2, одна смена
    assert cal.shifts_on(date(2026, 11, 17)) == 1
    assert cal.shifts_on(date(2026, 11, 21)) == 0  # суббота
    assert cal.shifts_on(date(2026, 11, 4)) == 0  # праздник
    cal.overrides[date(2026, 11, 21)] = 2  # рабочая суббота вручную
    assert cal.hours_on(date(2026, 11, 21)) == 16
    assert LineCalendar(mode=MODE_24_7, shifts=3).hours_on(date(2026, 11, 21)) == 24
    three = LineCalendar(shifts=3).working_intervals(date(2026, 11, 17))
    assert len(three) == 1 and three[0][0].hour == 0  # 00:00–24:00 одним интервалом


def test_order_pauses_overnight_and_counts_changeover():
    t = Task("КЛ1", "Мята 50г", BBL_SHIFT, "Линия ББЛ")
    schedule([t], {}, START)
    # 8 ч фасовки + 1 ч переналадки: 09–16 во вторник и 08–10 в среду
    assert t.start == datetime(2026, 11, 17, 9) and t.end == datetime(2026, 11, 18, 10)
    assert t.changeover and t.hours == 9


def test_same_product_back_to_back_has_no_changeover():
    tasks = [Task(f"КЛ{i}", "Аир", 2000, "Линия ББЛ", priority=i) for i in range(4)]
    schedule(tasks, {"BBL-2": LineCalendar(shifts=0), "BBL-3": LineCalendar(shifts=0)}, START)
    assert {t.line_code for t in tasks} == {"BBL-1"}
    assert [t.changeover for t in sorted(tasks, key=lambda t: t.start)] == [True, False, False, False]


def test_only_lines_of_own_group_and_earliest_finish():
    big = Task("КЛ1", "Мята", BBL_SHIFT * 3, "Линия ББЛ", priority=1)
    small = Task("КЛ2", "Аир", 2000, "Линия ББЛ", priority=2)
    fp = Task("КЛ3", "Фп Мята", 1000, "Линия ИМА С 50", priority=3)
    schedule([big, small, fp], {}, START)
    assert big.line_code.startswith("BBL") and small.line_code.startswith("BBL")
    assert small.line_code != big.line_code  # на свободную линию, а не в очередь
    assert fp.line_code in {"IMA C50.1", "IMA C50.2", "IMA C51"}


def test_locked_task_stays_and_others_go_around():
    locked = Task(
        "КЛ1", "Мята", 2000, "Линия ББЛ", line_code="BBL-1", start=datetime(2026, 11, 17, 10), locked=True
    )
    other = Task("КЛ2", "Аир", BBL_SHIFT, "Линия ББЛ", priority=1)
    cals = {"BBL-2": LineCalendar(shifts=0), "BBL-3": LineCalendar(shifts=0)}
    schedule([locked, other], cals, START)
    assert locked.start == datetime(2026, 11, 17, 10) and locked.line_code == "BBL-1"
    assert other.start >= locked.end  # не влезает в окно 09–10, идёт после


def test_weekend_override_used():
    t = Task("КЛ1", "Мята", BBL_SHIFT * 2, "Линия ББЛ")
    cals = {code: LineCalendar(shifts=0) for code in ("BBL-1", "BBL-2", "BBL-3")}
    cals["BBL-1"].overrides = {date(2026, 11, 21): 3, date(2026, 11, 22): 3}  # выходные 24 ч
    schedule([t], cals, START)
    assert t.start.date() == date(2026, 11, 21) and t.end.date() == date(2026, 11, 21)


def test_no_capacity_gives_warning():
    t = Task("КЛ1", "Мята", 1000, "Линия ББЛ")
    cals = {code: LineCalendar(shifts=0) for code in ("BBL-1", "BBL-2", "BBL-3")}
    schedule([t], cals, START, horizon_days=30)
    assert t.end is None and "Не помещается" in t.warnings[0]


def test_week_load():
    t = Task("КЛ1", "Мята", BBL_SHIFT, "Линия ББЛ", line_code="BBL-1")
    schedule([t], {"BBL-2": LineCalendar(shifts=0), "BBL-3": LineCalendar(shifts=0)}, START)
    row = week_load([t], {}, ["BBL-1"], date(2026, 11, 16), 1)[0]
    assert row["available_hours"] == 40 and row["busy_hours"] == 9


def test_pinned_line_with_automatic_time():
    t = Task("КЛ1", "Мята", 2000, "Линия ББЛ", line_code="BBL-3", line_locked=True)
    schedule([t], {}, START)
    assert t.line_code == "BBL-3" and t.start == START and not t.locked


def test_in_progress_task_first_on_line_has_no_changeover():
    cals = {"BBL-1": LineCalendar(mode=MODE_24_7, shifts=3)}
    running = Task(
        key="1",
        item="A",
        qty=17283 / 8,
        group="Линия ББЛ",
        priority=-1,
        line_code="BBL-1",
        line_locked=True,
        in_progress=True,
    )
    nxt = Task(key="2", item="B", qty=17283 / 8, group="Линия ББЛ", line_code="BBL-1", line_locked=True)
    schedule([running, nxt], cals, START)
    assert not running.changeover and running.hours == 1.0
    assert nxt.changeover and nxt.start == running.end
