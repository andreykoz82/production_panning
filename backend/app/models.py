"""Таблицы БД. Каждая загрузка выгрузок 1С — отдельный снимок (ImportSnapshot),
поэтому любой расчёт можно воспроизвести на тех данных, на которых он был сделан."""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ImportSnapshot(Base):
    __tablename__ = "import_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    source: Mapped[str] = mapped_column(String(50))  # folder | upload
    files: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)

    issues: Mapped[list["ImportIssue"]] = relationship(cascade="all, delete-orphan")


class _SnapshotRow:
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("import_snapshot.id", ondelete="CASCADE"), index=True)


class Item(_SnapshotRow, Base):
    """Карточка ГП из actual_items + найденная спецификация."""

    __tablename__ = "item"

    name: Mapped[str] = mapped_column(String(300))
    abc: Mapped[str] = mapped_column(String(1))
    mass_g: Mapped[float] = mapped_column(Float)
    line_group: Mapped[str | None] = mapped_column(String(100))
    form: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str | None] = mapped_column(String(50))
    gtin: Mapped[str | None] = mapped_column(String(20))
    nfp: Mapped[str | None] = mapped_column(String(300))
    nfp_source: Mapped[str | None] = mapped_column(String(20))
    purpose: Mapped[str | None] = mapped_column(String(200))
    printed_material: Mapped[str | None] = mapped_column(String(300))
    in_scope: Mapped[bool] = mapped_column(Boolean)
    spec: Mapped[str | None] = mapped_column(String(300))
    spec_method: Mapped[str | None] = mapped_column(String(30))
    spec_score: Mapped[float] = mapped_column(Float, default=0)
    spec_needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)


class StockRow(_SnapshotRow, Base):
    __tablename__ = "stock_row"

    warehouse: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    item: Mapped[str | None] = mapped_column(String(300))  # ссылка на ГП из actual_items
    characteristic: Mapped[str | None] = mapped_column(String(200))
    series: Mapped[str | None] = mapped_column(String(200))
    expiry: Mapped[date | None] = mapped_column(Date)
    purpose: Mapped[str | None] = mapped_column(String(200))
    packing_allowed: Mapped[bool | None] = mapped_column(Boolean)
    on_hand: Mapped[float] = mapped_column(Float)
    reserved: Mapped[float] = mapped_column(Float)
    to_ship: Mapped[float] = mapped_column(Float)
    available: Mapped[float] = mapped_column(Float)
    is_defect: Mapped[bool] = mapped_column(Boolean)


class SpecLine(_SnapshotRow, Base):
    """Строка ресурсной спецификации (все версии). is_effective — версия, взятая в расчёт."""

    __tablename__ = "spec_line"

    spec: Mapped[str] = mapped_column(String(300), index=True)
    status: Mapped[str | None] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer)
    component: Mapped[str] = mapped_column(String(300))
    characteristic: Mapped[str | None] = mapped_column(String(200))
    qty_per_1000: Mapped[float] = mapped_column(Float)
    is_effective: Mapped[bool] = mapped_column(Boolean, default=False)
    analogs: Mapped[str | None] = mapped_column(Text)


class SalesPlanRow(_SnapshotRow, Base):
    __tablename__ = "sales_plan_row"

    name: Mapped[str] = mapped_column(String(300), index=True)
    item: Mapped[str | None] = mapped_column(String(300))
    month: Mapped[date] = mapped_column(Date)
    qty: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(200))


class ProductionOrder(_SnapshotRow, Base):
    __tablename__ = "production_order"

    number: Mapped[str] = mapped_column(String(50))
    stage: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(300))
    item: Mapped[str | None] = mapped_column(String(300))  # ГП (2 ступень)
    qty: Mapped[float] = mapped_column(Float)  # открытый остаток
    qty_plan: Mapped[float | None] = mapped_column(Float)
    qty_done: Mapped[float | None] = mapped_column(Float)  # факт выпуска (только 2 ступень)
    status: Mapped[str | None] = mapped_column(String(50))
    line_1c: Mapped[str | None] = mapped_column(String(100))
    line_code: Mapped[str | None] = mapped_column(String(30))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    production_date: Mapped[date | None] = mapped_column(Date)
    doc_date: Mapped[datetime | None] = mapped_column(DateTime)
    nfp: Mapped[str | None] = mapped_column(String(300))  # НФП (1 ступень)
    nfp_characteristic: Mapped[str | None] = mapped_column(String(100))


class ImportIssue(_SnapshotRow, Base):
    __tablename__ = "import_issue"

    severity: Mapped[str] = mapped_column(String(10))
    area: Mapped[str] = mapped_column(String(20))
    item: Mapped[str | None] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)


class PlanRun(Base):
    """Расчёт потребности. Результат хранится целиком в JSON: строки по ГП, материалы, дефицит НФП."""

    __tablename__ = "plan_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("import_snapshot.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    stage: Mapped[int] = mapped_column(Integer)
    params: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    lines: Mapped[list] = mapped_column(JSON)
    materials: Mapped[list] = mapped_column(JSON)
    nfp: Mapped[list] = mapped_column(JSON)


class LineTemplate(Base):
    """Режим работы линии: «5/2» или «24/7» и смен в день."""

    __tablename__ = "line_template"

    line_code: Mapped[str] = mapped_column(String(30), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))
    shifts: Mapped[int] = mapped_column(Integer)


class LineDay(Base):
    """Ручная правка календаря линии на день."""

    __tablename__ = "line_day"

    line_code: Mapped[str] = mapped_column(String(30), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    shifts: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(200))


class ScheduleTask(Base):
    """Заказ 2 ступени на диаграмме Ганта. Ключ — номер заказа 1С."""

    __tablename__ = "schedule_task"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    stage: Mapped[int] = mapped_column(Integer, default=2)
    item: Mapped[str] = mapped_column(String(300))
    qty: Mapped[float] = mapped_column(Float)
    line_group: Mapped[str | None] = mapped_column(String(100))
    line_code: Mapped[str | None] = mapped_column(String(30))
    start: Mapped[datetime | None] = mapped_column(DateTime)
    end: Mapped[datetime | None] = mapped_column(DateTime)
    hours: Mapped[float] = mapped_column(Float, default=0)
    changeover: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # время и линия зафиксированы
    line_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # только линия
    status: Mapped[str | None] = mapped_column(String(50))  # статус этапа в 1С
    line_1c: Mapped[str | None] = mapped_column(String(100))  # линия, назначенная в 1С
    started_at: Mapped[datetime | None] = mapped_column(DateTime)  # фактическое начало этапа в 1С
    qty_plan: Mapped[float | None] = mapped_column(Float)
    qty_done: Mapped[float | None] = mapped_column(Float)
    available_from: Mapped[date | None] = mapped_column(Date)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class WarehouseRole(Base):
    """Роль склада, назначенная вручную (переопределяет роль по умолчанию)."""

    __tablename__ = "warehouse_role"

    warehouse: Mapped[str] = mapped_column(String(200), primary_key=True)
    role: Mapped[str] = mapped_column(String(30))
