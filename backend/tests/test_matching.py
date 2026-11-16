import pandas as pd

from app.importers.matching import match_items_to_specs


def test_all_planned_items_have_spec(imported):
    scope = imported.items[imported.items["in_scope"]]
    assert scope["spec"].notna().all()
    assert not scope["spec_needs_confirmation"].any()


def test_known_spelling_differences(imported):
    by_name = imported.items.set_index("name")
    cases = {
        'Фп Фиточай "Мята" (ТМ "Будь здоров!") (БАД)20х1,5г': 'Фп Фиточай "Мята" (ТМ "Будь здоров!") (БАД)20*1,5г',
        "Шиповник плоды низковитаминные 50г": "Шиповник низковитаминный плoды 50г",
        "Фп Ромашка цветки 20x1,5г": "Фп Ромашка цветки 20x1,5г (С РПС)",
        "Ламинарии слоевища (морская капуста) 100г": "Ламинарии слоевища (Морская капуста) 100г",
        "Валериана корневища с корнями 50г": "Валериана корневища и корни 50г",
    }
    for item, spec in cases.items():
        assert by_name.loc[item, "spec"] == spec, item


def test_fuzzy_match_needs_confirmation():
    items = pd.DataFrame([{"name": "Фп Липа цветочки 20x1,5г", "printed_material": "нет такого"}])
    specs = pd.DataFrame([{"spec": "Фп Липа цветки 20x1,5г", "component": "Липа цветки НФП"}])
    m = match_items_to_specs(items, specs).iloc[0]
    assert m["method"] == "fuzzy" and m["needs_confirmation"]


def test_out_of_scope_without_spec_is_not_an_error(imported):
    errors = [i for i in imported.issues if i.severity == "error" and i.area == "specs"]
    assert errors == []
