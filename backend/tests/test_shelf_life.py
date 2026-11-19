from datetime import date

import pandas as pd

from app.planning.shelf_life import ShelfLifeParams, simulate_item

CALC = date(2026, 12, 1)


def _lots(*rows):
    return pd.DataFrame(
        [
            {"series": s, "production_date": prod, "expiry": exp, "shelf_life_months": 36, "qty": q}
            for s, prod, exp, q in rows
        ]
    )


def _plan(qty, months=12):
    out, d = {}, CALC
    for _ in range(months):
        out[d] = qty
        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return out


def test_fefo_and_threshold():
    # старая серия: 36 мес., остаточный срок 70 % — 31.01.2027; новая — свежая
    old = ("old", date(2026, 3, 1), date(2029, 3, 1), 6_000)
    new = ("new", date(2026, 11, 1), date(2029, 11, 1), 10_000)
    p = ShelfLifeParams(calc_date=CALC, horizon_months=6, replenish=False)
    r = simulate_item("Мята", _lots(old, new), _plan(3_100), [], p)
    lots = {lot.series: lot for lot in r.lots}
    # FEFO: сначала продаём старую; к 31.01 продано ≈ 2 месяца × 3 100 → остаток уходит в неликвид
    assert lots["old"].illiquid_date == lots["old"].illiquid_from(0.7)
    assert 0 < lots["old"].illiquid_qty < 6_000
    assert lots["new"].illiquid_qty == 0
    assert r.illiquid_now == 0 and r.illiquid_forecast == lots["old"].illiquid_qty


def test_lower_plan_fulfillment_means_more_illiquid():
    lots = _lots(("old", date(2026, 3, 1), date(2029, 3, 1), 6_000))
    full = simulate_item("Мята", lots, _plan(3_100), [], ShelfLifeParams(CALC, 6, replenish=False))
    half = simulate_item(
        "Мята", lots, _plan(3_100), [], ShelfLifeParams(CALC, 6, fulfillment_pct=50, replenish=False)
    )
    assert half.illiquid_forecast > full.illiquid_forecast
    assert round(half.demand) == round(full.demand / 2)


def test_already_illiquid_and_replenishment_by_min_series():
    stale = ("stale", date(2025, 1, 1), date(2028, 1, 1), 500)  # остаточный срок уже < 70 %
    p = ShelfLifeParams(calc_date=CALC, horizon_months=3, cover_months=1)
    r = simulate_item("Мята", _lots(stale), _plan(3_000), [], p, min_series=20_000)
    assert r.illiquid_now == 500
    batches = [lot for lot in r.lots if lot.source == "наработка"]
    assert batches and batches[0].initial == 20_000  # не меньше минимальной серии
    assert r.lost_sales > 0  # первые 2 недели продавать нечего
    assert r.lost_sales < 3_000


def test_open_order_arrives_after_certification():
    order = {
        "item": "Мята",
        "number": "КЛ00-1.1.1",
        "qty": 9_000,
        "produced": date(2026, 12, 10),
        "available": date(2026, 12, 17),
    }
    p = ShelfLifeParams(calc_date=CALC, horizon_months=1, replenish=False)
    r = simulate_item("Мята", _lots(), _plan(3_100), [order], p)
    assert r.produced_orders == 9_000
    assert round(r.lost_sales) == round(3_100 / 31 * 16)  # продаём с 17.12


def test_is_bottling():
    from app.reference.bottling import is_bottling

    assert is_bottling("Стоматофит 50 мл") and is_bottling("Бронхофитол® плющ сироп 100 мл")
    assert not is_bottling("Стоматофит 50 мл, Фармацвет (экспериментальный)")
    assert not is_bottling('Сэмпл-продукт ДЧ "ФармаЦветик® для животика" 1.5г')
    assert not is_bottling("Чага (березовый гриб) 50г")
