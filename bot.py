import asyncio
import asyncpg

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, DATABASE_URL


# ===============================
#  ИНИЦИАЛИЗАЦИЯ
# ===============================

bot = Bot(BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
db_pool: asyncpg.pool.Pool | None = None


# ===============================
#  БАЗА ДАННЫХ
# ===============================

async def get_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool


async def get_or_create_user(tg_user):
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "select * from users where id=$1",
            tg_user.id
        )
        if not user:
            user = await conn.fetchrow(
                "insert into users (id, username) values ($1, $2) returning *",
                tg_user.id,
                tg_user.username
            )
        return user


async def register_figure_open(user_id: int, figure_id: str):
    """
    Лимит на бесплатный доступ: 5 разных фигур.
    Возвращает (allowed: bool, count: int | None)
    """
    pool = await get_db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("select * from users where id=$1", user_id)

        # если нет пользователя — создаём
        if not user:
            user = await conn.fetchrow(
                "insert into users (id) values ($1) returning *",
                user_id
            )

        # подписан — ограничения нет
        if user["is_subscribed"]:
            return True, None

        # проверяем, открывал ли ранее эту фигуру
        exists = await conn.fetchrow(
            "select 1 from user_figure_accesses where user_id=$1 and figure_id=$2",
            user_id, figure_id
        )
        if exists:
            return True, None

        # считаем количество уникальных фигур
        count = await conn.fetchval(
            "select count(*) from user_figure_accesses where user_id=$1",
            user_id
        )

        if count >= 5:
            return False, count

        # записываем новый доступ
        await conn.execute(
            "insert into user_figure_accesses (user_id, figure_id) values ($1, $2)",
            user_id, figure_id
        )

        await conn.execute(
            "update users set free_figures_opened=$1 where id=$2",
            count + 1, user_id
        )

        return True, count + 1


# ===============================
#  ОБРАБОТЧИКИ
# ===============================

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await get_or_create_user(message.from_user)

    pool = await get_db()
    async with pool.acquire() as conn:
        programs = await conn.fetch(
            "select id, name from programs order by name"
        )

    text = (
        "Привет! Это бот-пособие по латине по книге *Walter Laird*.\n\n"
        "▫️ В бесплатной версии можно открыть до *5 фигур*.\n"
        "▫️ Полный доступ — по подписке *500₽/мес* (оплата @glebyshkaone).\n\n"
        "Выбери программу:"
    )

    kb = InlineKeyboardBuilder()
    for row in programs:
        kb.button(text=row["name"], callback_data=f"program:{row['id']}")
    kb.adjust(1)

    await message.answer(text, reply_markup=kb.as_markup())


@dp.message(F.text == "/help")
async def cmd_help(message: Message):
    await cmd_start(message)


# --------- ПРОГРАММЫ ---------

@dp.callback_query(F.data.startswith("program:"))
async def cb_program(callback: CallbackQuery):
    program_id = callback.data.split(":", 1)[1]

    pool = await get_db()
    async with pool.acquire() as conn:
        dances = await conn.fetch(
            "select id, name from dances where program_id=$1 order by name",
            program_id
        )

    if not dances:
        await callback.answer("Пока нет танцев в этой программе.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for d in dances:
        kb.button(text=d["name"], callback_data=f"dance:{d['id']}")
    kb.button(text="⬅️ В начало", callback_data="back:root")
    kb.adjust(1)

    await callback.message.edit_text(
        "Выбери танец:",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


# --------- ТАНЦЫ ---------

@dp.callback_query(F.data.startswith("dance:"))
async def cb_dance(callback: CallbackQuery):
    dance_id = callback.data.split(":", 1)[1]

    pool = await get_db()
    async with pool.acquire() as conn:
        figures = await conn.fetch(
            "select id, name from figures where dance_id=$1 order by name",
            dance_id
        )

    if not figures:
        await callback.answer("Для этого танца пока нет фигур.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for f in figures:
        kb.button(text=f["name"], callback_data=f"figure:{f['id']}")
    kb.button(text="⬅️ В начало", callback_data="back:root")
    kb.adjust(1)

    await callback.message.edit_text(
        "Выбери фигуру:",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


# --------- ФИГУРА ---------

@dp.callback_query(F.data.startswith("figure:"))
async def cb_figure(callback: CallbackQuery):
    figure_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    # проверка лимита
    allowed, _ = await register_figure_open(user_id, figure_id)

    if not allowed:
        text = (
            "🔥 Лимит *5 бесплатных фигур* исчерпан.\n\n"
            "Чтобы получить полный доступ:\n"
            "1) Оплати 500₽/мес на @glebyshkaone\n"
            "2) Напиши ему свой username\n"
            "3) Он активирует подписку"
        )
        await callback.message.edit_text(text)
        await callback.answer()
        return

    pool = await get_db()
    async with pool.acquire() as conn:
        figure = await conn.fetchrow(
            "select name from figures where id=$1", figure_id
        )
        authors = await conn.fetch(
            """
            select a.id, a.name
            from figure_versions fv
            join authors a on a.id = fv.author_id
            where fv.figure_id=$1
            order by a.name
            """,
            figure_id
        )

    if not authors:
        await callback.answer("Нет описаний от авторов.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for a in authors:
        kb.button(
            text=f"По {a['name']}",
            callback_data=f"figure_ver:{figure_id}:{a['id']}"
        )
    kb.button(text="⬅️ В начало", callback_data="back:root")
    kb.adjust(1)

    await callback.message.edit_text(
        f"*{figure['name']}*\n\nВыбери автора техники:",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


# --------- ВЕРСИЯ ФИГУРЫ ---------

@dp.callback_query(F.data.startswith("figure_ver:"))
async def cb_figure_version(callback: CallbackQuery):
    _, fig_id, author_id = callback.data.split(":")

    pool = await get_db()
    async with pool.acquire() as conn:
        figure = await conn.fetchrow(
            "select name from figures where id=$1", fig_id
        )
        author = await conn.fetchrow(
            "select name from authors where id=$1", author_id
        )
        blocks = await conn.fetch(
            """
            select tb.block, tb.content, tb.position
            from technique_blocks tb
            join figure_versions fv on fv.id = tb.version_id
            where fv.figure_id=$1 and fv.author_id=$2
            order by tb.position
            """,
            fig_id, author_id
        )

    if not blocks:
        await callback.answer("Нет блоков техники.", show_alert=True)
        return

    block_titles = {
        "steps_leader": "🕺 *Шаги партнёра*",
        "steps_follower": "💃 *Шаги партнёрши*",
        "shaping": "🌀 *Шейпинг*",
        "bounce": "🔸 *Баунс*",
        "notes": "✏️ *Примечания*",
        "links": "🔗 *Связки*",
    }

    text_parts = [
        f"*{figure['name']}*",
        f"_по {author['name']}_",
        ""
    ]

    for b in blocks:
        title = block_titles.get(b["block"], "")
        if title:
            text_parts.append(title)
        body = b["content"].get("text", "")
        if body:
            text_parts.append(body)

    final_text = "\n\n".join(text_parts)

    if len(final_text) > 3900:
        final_text = final_text[:3900] + "\n\n…текст сокращён."

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В начало", callback_data="back:root")
    kb.adjust(1)

    await callback.message.edit_text(final_text, reply_markup=kb.as_markup())
    await callback.answer()


# --------- КНОПКА НАЗАД ---------

@dp.callback_query(F.data.startswith("back:root"))
async def cb_back_root(callback: CallbackQuery):
    await cmd_start(callback.message)
    await callback.answer()


# ===============================
#  ЗАПУСК
# ===============================

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не указан")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не указан")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
