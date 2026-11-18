"""Ресурсные спецификации из 1С ERP (справочник, таблица «Материалы и работы»).

Нормы указаны на 1 000 единиц выпуска: на 1 000 шт. ГП или на 1 000 кг НФП.
Колонка «Ресурсная спецификация, Статус» содержит «<имя>, <статус>».
Одна спецификация может выгружаться несколькими версиями — подряд идущими блоками строк.
Правило (16.11.2026): берём только «Действует»; если действующих версий несколько,
берём версию с максимальной нормой НФП. Материалы-аналоги из других версий взаимозаменяемы.

С 18.11.2026 в отчёт добавлена колонка «Ресурсная спецификация.Изделия по рассчитываемой стоимости.
Номенклатура» — что выпускается по спецификации (ГП или НФП). По ней ГП сопоставляется
со спецификацией надёжнее, чем по похожему имени. Если у спецификации несколько изделий,
1С повторяет строки материалов для каждого — оставляем один набор, изделия собираем в список.
"""

import re
from pathlib import Path

import pandas as pd

from app.importers.common import ReportFormatError, clean, find_row, read_raw, to_float

STATUS_ACTIVE = "Действует"
SPEC_COLUMNS = ["spec", "status", "version", "component", "characteristic", "qty_per_1000", "products"]

_ANALOG_NOISE = re.compile(r"\((импорт)\)|\bс логотипом\b", re.IGNORECASE)


_VERSION_ID = re.compile(r"^Ресурсная спецификация\.(Код|Номер|Ссылка|Идентификатор)", re.IGNORECASE)


def parse_specs(path: Path | str) -> pd.DataFrame:
    """Строки спецификаций. version — номер версии внутри имени; 0 — версии в выгрузке не различить.

    Форматы выгрузки:
    - до 18.11.2026: первая колонка «Ресурсная спецификация, Статус», версии — подряд идущими блоками;
    - с 18.11.2026: «Номенклатура» первой, имя, статус и изделие — отдельными колонками
      («Ресурсная спецификация», «….Статус», «….Изделия по рассчитываемой стоимости.Номенклатура»).
      Строки одной версии идут не подряд, поэтому без кода версии («Ресурсная спецификация.Код»)
      версии одного имени объединяются (см. effective_specs).
    """
    raw = read_raw(path)
    head = find_row(
        raw,
        lambda r: (
            "Количество упаковок" in r and any((c or "").startswith("Ресурсная спецификация") for c in r)
        ),
        "Ресурсная спецификация / Количество упаковок",
    )
    header = [clean(v) or "" for v in raw.iloc[head]]
    combined = header[0].startswith("Ресурсная спецификация")  # старый формат
    try:
        c_comp = header.index("Номенклатура")
        c_char = header.index("Характеристика")
        c_qty = header.index("Количество упаковок")
        c_spec = 0 if combined else header.index("Ресурсная спецификация")
    except ValueError as exc:
        raise ReportFormatError(f"Спецификации: нет колонки {exc}") from exc
    has_status = combined and "Статус" in header[0]
    c_status = (
        None
        if combined
        else next((i for i, h in enumerate(header) if h == "Ресурсная спецификация.Статус"), None)
    )
    c_ver = None if combined else next((i for i, h in enumerate(header) if _VERSION_ID.match(h)), None)
    # «Ресурсная спецификация.Изделия по рассчитываемой стоимости.Номенклатура» — выходное изделие
    c_prod = next(
        (i for i, h in enumerate(header) if h and "издели" in h.lower() and "номенклатур" in h.lower()), None
    )

    rows = []
    versions: dict[str, int] = {}
    version_ids: dict[tuple[str, str], int] = {}
    prev_cell = None
    for values in raw.iloc[head + 1 :].itertuples(index=False):
        cell = clean(values[c_spec])
        component = clean(values[c_comp])
        if not cell or not component:
            continue
        spec, status = cell, None
        if combined:
            if has_status and ", " in cell:
                spec, status = cell.rsplit(", ", 1)
            if cell != prev_cell:  # новый блок строк = новая версия
                versions[spec] = versions.get(spec, 0) + 1
                prev_cell = cell
            version = versions[spec]
        else:
            status = clean(values[c_status]) if c_status is not None else None
            vid = clean(values[c_ver]) if c_ver is not None else None
            if vid:
                version = version_ids.setdefault((spec, vid), sum(1 for k in version_ids if k[0] == spec) + 1)
            else:
                version = 0
        rows.append(
            {
                "spec": spec,
                "status": status,
                "version": version,
                "component": component,
                "characteristic": clean(values[c_char]),
                "qty_per_1000": to_float(values[c_qty]),
                "product": clean(values[c_prod]) if c_prod is not None else None,
            }
        )
    df = pd.DataFrame(rows, columns=[*SPEC_COLUMNS[:-1], "product"])
    return _collapse_products(df)


def _collapse_products(df: pd.DataFrame) -> pd.DataFrame:
    """Изделия версии — списком в колонке products; повтор материалов по изделиям убираем."""
    if df.empty or df["product"].isna().all():
        out = df.drop(columns="product").assign(products=None)[SPEC_COLUMNS]
        return out.assign(row_id=range(len(out)))
    parts = []
    for _, block in df.groupby(["spec", "status", "version"], sort=False, dropna=False):
        products = list(dict.fromkeys(block["product"].dropna()))
        if len(products) > 1:
            # 1С повторяет материалы для каждого изделия — берём строки первого
            block = block[block["product"].isna() | (block["product"] == products[0])]
        parts.append(block.assign(products="; ".join(products) or None))
    out = pd.concat(parts, ignore_index=True).drop(columns="product")[SPEC_COLUMNS]
    return out.assign(row_id=range(len(out)))


def spec_products(specs: pd.DataFrame) -> dict[str, list[str]]:
    """Спецификация → выпускаемые изделия (из колонки «Изделия … Номенклатура»)."""
    out: dict[str, list[str]] = {}
    if "products" not in specs.columns:
        return out
    for spec, products in specs[["spec", "products"]].drop_duplicates().itertuples(index=False):
        if isinstance(products, str) and products:
            for p in products.split("; "):
                if p not in out.setdefault(spec, []):
                    out[spec].append(p)
    return out


def is_nfp_component(name: str) -> bool:
    return name.endswith(" НФП") or " НФП " in name


def analog_key(name: str) -> str:
    """Ключ группы взаимозаменяемых материалов: «Лента отрывная (импорт)» ≡ «Лента отрывная»."""
    return re.sub(r"\s+", " ", _ANALOG_NOISE.sub("", name)).strip().lower()


def _version_score(block: pd.DataFrame) -> float:
    """Норма основного продукта в версии: НФП, а если его нет — сырья/полуфабрикатов с фракцией."""
    nfp = block[block["component"].map(is_nfp_component)]
    if not nfp.empty:
        return float(nfp["qty_per_1000"].max())
    with_fraction = block[
        block["characteristic"].notna() & ~block["component"].str.startswith("Спирт", na=False)
    ]
    return float(with_fraction["qty_per_1000"].sum())


def effective_specs(specs: pd.DataFrame) -> pd.DataFrame:
    """Одна версия на спецификацию: действующая с максимальной нормой НФП.

    Возвращает строки выбранных версий с колонками versions_active (сколько было действующих)
    и analogs (аналоги материала из других действующих версий через «; »).
    """
    active = specs[specs["status"].isna() | (specs["status"] == STATUS_ACTIVE)]
    chosen_parts = []
    for _spec, group in active.groupby("spec", sort=False):
        if (group["version"] == 0).all():
            chosen_parts.append(_merge_versions(group))
            continue
        blocks = dict(list(group.groupby("version", sort=False)))
        scores = {v: _version_score(b) for v, b in blocks.items()}
        best_version = max(blocks, key=lambda v: (scores[v], -v))
        best = blocks[best_version].copy()

        analogs: dict[str, str] = {}
        if len(blocks) > 1:
            others = pd.concat([b for v, b in blocks.items() if v != best_version])
            keys = {analog_key(n): n for n in best["component"]}
            found: dict[str, set[str]] = {}
            for name in set(others["component"]) - set(best["component"]):
                target = keys.get(analog_key(name))
                if target:
                    found.setdefault(target, set()).add(name)
            analogs = {k: "; ".join(sorted(v)) for k, v in found.items()}
        best["versions_active"] = len(blocks)
        best["analogs"] = best["component"].map(analogs)
        chosen_parts.append(best)
    if not chosen_parts:
        return pd.DataFrame(columns=[*SPEC_COLUMNS, "row_id", "versions_active", "analogs"])
    return pd.concat(chosen_parts, ignore_index=True)


def _merge_versions(group: pd.DataFrame) -> pd.DataFrame:
    """Версии одного имени, которые в выгрузке не различить: по каждому материалу (с учётом
    аналогов) — строка с максимальной нормой. Для НФП это совпадает с правилом «версия с
    максимальной нормой НФП», для упаковки даёт запас в пределах разницы между версиями."""
    g = group.assign(_key=group["component"].map(analog_key))
    best = g.sort_values(["qty_per_1000", "row_id"], ascending=[False, True]).drop_duplicates("_key")
    best = best.sort_values("row_id")
    names = g.groupby("_key")["component"].agg(lambda s: list(dict.fromkeys(s)))
    nfp_rows = g[g["component"].map(is_nfp_component)]
    versions = int(nfp_rows["_key"].value_counts().max()) if len(nfp_rows) else 1
    best["versions_active"] = versions
    best["analogs"] = [
        "; ".join(n for n in names[k] if n != comp) or None
        for k, comp in zip(best["_key"], best["component"], strict=True)
    ]
    return best.drop(columns="_key")
