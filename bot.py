import asyncio
import logging
from typing import Any

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, DATABASE_URL

# -------------------- ЛОГИ --------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- БОТ И ДИСПЕТЧЕР --------------------

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
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


def _get_row_value(row: asyncpg.Record | None, *keys: str, default: str = "") -> str:
    """Безопасно достаём значение из asyncpg.Record."""
    if row is None:
        return default
    data: dict[str, Any] = dict(row)
    for key in keys:
        if key in data and data[key] is not None:
            return str(data[key])
    return default


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
            "SELECT * FROM programs ORDER BY name"
        )

    if not programs:
        await message.answer(
            "Привет! 👋\n\n"
            "Пока в базе нет ни одной программы.\n"
            "Добавь их через админку Supabase в таблицу *programs*.",
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
            text=_get_row_value(row, "name", "title", default="Без названия"),
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
        program = await conn.fetchrow("SELECT * FROM programs WHERE id = $1", program_id)
        dances = await conn.fetch(
            "SELECT * FROM dances WHERE program_id = $1 ORDER BY name",
            program_id,
        )

    if program is None:
        await callback.answer("Программа не найдена", show_alert=True)
        return

    if not dances:
        await callback.message.edit_text(
            f"Программа *{_get_row_value(program, 'name', 'title', default='без названия')}* пока пустая."
            "\nДобавьте танцы в таблицу *dances*.",
        )
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for row in dances:
        kb.button(
            text=_get_row_value(row, "name", "title", default="Без названия"),
            callback_data=f"dance:{row['id']}:{program_id}",
        )
    kb.adjust(1)

    await callback.message.edit_text(
        f"Танцы в программе *{_get_row_value(program, 'name', 'title', default='без названия')}*:",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("dance:"))
async def on_dance(callback: CallbackQuery):
    """Выбор танца → показываем фигуры."""
    _, dance_id_str, program_id_str = callback.data.split(":")
    dance_id = int(dance_id_str)
    program_id = int(program_id_str)

    pool = await get_db()
    async with pool.acquire() as conn:
        dance = await conn.fetchrow("SELECT * FROM dances WHERE id = $1", dance_id)
        figures = await conn.fetch(
            "SELECT * FROM figures WHERE dance_id = $1 ORDER BY id",
            dance_id,
        )
        program = await conn.fetchrow("SELECT * FROM programs WHERE id = $1", program_id)

    if dance is None:
        await callback.answer("Танец не найден", show_alert=True)
        return

    if not figures:
        await callback.message.edit_text(
            f"В танце *{_get_row_value(dance, 'name', 'title', default='без названия')}* нет фигур."
            "\nДобавьте их в таблицу *figures*.",
        )
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for row in figures:
        kb.button(
            text=_get_row_value(row, "name", "title", default="Без названия"),
            callback_data=f"figure:{row['id']}:{dance_id}:{program_id}",
        )
    kb.button(
        text="← Назад к программам",
        callback_data=f"program:{program_id}",
    )
    kb.adjust(1)

    await callback.message.edit_text(
        f"Фигуры в танце *{_get_row_value(dance, 'name', 'title', default='без названия')}*\n"
        f"Программа: {_get_row_value(program, 'name', 'title', default='неизвестно')}",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("figure:"))
async def on_figure(callback: CallbackQuery):
    """Показываем описание фигуры."""
    _, figure_id_str, dance_id_str, program_id_str = callback.data.split(":")
    figure_id = int(figure_id_str)
    dance_id = int(dance_id_str)
    program_id = int(program_id_str)

    pool = await get_db()
    async with pool.acquire() as conn:
        figure = await conn.fetchrow("SELECT * FROM figures WHERE id = $1", figure_id)
        dance = await conn.fetchrow("SELECT * FROM dances WHERE id = $1", dance_id)
        program = await conn.fetchrow("SELECT * FROM programs WHERE id = $1", program_id)

    if figure is None:
        await callback.answer("Фигура не найдена", show_alert=True)
        return

    title = _get_row_value(figure, "name", "title", default="Фигура")
    description = _get_row_value(
        figure,
        "description",
        "text",
        "content",
        default="Описание пока не заполнено.",
    )
    level = _get_row_value(figure, "level", "difficulty", default="")
    video = _get_row_value(figure, "video_url", "video", "link", default="")

    parts = [f"*{title}*"]
    if level:
        parts.append(f"Уровень: {level}")
    if description:
        parts.append(description)
    if video:
        if video.startswith("http"):
            parts.append(f"[Видео]({video})")
        else:
            parts.append(f"Видео: {video}")

    kb = InlineKeyboardBuilder()
    kb.button(
        text="← Назад к фигурам",
        callback_data=f"dance:{dance_id}:{program_id}",
    )
    kb.button(
        text="← В программы",
        callback_data=f"program:{program_id}",
    )
    kb.adjust(1)

    await callback.message.edit_text("\n\n".join(parts), reply_markup=kb.as_markup())
    await callback.answer()


# -------------------- ЗАПУСК --------------------


async def main():
    try:
        await dp.start_polling(bot)
    finally:
        if _db_pool is not None:
            await _db_pool.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
