"""Excel для диспетчера: что фасовать, дефицит материалов и НФП."""

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app import models
from app.reference.warehouses import ROLES

HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
STATUS_FILL = {
    "Можно фасовать": PatternFill("solid", fgColor="E2EFDA"),
    "Частично": PatternFill("solid", fgColor="FFF2CC"),
    "Нельзя": PatternFill("solid", fgColor="FCE4D6"),
    "Нет данных": PatternFill("solid", fgColor="EDEDED"),
}
INT = "# ##0"
KG = "# ##0.0"

LINE_COLUMNS = [
    ("Приоритет", "priority", 9, None),
    ("ГП", "item", 48, None),
    ("ABC", "abc", 5, None),
    ("Группа линий", "line_group", 16, None),
    ("Месяц, когда кончится ГП", "stockout_month", 13, "month"),
    ("План продаж на горизонт, шт", "plan_horizon", 13, INT),
    ("Запас ГП, шт", "gp_stock", 11, INT),
    ("в т.ч. на сертификации", "gp_on_certification", 12, INT),
    ("Открытые заказы, шт", "open_orders", 11, INT),
    ("Потребность, шт", "need", 12, INT),
    ("Можно выпустить сейчас, шт", "feasible", 13, INT),
    ("Статус", "status", 15, None),
    ("Что ограничивает", "limit", 34, None),
    ("НФП", "nfp", 36, None),
    ("Фракция", "nfp_characteristic", 18, None),
    ("Нужно НФП, кг", "nfp_need_kg", 11, KG),
    ("Доступно НФП, кг", "nfp_available_kg", 11, KG),
    ("НФП на карантине, кг", "nfp_quarantine_kg", 11, KG),
    ("НФП без «Фасовка = Да», кг", "nfp_unreleased_kg", 12, KG),
    ("Дефицит НФП, кг", "nfp_shortage_kg", 11, KG),
]
MATERIAL_COLUMNS = [
    ("Материал", "material", 60, None),
    ("Нужно", "need", 13, KG),
    ("На складе", "available", 13, KG),
    ("Дефицит", "shortage", 13, KG),
    ("Не хватает, %", "deviation_pct", 11, "0.0"),
    ("Позиций ГП", "items", 10, INT),
    ("Для каких ГП", "item_names", 80, None),
]
NFP_COLUMNS = [
    ("НФП", "nfp", 44, None),
    ("Фракция", "characteristic", 18, None),
    ("Целевое назначение", "purpose", 32, None),
    ("Нужно, кг", "need_kg", 11, KG),
    ("Доступно, кг", "available_kg", 11, KG),
    ("На карантине, кг", "quarantine_kg", 11, KG),
    ("Карантин закончится", "quarantine_ready", 12, "date"),
    ("Без «Фасовка = Да», кг", "unreleased_kg", 12, KG),
    ("Выпустить на 1 ступени, кг", "shortage_kg", 13, KG),
    ("В открытых заказах 1 ступени, кг", "stage1_orders_kg", 13, KG),
    ("Не покрыто заказами, кг", "uncovered_kg", 13, KG),
    ("Для каких ГП", "items", 80, None),
]


def _value(raw, fmt):
    if raw is None:
        return None
    if fmt in ("month", "date") and isinstance(raw, str):
        return date.fromisoformat(raw)
    return raw


def _sheet(wb: Workbook, title: str, columns, rows: list[dict], status_col: str | None = None):
    ws = wb.create_sheet(title)
    for col, (header, _key, width, _fmt) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 45
    for r, rec in enumerate(rows, start=2):
        for col, (_header, key, _width, fmt) in enumerate(columns, start=1):
            cell = ws.cell(row=r, column=col, value=_value(rec.get(key), fmt))
            if fmt == "month":
                cell.number_format = "mm.yyyy"
            elif fmt == "date":
                cell.number_format = "dd.mm.yyyy"
            elif fmt:
                cell.number_format = fmt
            if status_col and key == status_col and rec.get(key) in STATUS_FILL:
                cell.fill = STATUS_FILL[rec[key]]
    ws.freeze_panes = "C2" if status_col else "B2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def build_stage2_workbook(run: models.PlanRun) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    lines = sorted(run.lines, key=lambda r: r["priority"])
    _sheet(wb, "К фасовке", LINE_COLUMNS, [r for r in lines if r["need"] > 0], status_col="status")
    _sheet(wb, "Дефицит материалов", MATERIAL_COLUMNS, [m for m in run.materials if m["shortage"] > 0])
    _sheet(wb, "Дефицит НФП (1 ступень)", NFP_COLUMNS, run.nfp)
    _sheet(wb, "Все позиции", LINE_COLUMNS, lines, status_col="status")
    _sheet(wb, "Все материалы", MATERIAL_COLUMNS, run.materials)

    ws = wb.create_sheet("Параметры")
    p, s = run.params, run.summary
    info = [
        ("Расчёт", f"#{run.id} от {run.created_at:%d.%m.%Y %H:%M}" if run.created_at else f"#{run.id}"),
        ("Снимок данных", f"#{run.snapshot_id}"),
        ("Дата расчёта", date.fromisoformat(p["calc_date"]).strftime("%d.%m.%Y")),
        ("Горизонт, мес.", p["horizon_months"]),
        ("Позиций к фасовке", s["items_needed"]),
        (
            "— можно полностью / частично / нельзя",
            f"{s['items_full']} / {s['items_partial']} / {s['items_blocked']}",
        ),
        ("Потребность, шт", s["need_units"]),
        ("Можно выпустить сейчас, шт", s["feasible_units"]),
        ("", ""),
        ("Доля плана месяца в горизонте", ""),
        *[(date.fromisoformat(m).strftime("%m.%Y"), f) for m, f in s["month_factors"].items()],
        ("", ""),
        ("Учтённые склады", ""),
        *[(ROLES.get(role, role), ", ".join(names)) for role, names in s.get("warehouses", {}).items()],
        ("", ""),
        (
            "Правила",
            "К фасовке = план на горизонт − запас ГП (склад ГП + опт) − открытые заказы; "
            "не меньше выпуска линии за 1 ч. НФП — с той же фракцией, назначением и «Фасовка = Да». "
            "НФП и материалы распределены по приоритету. Нехватка материала до 10 % — не дефицит. "
            "Задание 1 ступени по НФП округлено до 100 кг.",
        ),
    ]
    for r, (k, v) in enumerate(info, start=1):
        ws.cell(row=r, column=1, value=k).font = Font(bold=bool(k))
        ws.cell(row=r, column=2, value=v)
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 100

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
