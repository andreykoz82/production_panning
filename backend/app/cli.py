"""Командная строка: проверить выгрузки без запуска сервера.

python -m app.cli check "../Исходные данные"
python -m app.cli import "../Исходные данные"   # проверить и сохранить снимок в БД
"""

import argparse
import sys

from app.config import settings
from app.importers.loader import import_folder

SEVERITY_LABEL = {"error": "ОШИБКА", "warning": "ВНИМАНИЕ", "info": "инфо"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["check", "import"])
    parser.add_argument("folder", nargs="?", default=str(settings.data_dir))
    parser.add_argument("--all", action="store_true", help="показать и информационные сообщения")
    args = parser.parse_args(argv)

    result = import_folder(args.folder)
    s = result.summary
    print(
        f"ГП: {s['items_total']} (в планировании {s['items_in_scope']}, со спецификацией "
        f"{s['items_with_spec']}); строк остатков: {s['stock_rows']}; спецификаций: {s['specs_total']}; "
        f"план продаж: {s['plan_from']} … {s['plan_to']}; "
        f"заказов 1/2 ступени: {s.get('orders_stage1', 0)}/{s['orders_stage2']}"
    )
    print(
        f"Проблемы: ошибок {s['issues']['error']}, предупреждений {s['issues']['warning']}, "
        f"сообщений {s['issues']['info']}\n"
    )
    for issue in result.issues:
        if issue.severity == "info" and not args.all:
            continue
        who = f"{issue.item}: " if issue.item else ""
        print(f"[{SEVERITY_LABEL[issue.severity]}] {issue.area}: {who}{issue.message}")

    if args.command == "import":
        from app.db import SessionLocal
        from app.services.snapshots import save_snapshot

        with SessionLocal() as session:
            snap = save_snapshot(session, result, source="folder")
        print(f"\nСнимок сохранён: #{snap.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
