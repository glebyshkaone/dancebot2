import asyncio
import logging
from typing import Optional

import asyncpg
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import BOT_TOKEN, DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN, parse_mode="Markdown")
dp = Dispatcher()

_db_pool: Optional[asyncpg.Pool] = None


async def get_db() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        logger.info("Creating DB pool...")
        _db_pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("DB pool created")
    return _db_pool


async def get_or_create_user(tg_user: types.User) -> asyncpg.Record:
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select * from public.users where telegram_id = $1",
            tg_user.id,
        )
        if row:
            return row

        row = await conn.fetchrow(
            """
            insert into public.users (telegram_id, username, first_name, last_name)
            values ($1, $2, $3, $4)
            returning *
            """,
            tg_user.id,
            tg_user.username,
            tg_user.first_name,
            tg_user.last_name,
        )
        return row


async def fetch_programs() -> list[asyncpg.Record]:
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select id, code, name from public.programs order by id"
        )
    return rows


async def fetch_figures(program_id: int) -> list[asyncpg.Record]:
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            select id, code, name
            from public.figures
            where program_id = $1
            order by id
            """,
            program_id,
        )
    return rows


async def fetch_figure(figure_id: int) -> Optional[asyncpg.Record]:
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select
                f.id,
                f.code,
                f.name,
                f.program_id,
                p.name as program_name,
                -- если есть колонка description, возьмём её, иначе будет null
                (select column_default from information_schema.columns
                 where table_name = 'figures' and column_name = 'description') as _dummy,
                f.description
            from public.figures f
            join public.programs p on p.id = f.program_id
            where f.id = $1
            """,
            figure_id,
        )
    return row


def build_main_menu_kb(programs: list[asyncpg.Record], is_admin: bool) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    for p in programs:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=p["name"],
                    callback_data=f"program:{p['id']}",
                )
            ]
        )

    # нижний ряд — общие кнопки
    buttons.append(
        [InlineKeyboardButton(text="💳 Купить полный доступ", callback_data="buy")]
    )
    buttons.append(
        [InlineKeyboardButton(text="ℹ️ О боте", callback_data="about")]
    )

    if is_admin:
        buttons.append(
            [InlineKeyboardButton(text="⚙️ Админка", callback_data="admin")]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_figures_kb(figures: list[asyncpg.Record], program_id: int) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    for f_row in figures:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f_row["name"],
                    callback_data=f"figure:{f_row['id']}",
                )
            ]
        )

    # назад к программам
    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к программам",
                callback_data="back:programs",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(CommandStart())
async def cmd_start(message: Message):
    logger.info("/start from %s (@%s)", message.from_user.id, message.from_user.username)
    user_row = await get_or_create_user(message.from_user)
    programs = await fetch_programs()

    if not programs:
        await message.answer(
            "Привет! 👋\n\n"
            "Пока в базе нет ни одной программы.\n"
            "Добавь их через админку Supabase в таблицу *programs*."
        )
        return

    kb = build_main_menu_kb(programs, is_admin=bool(user_row.get("is_admin")))
    await message.answer("Выбери программу (танец):", reply_markup=kb)


@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    user_row = await get_or_create_user(message.from_user)
    programs = await fetch_programs()
    kb = build_main_menu_kb(programs, is_admin=bool(user_row.get("is_admin")))
    await message.answer("Главное меню:", reply_markup=kb)


@dp.callback_query(F.data == "back:programs")
async def cb_back_programs(callback: CallbackQuery):
    user_row = await get_or_create_user(callback.from_user)
    programs = await fetch_programs()
    kb = build_main_menu_kb(programs, is_admin=bool(user_row.get("is_admin")))

    await callback.message.edit_text("Выбери программу (танец):", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("program:"))
async def cb_program(callback: CallbackQuery):
    _, program_id_str = callback.data.split(":", 1)
    program_id = int(program_id_str)

    figures = await fetch_figures(program_id)
    if not figures:
        await callback.message.edit_text(
            "Для этой программы пока нет фигур.\n"
            "Добавь их в Supabase в таблицу *figures*.",
            reply_markup=None,
        )
        await callback.answer()
        return

    kb = build_figures_kb(figures, program_id=program_id)
    await callback.message.edit_text("Выбери фигуру:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("figure:"))
async def cb_figure(callback: CallbackQuery):
    _, fig_id_str = callback.data.split(":", 1)
    figure_id = int(fig_id_str)

    row = await fetch_figure(figure_id)
    if not row:
        await callback.answer("Фигура не найдена", show_alert=True)
        return

    name = row["name"]
    code = row["code"]
    program_name = row["program_name"]
    description = row.get("description") if "description" in row else None

    text = (
        f"*{name}* (`{code}`)\n"
        f"_Программа_: {program_name}\n\n"
    )

    if description:
        text += description
    else:
        text += "Описание техники ещё не добавлено. Позже здесь будет подробный разбор по Лейрду."

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ К списку фигур",
                    callback_data=f"program:{row['program_id']}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 Купить полный доступ",
                    callback_data="buy",
                )
            ],
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "buy")
async def cb_buy(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Написать @glebyshkaone",
                    url="https://t.me/glebyshkaone",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ В главное меню",
                    callback_data="back:programs",
                )
            ],
        ]
    )

    text = (
        "💳 *Подписка на бот*\n\n"
        "Доступ ко всем фигурам и авторам — *500 ₽ в месяц*.\n\n"
        "Оплата и активация доступа — через @glebyshkaone.\n"
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery):
    text = (
        "Этот бот — конспект по латиноамериканским танцам на основе книги\n"
        "*“The Laird Technique of Latin Dancing” — Walter Laird*.\n\n"
        "Здесь будут:\n"
        "• структуры фигур по танцам\n"
        "• техника и ключевые акценты\n"
        "• сравнение трактовок разных авторов (в будущем)\n\n"
        "Сейчас база пополняется. Если хочешь предложить идеи — пиши @glebyshkaone."
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ В главное меню",
                    callback_data="back:programs",
                )
            ]
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "admin")
async def cb_admin(callback: CallbackQuery):
    user_row = await get_or_create_user(callback.from_user)
    if not user_row.get("is_admin"):
        await callback.answer("У тебя нет прав администратора.", show_alert=True)
        return

    text = (
        "⚙️ *Админка*\n\n"
        "Пока всё управление через Supabase:\n"
        "• Таблица `programs` — добавление/редактирование программ\n"
        "• Таблица `figures` — фигуры по каждой программе\n"
        "• Таблица `users` — флаг is_admin, подписка и т.д.\n\n"
        "Позже можно будет вынести добавление фигур прямо в бот."
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ В главное меню",
                    callback_data="back:programs",
                )
            ]
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


async def main():
    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
