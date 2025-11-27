import os
from dotenv import load_dotenv

# Загружаем .env только локально
# На Railway .env не нужен — переменные берутся из среды
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # например: "12345,67890"

# Превращаем строки в список чисел
if ADMIN_IDS:
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",")]
else:
    ADMIN_IDS = []

# Валидация (опционально — можно отключить)
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing! Set it in Railway → Variables.")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing! Set it in Railway → Variables.")
