import pandas as pd

from app.importers.matching import match_items_to_specs


def test_all_planned_items_have_spec(imported):
    scope = imported.items[imported.items["in_scope"]]
    assert scope["spec"].notna().all()
    assert not scope["spec_needs_confirmation"].any()


def test_spelling_differences_seen_in_1c():
    """Расхождения, которые были в выгрузках 16.11.2026: ищутся без ручной правки."""
    items = pd.DataFrame(
        [
            {"name": 'Фп Фиточай "Мята" (ТМ "Будь здоров!") (БАД)20х1,5г', "printed_material": "-"},
            {"name": "Шиповник плоды низковитаминные 50г", "printed_material": "Б-6М Шиповник 50г"},
            {"name": "Фп Ромашка цветки 20x1,5г", "printed_material": "П-8 Фп Ромашка цветки 20х1,5г"},
        ]
    )
    specs = pd.DataFrame(
        [
            {"spec": 'Фп Фиточай "Мята" (ТМ "Будь здоров!") (БАД)20*1,5г', "component": "Мята НФП"},
            {"spec": "Шиповник низковитаминный плoды 50г", "component": "Б-6М Шиповник 50г"},
            {"spec": "Фп Ромашка цветки 20x1,5г (С РПС)", "component": "П-8 Фп Ромашка цветки 20х1,5г"},
            {"spec": "Ромашка цветки (крупный порошок)", "component": "Ромашка цветки цельные"},
        ]
    )
    m = match_items_to_specs(items, specs).set_index("item")
    assert m.loc[items.name[0], "method"] == "normalized"
    assert m.loc[items.name[1], "spec"] == "Шиповник низковитаминный плoды 50г"
    assert m.loc[items.name[2], "spec"] == "Фп Ромашка цветки 20x1,5г (С РПС)"
    assert m.loc[items.name[2], "method"] == "printed_material"


def test_fuzzy_match_needs_confirmation():
    items = pd.DataFrame([{"name": "Фп Липа цветочки 20x1,5г", "printed_material": "нет такого"}])
    specs = pd.DataFrame([{"spec": "Фп Липа цветки 20x1,5г", "component": "Липа цветки НФП"}])
    m = match_items_to_specs(items, specs).iloc[0]
    assert m["method"] == "fuzzy" and m["needs_confirmation"]


def test_out_of_scope_without_spec_is_not_an_error(imported):
    errors = [i for i in imported.issues if i.severity == "error" and i.area == "specs"]
    assert errors == []
