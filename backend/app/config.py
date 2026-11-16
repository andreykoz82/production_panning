from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Настройки приложения. Переопределяются переменными окружения с префиксом PP_."""

    model_config = SettingsConfigDict(env_prefix="PP_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{REPO_ROOT / 'planning.db'}"
    # Папка с выгрузками из 1С (по умолчанию — «Исходные данные» в корне репозитория)
    data_dir: Path = REPO_ROOT / "Исходные данные"


settings = Settings()
