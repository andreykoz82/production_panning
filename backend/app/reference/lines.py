"""Производственные линии и их мощности из ТЗ.

Производительность 2 ступени указана в штуках ГП за смену (8 ч), 1 ступени — в кг/ч.
Группа 2 ступени совпадает с колонкой «Производственная линия» в actual_items.xlsx:
внутри группы заказ можно ставить на любую линию, между группами — нельзя.
"""

import re
from dataclasses import dataclass

from app.importers.common import norm_name

SHIFT_HOURS = 8
MAX_SHIFTS_PER_DAY = 3
CHANGEOVER_HOURS = {1: 5.0, 2: 1.0}
NFP_QUARANTINE_WORKDAYS = 5
GP_CERTIFICATION_DAYS = 7


@dataclass(frozen=True)
class LineSpec:
    code: str
    stage: int
    group: str
    capacity: float
    unit: str  # "шт/смену" или "кг/ч"
    setters: int
    workers: int
    note: str

    @property
    def per_hour(self) -> float:
        return self.capacity / SHIFT_HOURS if self.unit == "шт/смену" else self.capacity

    @property
    def min_batch(self) -> float | None:
        """Минимальная партия фасовки = выпуск за время переналадки (1 ч). Для 1 ступени не задана."""
        return self.per_hour * CHANGEOVER_HOURS[2] if self.stage == 2 else None


GROUP_BBL = "Линия ББЛ"
GROUP_IMA_C50 = "Линия ИМА С 50"
GROUP_IMA_C21 = "Линия ИМА С 21"
GROUP_CONSUMASZ = "Линия Консумаш"
# Не планируются (решение от 16.11.2026)
EXCLUDED_GROUPS = {"Линия розлива", "Контрактная площадка"}

LINES: list[LineSpec] = [
    LineSpec("Rotoplex-1", 1, "Rotoplex", 180, "кг/ч", 1, 2, "Линия измельчения и очистки"),
    LineSpec("Rotoplex-2", 1, "Rotoplex", 180, "кг/ч", 1, 2, "Линия измельчения и очистки"),
    LineSpec("Rotoplex-3", 1, "Rotoplex", 180, "кг/ч", 1, 2, "Линия измельчения и очистки"),
    LineSpec("Rotoplex-4", 1, "Rotoplex", 180, "кг/ч", 0, 2, "Линия измельчения и очистки"),
    LineSpec("Winicker", 1, "Winicker", 100, "кг/ч", 0, 2, "Линия измельчения и очистки"),
    LineSpec("Mixer-1", 1, "Mixer", 280, "кг/ч", 0, 2, "Линия смешивания"),
    LineSpec("Mixer-2", 1, "Mixer", 280, "кг/ч", 0, 2, "Линия смешивания"),
    LineSpec("Musson", 1, "Musson", 25, "кг/ч", 0, 1, "Обработка микробиологических загрязнений"),
    LineSpec("BBL-1", 2, GROUP_BBL, 17283, "шт/смену", 1, 3, "Фасовка в насыпную пачку"),
    LineSpec("BBL-2", 2, GROUP_BBL, 17283, "шт/смену", 1, 3, "Фасовка в насыпную пачку"),
    LineSpec("BBL-3", 2, GROUP_BBL, 17283, "шт/смену", 1, 3, "Фасовка в насыпную пачку"),
    LineSpec("IMA C50.1", 2, GROUP_IMA_C50, 25917, "шт/смену", 1, 5, "Однокамерные фильтр-пакеты"),
    LineSpec("IMA C50.2", 2, GROUP_IMA_C50, 25917, "шт/смену", 1, 5, "Однокамерные фильтр-пакеты"),
    LineSpec("IMA C51", 2, GROUP_IMA_C50, 25917, "шт/смену", 1, 5, "Однокамерные фильтр-пакеты"),
    LineSpec("IMA C21", 2, GROUP_IMA_C21, 3562, "шт/смену", 1, 3, "Двухкамерные фильтр-пакеты"),
    LineSpec("IMA C21.2", 2, GROUP_IMA_C21, 4007, "шт/смену", 1, 2, "Фасовка Азерчая"),
    LineSpec("Consumasz", 2, GROUP_CONSUMASZ, 7361, "шт/смену", 1, 5, "Однокамерные фильтр-пакеты"),
]

STAGE2_GROUPS = {line.group for line in LINES if line.stage == 2}
LINE_BY_CODE = {line.code: line for line in LINES}

# «Основной ВРЦ» из 1С → код линии. Сравниваем после norm_name (латинская C → кириллическая с).
_LINES_1C = [
    (r"ббл\s*(\d)", lambda m: f"BBL-{m[1]}"),
    (r"има\s*с\s*51", lambda m: "IMA C51"),
    (r"има\s*с\s*50\.?\s*([12])", lambda m: f"IMA C50.{m[1]}"),
    (r"има\s*с\s*21\.\s*2", lambda m: "IMA C21.2"),
    (r"има\s*с\s*21", lambda m: "IMA C21"),
    (r"консумаш", lambda m: "Consumasz"),
    (r"ротоплекс\s*(\d)", lambda m: f"Rotoplex-{m[1]}"),
    (r"виникер", lambda m: "Winicker"),
    (r"смешивани\w*\s*(\d)", lambda m: f"Mixer-{m[1]}"),
    (r"муссон", lambda m: "Musson"),
]


def line_from_1c(name: str | None) -> str | None:
    """Код линии по названию рабочего центра 1С («Линия ИМА С 50.1» → «IMA C50.1»), иначе None."""
    if not name:
        return None
    text = norm_name(name)
    for pattern, code in _LINES_1C:
        m = re.search(pattern, text)
        if m:
            result = code(m)
            return result if result in LINE_BY_CODE else None
    return None


def lines_in_group(group: str) -> list[LineSpec]:
    return [line for line in LINES if line.group == group]
