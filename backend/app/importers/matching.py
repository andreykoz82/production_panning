"""Сопоставление наименований между отчётами 1С.

ГП ↔ спецификация ищется по порядку:
1. точное имя;
2. имя после нормализации (регистр, ®, «20*2.0г» = «20х2,0г», латиница-двойник);
3. печатный материал (Б-6М, П-8 …) из actual_items, который входит в спецификацию;
4. нечёткое сравнение имени — такие связи нужно подтвердить в интерфейсе.
"""

import re

import pandas as pd
from rapidfuzz import fuzz, process

from app.importers.common import norm_name

FUZZY_CUTOFF = 85.0
MATCH_COLUMNS = ["item", "spec", "method", "score", "needs_confirmation"]


def match_items_to_specs(items: pd.DataFrame, specs: pd.DataFrame) -> pd.DataFrame:
    """items — из parse_items, specs — из effective_specs (одна версия на спецификацию)."""
    spec_names = list(dict.fromkeys(specs["spec"]))
    exact = set(spec_names)
    by_norm: dict[str, str] = {}
    for name in spec_names:
        by_norm.setdefault(norm_name(name), name)
    specs_by_component: dict[str, list[str]] = {}
    for spec, component in specs[["spec", "component"]].itertuples(index=False):
        specs_by_component.setdefault(norm_name(component), []).append(spec)
    norm_keys = list(by_norm)

    rows = []
    for item in items.itertuples(index=False):
        name = item.name
        key = norm_name(name)
        if name in exact:
            rows.append((name, name, "exact", 100.0, False))
            continue
        if key in by_norm:
            rows.append((name, by_norm[key], "normalized", 100.0, False))
            continue
        candidates = sorted(set(specs_by_component.get(norm_name(item.printed_material), [])))
        if candidates:
            best = max(candidates, key=lambda s: fuzz.ratio(key, norm_name(s)))
            rows.append((name, best, "printed_material", round(fuzz.ratio(key, norm_name(best)), 1), False))
            continue
        hit = process.extractOne(key, norm_keys, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF)
        if hit:
            rows.append((name, by_norm[hit[0]], "fuzzy", round(hit[1], 1), True))
        else:
            rows.append((name, None, None, 0.0, False))
    return pd.DataFrame(rows, columns=MATCH_COLUMNS)


_MARKED = re.compile(r"\(\s*маркированн\w*\s*\)", re.IGNORECASE)


def match_to_catalog(names: pd.Series, catalog: pd.Series) -> pd.Series:
    """Для каждого имени из отчёта — имя из справочника ГП (точно или после нормализации), иначе None."""
    exact = set(catalog)
    by_norm = {norm_name(c): c for c in catalog}

    def find(n: str):
        if n in exact:
            return n
        # «… 20х1,5 г (маркированный)» — спецификация с маркировкой, ГП в справочнике та же
        return by_norm.get(norm_name(n)) or by_norm.get(norm_name(_MARKED.sub("", n)))

    return names.map(find)
