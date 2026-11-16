from datetime import date

import pytest

from app.importers.common import date_in_text, norm_name
from app.reference.lines import LINES


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            'Фп Фиточай "Мята" (ТМ "Будь здоров!") (БАД)20х1,5г',
            'Фп Фиточай "Мята" (ТМ "Будь здоров!") (БАД)20*1,5г',
        ),
        ("Фп Ромашка цветки 20x1,5г", "Фп Ромашка цветки 20х1,5 г"),
        ("Шиповник низковитаминный плoды 50г", "Шиповник низковитаминный плоды 50г"),  # латинская «o»
        (
            'Фп "Щедрость природы® Фиточай очищающий" 20х2,0 г',
            'Фп "Щедрость природы Фиточай очищающий" 20х2,0 г',
        ),
    ],
)
def test_norm_name_equal(a, b):
    assert norm_name(a) == norm_name(b)


def test_norm_name_keeps_different_products_apart():
    assert norm_name("Мята перечная листья 50г") != norm_name("Мята перечная листья 75г")


def test_date_in_series():
    assert date_in_text("270426, 30.04.2029, РОССИЯ, Красногорсклексредства") == date(2029, 4, 30)
    assert date_in_text(None) is None


def test_stage2_capacity_is_per_shift():
    bbl = next(line for line in LINES if line.code == "BBL-1")
    assert bbl.per_hour == pytest.approx(17283 / 8)
    assert bbl.min_batch == pytest.approx(17283 / 8)  # минимальная партия = 1 ч переналадки
    rotoplex = next(line for line in LINES if line.code == "Rotoplex-1")
    assert rotoplex.per_hour == 180
