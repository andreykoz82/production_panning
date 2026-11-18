"""СТМ — продукция под собственной торговой маркой клиента.

Заказ на производство ставится только после письма клиента, поэтому план продаж по СТМ
не превращается в задание на фасовку: в расчёте СТМ идёт отдельно и после наших продуктов
(НФП и упаковку получает то, что осталось), а в дефициты не попадает.
"""

from app.importers.common import norm_name

# Признак СТМ в наименовании ГП (сравнение без учёта регистра, пробелов и вида кавычек)
STM_MARKERS = ("ТМ Будь здоров",)

_KEYS = tuple(norm_name(m).replace('"', "").replace("'", "") for m in STM_MARKERS)


def is_stm(name: str | None) -> bool:
    if not name:
        return False
    key = norm_name(name).replace('"', "").replace("'", "")
    return any(k in key for k in _KEYS)
