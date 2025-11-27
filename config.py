import os
from urllib.parse import urlparse

from dotenv import load_dotenv

# Загружаем .env только локально
# На Railway .env не нужен — переменные берутся из среды
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")


def _validate_database_url(raw_url: str | None) -> str:
    """Ensure DSN uses postgres scheme and fail fast with a helpful hint."""

    if not raw_url:
        raise ValueError("DATABASE_URL is missing! Set it in Railway → Variables.")

    parsed = urlparse(raw_url)

    if parsed.scheme in {"postgres", "postgresql"}:
        return raw_url

    if parsed.scheme == "https":
        raise ValueError(
            "DATABASE_URL looks like an HTTPS URL (e.g. Supabase project URL). "
            "Use the Postgres connection string from Supabase → Settings → Connection string → URI "
            "that starts with postgres:// or postgresql://."
        )

    raise ValueError(
        "DATABASE_URL must start with postgres:// or postgresql:// (got: "
        f"{parsed.scheme or 'no scheme'})."
    )


DATABASE_URL = _validate_database_url(os.getenv("DATABASE_URL"))
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # например: "12345,67890"

# Превращаем строки в список чисел
if ADMIN_IDS:
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",")]
else:
    ADMIN_IDS = []

# Валидация (опционально — можно отключить)
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing! Set it in Railway → Variables.")
