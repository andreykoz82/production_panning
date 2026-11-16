from datetime import date
from pathlib import Path

import pytest

from app.importers.loader import import_folder

DATA_DIR = Path(__file__).resolve().parents[2] / "Исходные данные"
TODAY = date(2026, 11, 16)

requires_data = pytest.mark.skipif(not DATA_DIR.is_dir(), reason="нет папки «Исходные данные»")


@pytest.fixture(scope="session")
def data_dir() -> Path:
    if not DATA_DIR.is_dir():
        pytest.skip("нет папки «Исходные данные»")
    return DATA_DIR


@pytest.fixture(scope="session")
def imported(data_dir):
    return import_folder(data_dir, today=TODAY)
