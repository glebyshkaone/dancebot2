import asyncio
import logging

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, DATABASE_URL

# -------------------- ЛОГИ --------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- БОТ И ДИСПЕТЧЕР --------------------

bot = Bot(BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()

# -------------------- БАЗА ДАННЫХ --------------------

_db_pool: asyncpg.Pool | None = None


async def get_db() -> asyncpg.Pool:
    """Ленивая инициализация пула соединений с БД."""
    global _db_pool
    if _db_pool is None:
        logger.info("Creating DB pool...")
        _db_pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("DB pool created")
    return _db_pool


async def get_or_create_user(tg_user) -> asyncpg.Record:
    """Создаём пользователя в БД, если его ещё нет."""
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1",
            tg_user.id,
        )
        if row is None:
            row = await conn.fetchrow(
                """
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                tg_user.id,
                tg_user.username,
                tg_user.first_name,
                tg_user.last_name,
            )
            logger.info(f"New user created: {tg_user.id} (@{tg_user.username})")
        return row


# -------------------- ХЕНДЛЕРЫ СООБЩЕНИЙ --------------------


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Старт: показываем список программ (Latin / Standard и т.п.)."""
    logger.info(f"/start from {message.from_user.id} (@{message.from_user.username})")

    await get_or_create_user(message.from_user)

    pool = await get_db()
    async with pool.acquire() as conn:
        # Таблица programs: id, name
        programs = await conn.fetch(
            "SELECT id, name FROM programs ORDER BY name"
        )

    if not programs:
        await message.answer(
            "Привет! 👋\n\n"
            "Пока в базе нет ни одной программы.\n"
            "Добавь их через админку Supabase в таблицу *programs*."
        )
        return

    text = (
        "Привет! Это бот-пособие по латине по книге *Walter Laird*.\n\n"
        "▫ В бесплатной версии можно открыть до *5 фигур*.\n"
        "▫ Полный доступ — по подписке *500 ₽/мес* (оплата @glebyshkaone).\n\n"
        "Выбери программу:"
    )

    kb = InlineKeyboardBuilder()
    for row in programs:
        kb.button(
            text=row["name"],
            callback_data=f"program:{row['id']}",
        )
    kb.adjust(1)

    await message.answer(text, reply_markup=kb.as_markup())


@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    await message.answer("pong 🏓")


# DEBUG: логировать любые текстовые сообщения, чтобы видеть,
# что апдейты вообще доходят до бота
@dp.message(F.text)
async def debug_any_text(message: Message):
    logger.info(
        f"Text message from {message.from_user.id} (@{message.from_user.username}): "
        f"{message.text!r}"
    )
    if message.text not in ("/start", "/ping"):
        await message.answer("Используй /start, чтобы открыть меню фигур.")


# -------------------- ХЕНДЛЕРЫ CALLBACK --------------------


@dp.callback_query(F.data.startswith("program:"))
async def on_program(callback: CallbackQuery):
    """Выбор программы → показываем танцы в этой программе."""
    _, program_id_str = callback.data.split(":")
    program_id = int(program_id_str)

    pool = await get_db()
    async with pool.acquire() as conn:
        program = aw
