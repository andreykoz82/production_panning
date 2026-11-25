from datetime import date

import pandas as pd
import pytest

from app.planning.stage2 import (
    STATUS_BLOCKED,
    STATUS_FULL,
    STATUS_NOT_NEEDED,
    STATUS_PARTIAL,
    PlanningData,
    Stage2Params,
    calculate_stage2,
)

CALC = date(2026, 11, 17)  # в ноябре осталось 10 рабочих дней из 20 → доля 0,5
PACK = "Лекарств. продукция (моно), пачка"


def _data(items, stock=(), plan=(), orders=(), specs=()):
    return PlanningData(
        items=pd.DataFrame(
            [{"abc": "B", "line_group": "Линия ББЛ", "purpose": PACK, "in_scope": True, **i} for i in items]
        ),
        stock=pd.DataFrame(
            [
                {
                    "item": None,
                    "characteristic": None,
                    "purpose": None,
                    "packing_allowed": None,
                    "is_defect": False,
                    **s,
                }
                for s in stock
            ],
            columns=[
                "warehouse",
                "name",
                "item",
                "characteristic",
                "purpose",
                "packing_allowed",
                "available",
                "is_defect",
            ],
        ),
        specs=pd.DataFrame(list(specs), columns=["spec", "component", "characteristic", "qty_per_1000"]),
        plan=pd.DataFrame(list(plan), columns=["item", "month", "qty"]),
        orders=pd.DataFrame(list(orders), columns=["number", "item", "qty", "stage"]),
    )


def _spec(name, nfp="Мята НФП", nfp_kg=50.0, box="Б-6М Мята"):
    return [(name, nfp, "Верхнее сито 5 - 7", nfp_kg), (name, box, None, 1010.0)]


def _nfp(qty, purpose=PACK, packing=True, char="Верхнее сито 5 - 7", wh="Склад нерасфасованных продуктов"):
    return {
        "warehouse": wh,
        "name": "Мята НФП",
        "characteristic": char,
        "purpose": purpose,
        "packing_allowed": packing,
        "available": qty,
    }


def _box(qty, name="Б-6М Мята"):
    return {"warehouse": "Материальный склад", "name": name, "available": qty}


def test_horizon_uses_remaining_workdays_and_subtracts_stock_and_orders():
    data = _data(
        items=[{"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"}],
        specs=_spec("Мята 50г"),
        plan=[
            ("Мята 50г", date(2026, 11, 1), 10_000),
            ("Мята 50г", date(2026, 12, 1), 10_000),
            ("Мята 50г", date(2027, 1, 1), 10_000),
            ("Мята 50г", date(2027, 2, 1), 99_999),
        ],
        stock=[
            {
                "warehouse": "Склад готовой продукции",
                "name": "Мята 50г",
                "item": "Мята 50г",
                "available": 3_000,
            },
            {
                "warehouse": "Склад оптовой торговли ЛС",
                "name": "Мята 50г",
                "item": "Мята 50г",
                "available": 2_000,
            },
            {
                "warehouse": "Склад готовой продукции",
                "name": "Мята 50г (брак)",
                "item": "Мята 50г",
                "available": 500,
                "is_defect": True,
            },
            _nfp(10_000),
            _box(100_000),
        ],
        orders=[("КЛ00-1", "Мята 50г", 4_000, 2)],
    )
    r = calculate_stage2(data, Stage2Params(3, CALC)).lines.iloc[0]
    # 5 000 (половина ноября) + 10 000 + 10 000 − 5 000 запас − 4 000 заказ
    assert r["plan_horizon"] == 25_000
    assert r["need"] == 16_000
    assert r["gp_on_certification"] == 3_000
    assert r["status"] == STATUS_FULL and r["feasible"] == 16_000
    assert r["stockout_month"] == date(2026, 12, 1)


def test_need_rounded_up_to_min_batch():
    data = _data(
        items=[{"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"}],
        specs=_spec("Мята 50г"),
        plan=[("Мята 50г", date(2026, 12, 1), 100)],
        stock=[_nfp(10_000), _box(100_000)],
    )
    r = calculate_stage2(data, Stage2Params(2, CALC)).lines.iloc[0]
    assert r["need"] == 2161  # выпуск BBL за 1 ч = 17 283 / 8


def test_nfp_must_match_fraction_purpose_and_packing_flag():
    data = _data(
        items=[{"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"}],
        specs=_spec("Мята 50г"),
        plan=[("Мята 50г", date(2026, 12, 1), 10_000)],
        stock=[
            _nfp(1_000, char="Крупный порошок"),  # не та фракция
            _nfp(1_000, purpose="Лекарств. продукция (моно), ф/п"),  # не то назначение
            _nfp(300, packing=None),  # нет «Фасовка = Да»
            _nfp(200, wh="Склад НФП (карантинное хранение)"),
            _nfp(100),  # подходит: хватит на 2 000 пачек по 50 г
            _box(100_000),
        ],
    )
    res = calculate_stage2(data, Stage2Params(2, CALC))
    r = res.lines.iloc[0]
    assert r["nfp_available_kg"] == 100
    assert r["nfp_unreleased_kg"] == 300 and r["nfp_quarantine_kg"] == 200
    assert r["feasible"] == 0  # 2 000 шт меньше минимальной партии 2 161
    assert r["status"] == STATUS_BLOCKED and r["limit"] == "НФП"
    nfp = res.nfp.iloc[0]
    assert nfp["need_kg"] == 500 and nfp["shortage_kg"] == 200  # 500 − 100 доступно − 200 карантин


def test_all_resources_short_of_full_need_are_reported():
    item = "Пижма цветки 75г"
    box = "Б-6М Пижма цветки 75г"
    data = _data(
        items=[{"name": item, "nfp": "Пижма НФП", "spec": item}],
        specs=_spec(item, nfp="Пижма НФП", nfp_kg=75, box=box) + [(item, "Этикетка", None, 1000)],
        plan=[(item, date(2026, 12, 1), 10_000)],
        stock=[_box(500, box), _box(10_000, "Этикетка")],
    )
    row = calculate_stage2(data, Stage2Params(2, CALC)).lines.iloc[0]
    assert row["limit"].splitlines() == ["НФП", box]
    assert row["feasible"] == 0


def test_shared_nfp_goes_to_earlier_stockout_first():
    data = _data(
        items=[
            {"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"},
            {"name": "Мята 75г", "nfp": "Мята НФП", "spec": "Мята 75г", "abc": "A"},
        ],
        specs=_spec("Мята 50г") + _spec("Мята 75г", nfp_kg=75.0, box="Б-6М Мята 75"),
        plan=[("Мята 50г", date(2026, 11, 1), 10_000), ("Мята 75г", date(2027, 1, 1), 10_000)],
        stock=[_nfp(600), _box(100_000), _box(100_000, "Б-6М Мята 75")],
    )
    lines = calculate_stage2(data, Stage2Params(3, CALC)).lines.set_index("item")
    assert lines.loc["Мята 50г", "priority"] == 1  # кончается в ноябре, раньше чем 75 г в январе
    assert lines.loc["Мята 50г", "feasible"] == 5_000 and lines.loc["Мята 50г", "status"] == STATUS_FULL
    # остаток НФП 350 кг → 4 666 пачек по 75 г из 10 000
    assert lines.loc["Мята 75г", "feasible"] == 4_666 and lines.loc["Мята 75г", "status"] == STATUS_PARTIAL


def test_import_analog_counts_as_material():
    data = _data(
        items=[{"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"}],
        specs=_spec("Мята 50г") + [("Мята 50г", "Лента отрывная", None, 1.0)],
        plan=[("Мята 50г", date(2026, 12, 1), 10_000)],
        stock=[_nfp(10_000), _box(100_000), _box(4, "Лента отрывная (импорт)"), _box(4, "Лента отрывная")],
    )
    r = calculate_stage2(data, Stage2Params(2, CALC)).lines.iloc[0]
    assert r["feasible"] == 8_000 and r["limit"] == "Лента отрывная"


def test_material_shortage_within_10_percent_is_not_deficit():
    data = _data(
        items=[{"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"}],
        specs=_spec("Мята 50г") + [("Мята 50г", "Лента отрывная", None, 1.0)],
        plan=[("Мята 50г", date(2026, 12, 1), 10_000)],
        stock=[_nfp(10_000), _box(100_000), _box(9, "Лента отрывная")],  # 9 из 10 — 90 %
    )
    res = calculate_stage2(data, Stage2Params(2, CALC))
    r = res.lines.iloc[0]
    assert r["feasible"] == 10_000 and r["status"] == STATUS_FULL
    tape = res.materials.set_index("material").loc["Лента отрывная"]
    assert tape["shortage"] == 0 and tape["within_tolerance"] and tape["deviation_pct"] == 10.0
    assert res.summary["materials_short"] == 0


def test_nfp_task_rounded_to_100_kg():
    from app.planning.stage2 import round_kg

    assert round_kg(4543.2) == 4500 and round_kg(4550) == 4600 and round_kg(30) == 100 and round_kg(0) == 0


def test_enough_stock_needs_nothing():
    data = _data(
        items=[{"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"}],
        specs=_spec("Мята 50г"),
        plan=[("Мята 50г", date(2026, 12, 1), 1_000)],
        stock=[
            {
                "warehouse": "Склад готовой продукции",
                "name": "Мята 50г",
                "item": "Мята 50г",
                "available": 5_000,
            }
        ],
    )
    r = calculate_stage2(data, Stage2Params(3, CALC)).lines.iloc[0]
    assert r["need"] == 0 and r["status"] == STATUS_NOT_NEEDED
    assert r["stockout_month"] is None  # 5 000 хватает на весь план


def test_released_not_received_counts_as_stock():
    """Этап завершён, серия ещё не на складе ГП — это запас, повторно выпускать не нужно."""
    data = _data(
        items=[{"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г"}],
        specs=_spec("Мята 50г"),
        plan=[("Мята 50г", date(2026, 12, 1), 10_000)],
    )
    before = calculate_stage2(data, Stage2Params(3, CALC)).lines.iloc[0]
    data.in_transit = pd.DataFrame([{"item": "Мята 50г", "qty": 9_737.0}])
    after = calculate_stage2(data, Stage2Params(3, CALC)).lines.iloc[0]
    assert after["gp_in_transit"] == 9_737 and after["need"] < before["need"]


def test_horizon_validation():
    with pytest.raises(ValueError):
        Stage2Params(0, CALC)


def test_real_data(imported):
    data = PlanningData(
        items=imported.items,
        stock=imported.stock,
        specs=imported.specs_effective,
        plan=imported.sales_plan,
        orders=imported.orders,
    )
    res = calculate_stage2(data, Stage2Params(3, CALC))
    lines = res.lines
    assert len(lines) == imported.items["in_scope"].sum()
    assert (lines["need"] >= 0).all() and (lines["feasible"] <= lines["need"]).all()
    assert list(lines["priority"]) == list(range(1, len(lines) + 1))
    assert res.summary["month_factors"]["2026-11-01"] == 0.5


def test_stage1_orders_cover_nfp_shortage_across_purposes():
    from app.planning.stage2 import _apply_stage1_orders

    records = [
        {"nfp": "Мята НФП", "characteristic": "Крупный порошок", "purpose": "А", "shortage_kg": 100.0},
        {"nfp": "Мята НФП", "characteristic": "Крупный порошок", "purpose": "Б", "shortage_kg": 300.0},
        {"nfp": "Мята НФП", "characteristic": "Цельное", "purpose": "А", "shortage_kg": 50.0},
    ]
    orders = pd.DataFrame(
        [
            ("КЛ00-1.1.1", None, 250.0, 1, "Мята НФП", "Крупный порошок"),
            ("КЛ00-2.1.1", None, 100.0, 1, "Мята НФП", "Крупный порошок"),
            ("КЛ00-3.1.1", "Мята 50г", 999.0, 2, None, None),
        ],
        columns=["number", "item", "qty", "stage", "nfp", "nfp_characteristic"],
    )
    _apply_stage1_orders(records, orders)
    a, b, whole = records
    assert (b["stage1_orders_kg"], b["uncovered_kg"]) == (300.0, 0.0)  # сначала больший дефицит
    assert (a["stage1_orders_kg"], a["uncovered_kg"]) == (50.0, 50.0)  # остаток 350 − 300
    assert (whole["stage1_orders_kg"], whole["uncovered_kg"]) == (0.0, 50.0)  # другая фракция


def test_stm_goes_after_own_products_and_out_of_deficits():
    stm = 'Фиточай "Мята" (ТМ "Будь здоров!")(БАД) 50г'
    data = _data(
        items=[
            {"name": stm, "nfp": "Мята НФП", "spec": stm, "abc": "A"},
            {"name": "Мята 50г", "nfp": "Мята НФП", "spec": "Мята 50г", "abc": "C"},
        ],
        specs=_spec(stm) + _spec("Мята 50г"),
        # у СТМ запас кончается раньше, но НФП сначала получает наш продукт
        plan=[(stm, date(2026, 11, 1), 20_000), ("Мята 50г", date(2026, 12, 1), 10_000)],
        stock=[_nfp(650), _box(100_000)],  # 650 кг НФП = 13 000 пачек
    )
    res = calculate_stage2(data, Stage2Params(2, CALC))
    lines = res.lines.set_index("item")
    assert not lines.loc["Мята 50г", "stm"] and lines.loc[stm, "stm"]
    assert lines.loc["Мята 50г", "priority"] == 1 and lines.loc["Мята 50г", "feasible"] == 10_000
    assert lines.loc[stm, "need"] == 10_000 and lines.loc[stm, "feasible"] == 3_000  # остаток НФП
    s = res.summary
    assert s["items_needed"] == 1 and s["need_units"] == 10_000  # СТМ в сводку не входит
    assert s["stm_items"] == 1 and s["stm_need_units"] == 10_000 and s["stm_feasible_units"] == 3_000
    assert res.nfp.empty  # прогноз СТМ не создаёт задания 1 ступени
    assert res.materials["need"].sum() == 10_000 * 1.01  # упаковка — только под наш продукт


def test_series_min_and_max():
    from app.planning.stage2 import _series_plan

    assert _series_plan(3_000, 2_160, 5_000, 50_000) == (5_000, 1)  # меньше минимальной серии
    assert _series_plan(120_000, 2_160, 5_000, 50_000) == (120_000, 3)  # 3 серии по 40 000
    assert _series_plan(52_000, 2_160, 30_000, 50_000) == (60_000, 2)  # 2 серии, каждая ≥ 30 000
    assert _series_plan(52_000, 2_160, None, None) == (52_000, 1)


def test_series_limits_need_and_feasible():
    data = _data(
        items=[
            {
                "name": "Мята 50г",
                "nfp": "Мята НФП",
                "spec": "Мята 50г",
                "min_series": 8_000,
                "max_series": 6_000,
            }
        ],
        specs=_spec("Мята 50г"),
        plan=[("Мята 50г", date(2026, 12, 1), 10_000)],
        stock=[_nfp(350), _box(100_000)],  # 350 кг = 7 000 пачек — меньше минимальной серии
    )
    r = calculate_stage2(data, Stage2Params(2, CALC)).lines.iloc[0]
    assert r["need"] == 16_000 and r["series"] == 2 and r["series_size"] == 8_000
    assert r["feasible"] == 0 and r["status"] == STATUS_BLOCKED
