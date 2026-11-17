"""Проверки на реальных выгрузках из папки «Исходные данные»."""

from datetime import date

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
    assert orders["item"].notna().all()
