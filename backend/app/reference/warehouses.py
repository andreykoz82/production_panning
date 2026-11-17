"""Роли складов из отчёта «Остатки по складам»: как каждый склад участвует в расчёте.

Роль по умолчанию задана для известных складов; любой склад можно переназначить в приложении
(раздел «Склады»). Новый склад, которого нет в списке, по умолчанию не учитывается.
"""

import pandas as pd

GP_CERT = "gp_cert"
GP_SALE = "gp_sale"
NFP = "nfp"
NFP_QUARANTINE = "nfp_quarantine"
BYPRODUCTS = "byproducts"
RAW = "raw"
MATERIALS = "materials"
IGNORE = "ignore"

ROLES = {
    GP_CERT: "Готовая продукция на сертификации",
    GP_SALE: "Готовая продукция к продаже",
    NFP: "НФП для фасовки",
    NFP_QUARANTINE: "НФП на карантине",
    BYPRODUCTS: "Продукты обработки сырья (ПП)",
    RAW: "Лекарственное сырьё",
    MATERIALS: "Упаковочные материалы",
    IGNORE: "Не учитывается",
}
GP_ROLES = (GP_CERT, GP_SALE)

DEFAULT_ROLES = {
    "Склад готовой продукции": GP_CERT,
    "Склад оптовой торговли ЛС": GP_SALE,
    "Склад нерасфасованных продуктов": NFP,
    "Склад НФП (карантинное хранение)": NFP_QUARANTINE,
    "Склад продуктов обработки сырья (скл. НФП)": BYPRODUCTS,
    "Склад лексырья": RAW,
    "Материальный склад": MATERIALS,
    # добавлены 17.11.2026
    "Кладовая 2 ступени производства": MATERIALS,  # упаковка, выданная на участок фасовки
    "Производство 2 ступени": IGNORE,  # в основном отходы печатных материалов и материалы в работе
}

WASTE_MARK = "(отход)"


def role_of(warehouse: str, overrides: dict[str, str] | None = None) -> str:
    if overrides and warehouse in overrides:
        return overrides[warehouse]
    return DEFAULT_ROLES.get(warehouse, IGNORE)


def with_roles(stock: pd.DataFrame, overrides: dict[str, str] | None = None) -> pd.DataFrame:
    """Добавляет колонку role. Отходы («(отход)») в материалы не попадают."""
    roles = stock["warehouse"].map(lambda w: role_of(w, overrides))
    waste = stock["name"].str.contains(WASTE_MARK, regex=False, na=False)
    return stock.assign(role=roles.where(~(waste & (roles == MATERIALS)), IGNORE))


def warehouses_by_role(warehouses, overrides: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Какие склады в каком качестве учтены (для параметров расчёта и Excel)."""
    out: dict[str, list[str]] = {}
    for wh in sorted(set(warehouses)):
        out.setdefault(role_of(wh, overrides), []).append(wh)
    return out
