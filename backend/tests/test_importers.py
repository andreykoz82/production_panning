"""Проверки на реальных выгрузках из папки «Исходные данные»."""

from datetime import date

import pandas as pd
import pytest

from app.importers.specs import effective_specs, parse_specs
from app.importers.stock import WAREHOUSE_GP, WAREHOUSE_WHOLESALE
from app.reference.lines import EXCLUDED_GROUPS, STAGE2_GROUPS
from app.reference.warehouses import DEFAULT_ROLES


def test_items(imported):
    items = imported.items
    assert len(items) > 100
    assert items["name"].is_unique
    assert set(items.loc[items["in_scope"], "line_group"]) <= STAGE2_GROUPS
    # розлив и контрактная площадка, если остались в файле, не планируются
    assert set(items.loc[~items["in_scope"], "line_group"]) <= EXCLUDED_GROUPS


def test_stock(imported):
    stock = imported.stock
    assert len(stock) > 1000
    assert set(stock["warehouse"]) <= set(DEFAULT_ROLES)  # все склады отчёта известны
    assert stock["is_defect"].any()
    aira = stock[
        (stock["name"] == "Аир корневища 75г") & stock["warehouse"].isin([WAREHOUSE_GP, WAREHOUSE_WHOLESALE])
    ]
    assert len(aira) > 0 and set(aira["item"]) == {"Аир корневища 75г"}
    assert aira["expiry"].notna().all()


def test_specs_status_and_max_nfp_norm(data_dir):
    specs = parse_specs(data_dir / "Ресурсные спецификации.xlsx")
    assert set(specs["status"].dropna()) == {"Действует", "Закрыта", "В разработке"}
    eff = effective_specs(specs)
    aira = eff[eff["spec"] == "Аир корневища 75г"]
    nfp = aira[aira["component"] == "Аир корневища НФП"]["qty_per_1000"]
    assert list(nfp) == [pytest.approx(78.13)]  # из версий 76,14 / 76,53 / 78,13 — максимальная
    assert aira["versions_active"].iloc[0] == 3
    assert (eff.groupby("spec")["version"].nunique() == 1).all()


def test_specs_analogs(imported):
    eff = imported.specs_effective
    with_analogs = eff[eff["analogs"].notna()]
    assert len(with_analogs) > 0
    assert with_analogs["analogs"].str.contains("Лента отрывная").any()


def test_sales_plan(imported):
    plan = imported.sales_plan
    assert plan["month"].min() == date(2026, 1, 1)
    assert plan["month"].max() == date(2027, 12, 1)
    assert not plan["name"].str.lower().str.startswith("итого").any()
    assert not plan.duplicated(["name", "month"]).any()


def test_orders(imported):
    orders = imported.orders
    assert len(orders) > 0
    assert orders["number"].is_unique
    assert orders["number"].str.startswith("КЛ00-").all()
    assert set(orders["stage"]) == {1, 2}
    st2, st1 = orders[orders["stage"] == 2], orders[orders["stage"] == 1]
    assert st2["item"].notna().all()  # «… (маркированный)» тоже находит ГП
    assert st1["item"].isna().all()
    # открытый остаток = запланировано − выполнено; у 1 ступени факт не учитываем
    assert (st2["qty"] == (st2["qty_plan"] - st2["qty_done"]).clip(lower=0)).all()
    assert (st1["qty_done"] == 0).all() and (st1["qty"] == st1["qty_plan"]).all()
    assert orders["line_code"].notna().all()  # все линии 1С сопоставлены
    assert set(orders.loc[orders["status"] == "Начат", "started_at"].map(type)) <= {pd.Timestamp}
    assert st1["nfp"].notna().mean() > 0.8


def test_stage1_nfp_from_order_name():
    from app.importers.common import norm_name
    from app.importers.orders import stage1_nfp

    fractions = ["Крупный порошок", "Верхнее сито 5 - 7", "Крупный порошок с РПС", "Цельное", "РПС"]
    chars = {norm_name(c): c for c in fractions}
    assert stage1_nfp("Сенна листья (крупный порошок) Тритек", chars) == ("Сенна листья", "Крупный порошок")
    assert stage1_nfp("Ромашка цветки (крупный порошок с РПС) (цельное + РПС)", chars) == (
        "Ромашка цветки",
        "Крупный порошок с РПС",
    )
    assert stage1_nfp("Полынь горькая трава (Верхнее сито 5 - 7) для смешивания", chars) == (
        "Полынь горькая трава",
        "Верхнее сито 5 - 7",
    )
    assert stage1_nfp("Фиточай Лактафитол  (крупный порошок) (Конус+Муссон)", chars) == (
        "Фиточай Лактафитол",
        "Крупный порошок",
    )
    assert stage1_nfp("Ноготки (календула) цветки (крупный порошок)", chars) == (
        "Ноготки (календула) цветки",
        "Крупный порошок",
    )


def test_line_from_1c():
    from app.reference.lines import line_from_1c

    assert line_from_1c("Линия ИМА С 50.1") == "IMA C50.1"  # кириллическая С
    assert line_from_1c("Линия ИМА C 50.2") == "IMA C50.2"  # латинская C
    assert line_from_1c("Линия ИМА C 21.2") == "IMA C21.2"
    assert line_from_1c("Линия ИМА C 21") == "IMA C21"
    assert line_from_1c("Линия ББЛ 3") == "BBL-3"
    assert line_from_1c("Линия Консумаш 1") == "Consumasz"
    assert line_from_1c("Ротоплекс 3 + Тритек") == "Rotoplex-3"
    assert line_from_1c("Ротоплекс 4 (ЛИО5)") == "Rotoplex-4"
    assert line_from_1c("Виникер (ЛИО1)") == "Winicker"
    assert line_from_1c("Линия смешивания 2") == "Mixer-2"
    assert line_from_1c("Муссон 2") == "Musson"
    assert line_from_1c("Неизвестный ВРЦ") is None
