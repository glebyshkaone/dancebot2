# Latin Technique Bot

Телеграм-бот-пособие по латиноамериканским танцам по книге Walter Laird.

## Технологии
- Python, aiogram 3
- Supabase (Postgres)
- Railway

## Запуск

1. Создать БД в Supabase, выполнить `supabase_schema.sql`.
2. Заполнить программы / танцы / авторов / фигуры.
3. В `.env` (локально) или в переменных Railway задать:
   - `BOT_TOKEN`
   - `DATABASE_URL`
4. Установить зависимости:

```bash
pip install -r requirements.txt
python bot.py
