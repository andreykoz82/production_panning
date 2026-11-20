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


def test_items_optional_series_and_stm_columns(tmp_path):
    from app.importers.items import COLUMNS, parse_items

    base = {c: None for c in COLUMNS}
    rows = [
        {
            **base,
            "Наименование": "Мята 50г",
            "Группа": "a",
            "Масса": 50,
            "min": 5000,
            "max": "50 000",
            "СТМ": "нет",
        },
        {**base, "Наименование": 'Фиточай "Укроп" (ТМ "Будь здоров!") 50г', "СТМ": None},
        {**base, "Наименование": "Чай клиента 20х1,5г", "СТМ": "да"},
    ]
    path = tmp_path / "actual_items.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False)
    items = parse_items(path).set_index("name")
    assert items.loc["Мята 50г", "min_series"] == 5000 and items.loc["Мята 50г", "max_series"] == 50000
    assert not items.loc["Мята 50г", "stm"]
    assert items.loc['Фиточай "Укроп" (ТМ "Будь здоров!") 50г', "stm"]  # пусто — по наименованию
    assert items.loc["Чай клиента 20х1,5г", "stm"]
    assert pd.isna(items.loc["Чай клиента 20х1,5г", "min_series"])


def _spec_report(tmp_path, rows):
    header = [
        "Ресурсная спецификация, Статус",
        "Номенклатура",
        "Характеристика",
        "Количество упаковок",
        "Ресурсная спецификация.Изделия по рассчитываемой стоимости.Номенклатура",
    ]
    path = tmp_path / "specs.xlsx"
    pd.DataFrame([["Параметры:", None, None, None, None], header, *rows]).to_excel(
        path, header=False, index=False
    )
    return path


def test_specs_output_product_and_duplicates(tmp_path):
    from app.importers.specs import effective_specs, parse_specs, spec_products

    s = "Сбор ромашки 20х1,5г, Действует"
    path = _spec_report(
        tmp_path,
        [
            # два изделия у одной спецификации — 1С повторяет материалы для каждого
            [s, "Ромашка НФП", "Крупный порошок", 31.5, "Фп Ромашка цветки 20x1,5г"],
            [s, "П-8 Ромашка", None, 1010, "Фп Ромашка цветки 20x1,5г"],
            [s, "Ромашка НФП", "Крупный порошок", 31.5, "Фп Ромашка цветки 20x1,5г (маркированный)"],
            [s, "П-8 Ромашка", None, 1010, "Фп Ромашка цветки 20x1,5г (маркированный)"],
            [
                "Ромашка цветки (крупный порошок), Действует",
                "Ромашка цветки",
                "Цельное",
                1100,
                "Ромашка цветки НФП",
            ],
        ],
    )
    specs = parse_specs(path)
    one = specs[specs["spec"] == "Сбор ромашки 20х1,5г"]
    assert len(one) == 2  # повтор материалов убран
    assert one["products"].iloc[0] == "Фп Ромашка цветки 20x1,5г; Фп Ромашка цветки 20x1,5г (маркированный)"
    products = spec_products(effective_specs(specs))
    assert products["Ромашка цветки (крупный порошок)"] == ["Ромашка цветки НФП"]


def test_item_matched_to_spec_by_output_product(tmp_path):
    from app.importers.matching import match_items_to_specs
    from app.importers.specs import effective_specs, parse_specs

    path = _spec_report(
        tmp_path,
        [
            # имя спецификации не похоже на ГП, но выпускает именно её
            [
                "Сбор ромашки 20х1,5г, Действует",
                "Ромашка НФП",
                "Крупный порошок",
                31.5,
                "Фп Ромашка цветки 20x1,5г",
            ],
            [
                "Фп Ромашка цветки 20х1,5г, Действует",
                "Ромашка НФП",
                "Крупный порошок",
                30,
                "Фп Ромашка 20x2г",
            ],
        ],
    )
    items = pd.DataFrame([{"name": "Фп Ромашка цветки 20x1,5г", "printed_material": None}])
    m = match_items_to_specs(items, effective_specs(parse_specs(path))).iloc[0]
    assert (m["spec"], m["method"], m["needs_confirmation"]) == ("Сбор ромашки 20х1,5г", "product", False)


def test_specs_new_layout_versions_not_contiguous(tmp_path):
    """С 18.11.2026: «Номенклатура» первой, имя/статус/изделие — отдельными колонками, строки версий вперемешку."""
    from app.importers.specs import effective_specs, parse_specs

    header = [
        "Номенклатура",
        "Характеристика",
        "Ресурсная спецификация.Статус",
        "Ресурсная спецификация.Изделия по рассчитываемой стоимости.Номенклатура",
        "Ресурсная спецификация",
        "Количество упаковок",
    ]
    s, p = "Фп Ромашка 20x1,5г", "Фп Ромашка 20x1,5г"
    rows = [
        ["Ромашка НФП", "КП", "Действует", p, s, 30.5],
        ["П-8 Ромашка", None, "Действует", p, s, 1020],
        ["Мята НФП", "КП", "Действует", "Мята 50г", "Мята 50г", 51],
        ["Ромашка НФП", "КП", "Действует", p, s, 31.25],  # вторая версия
        ["Лента отрывная (импорт)", None, "Действует", p, s, 255],
        ["Лента отрывная", None, "Действует", p, s, 250],
        ["П-8 Ромашка", None, "Действует", p, s, 1020],
        ["Ромашка НФП", "КП", "Закрыта", p, s, 40],
    ]
    path = tmp_path / "specs.xlsx"
    pd.DataFrame([["Параметры:", *[None] * 5], header, *rows]).to_excel(path, header=False, index=False)
    specs = parse_specs(path)
    assert set(specs["version"]) == {0} and specs["products"].notna().all()
    eff = effective_specs(specs).set_index("component")
    one = eff[eff["spec"] == s]
    assert one.loc["Ромашка НФП", "qty_per_1000"] == 31.25  # максимальная норма НФП, «Закрыта» не в счёт
    assert one.loc["Лента отрывная (импорт)", "qty_per_1000"] == 255
    assert one.loc["Лента отрывная (импорт)", "analogs"] == "Лента отрывная"
    assert len(one) == 3 and one["versions_active"].iloc[0] == 2


def test_specs_component_kind(tmp_path):
    """С 18.11.2026: «Номенклатура, Вид номенклатуры» — вид после последней запятой."""
    from app.importers.specs import parse_specs

    header = [
        "Номенклатура, Вид номенклатуры",
        "Характеристика",
        "Ресурсная спецификация",
        "Количество упаковок",
    ]
    rows = [
        ["Ромашка цветки НФП, Нерасфасованные продукты КЛС", "КП", "Фп Ромашка 20x1,5г", 31],
        [
            "Лента термотрансферная для принтера, 135 мм, Вспомогательные материалы для производства",
            None,
            "Фп Ромашка 20x1,5г",
            4.7,
        ],
        ["Спирт этиловый", None, "Фп Ромашка 20x1,5г", 0.01],
    ]
    path = tmp_path / "specs.xlsx"
    pd.DataFrame([["Параметры:", None, None, None], header, *rows]).to_excel(path, header=False, index=False)
    specs = parse_specs(path).set_index("component")
    assert specs.loc["Ромашка цветки НФП", "component_kind"] == "Нерасфасованные продукты КЛС"
    assert specs.loc["Лента термотрансферная для принтера, 135 мм", "component_kind"] == (
        "Вспомогательные материалы для производства"
    )
    assert pd.isna(specs.loc["Спирт этиловый", "component_kind"])


def test_orders_alternative_work_center(tmp_path):
    """Линия — альтернативный ВРЦ с «Использовать» = «Да», иначе основной; строки этапа схлопываются."""
    from app.importers.orders import parse_orders

    header = [
        "Этап производства",
        "Статус",
        "Спецификация",
        "Подразделение-исполнитель",
        "Основной ВРЦ.Наименование",
        "Альтернативные виды рабочих центров.Вид рабочего центра",
        "Альтернативные виды рабочих центров.Использовать",
        "Запланировано",
        "Выполнено",
    ]
    doc = "Этап производства КЛ00-{} от 10.11.2026 13:44:31"
    stage2 = "Вторая ступень производства"
    rows = [
        [
            doc.format("1.1.1"),
            "Начат",
            "Мята",
            stage2,
            "Линия ИМА С 50.1",
            "Линия ИМА C 50.2",
            "Нет",
            100,
            40,
        ],
        [doc.format("1.1.1"), "Начат", "Мята", stage2, "Линия ИМА С 50.1", "Линия ИМА С 51", "Да", 100, 40],
        [doc.format("2.1.1"), "Начат", "Мята", stage2, "Линия ББЛ 1", "Линия ББЛ 2", "Нет", 50, None],
        [doc.format("2.1.1"), "Начат", "Мята", stage2, "Линия ББЛ 1", "Линия ББЛ 3", None, 50, None],
        [doc.format("3.1.1"), "К выполнению", "Мята", stage2, "Линия Консумаш 1", None, None, 30, None],
        ["Итого", None, None, None, None, None, None, 180, 40],
    ]
    path = tmp_path / "orders.xlsx"
    pd.DataFrame([["Параметры:"], [], header, *rows]).to_excel(path, header=False, index=False)
    orders = parse_orders(path).set_index("number")
    assert list(orders.index) == ["КЛ00-1.1.1", "КЛ00-2.1.1", "КЛ00-3.1.1"]
    assert orders["line_code"].to_dict() == {
        "КЛ00-1.1.1": "IMA C51",
        "КЛ00-2.1.1": "BBL-1",
        "КЛ00-3.1.1": "Consumasz",
    }
    assert orders.loc["КЛ00-1.1.1", "qty"] == 60


def test_finished_stages_are_not_orders_and_track_releases(imported):
    """Завершённые этапы — не открытые заказы; свежий выпуск без серии в остатках ГП — «не оприходовано»."""
    assert not imported.orders["status"].str.startswith("Заверш").any()
    rel = imported.releases
    assert len(rel) > 0 and rel["received"].any()
    transit = rel[rel["in_transit"]]
    assert (transit["received"] == False).all()  # noqa: E712
    # серия этапа есть в остатках ГП → поступил
    lot_series = set(imported.gp_lots["series"].astype(str))
    assert rel.loc[rel["received"] == True, "series"].isin(lot_series).all()  # noqa: E712


def test_releases_in_transit_rules():
    from app.importers.loader import _releases

    catalog = pd.Series(["Мята 50г", "Чага 50г"])
    finished = pd.DataFrame(
        {
            "number": ["A", "B", "C", "D"],
            "name": ["Мята 50г", "Чага 50г", "Мята 50г", "Чага 50г"],
            "item": ["Мята 50г", "Чага 50г", "Мята 50г", "Чага 50г"],
            "gp_name": ["Мята 50г", "Чага 50г", "Мята 50г", "Чага 50г"],
            "gp_series": ["111126", "221126", "331026", None],
            "gp_expiry": [None] * 4,
            "qty_done": [1000.0, 500.0, 700.0, 300.0],
            "qty_plan": [1000.0, 500.0, 700.0, 300.0],
            "production_date": [
                date(2026, 11, 19),
                date(2026, 11, 18),
                date(2026, 10, 30),
                date(2026, 11, 19),
            ],
            "started_at": [pd.NaT] * 4,
            "line_code": ["BBL-1"] * 4,
        }
    )
    lots = pd.DataFrame({"series": ["221126"]})
    rel = _releases(finished, lots, catalog, date(2026, 11, 20)).set_index("number")
    assert rel.loc["A", "in_transit"] and rel.loc["A", "received"] is False  # серии нет в остатках
    assert rel.loc["B", "received"] is True and not rel.loc["B", "in_transit"]  # поступил
    assert not rel.loc["C", "in_transit"]  # старше 14 дней — видимо, уже продан
    assert rel.loc["D", "received"] is None and not rel.loc["D", "in_transit"]  # нет серии — проверить нельзя
