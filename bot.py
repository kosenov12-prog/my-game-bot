import os
import asyncio
import random
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
import aiosqlite

BOT_TOKEN = "9223869999:AAGCCEcj4H7-OWqTFbAffl_PBdHX_fXfLP0"
ADMIN_ID = 5118497284

# Создаем папку data, если ее нет, и кладем базу туда
os.makedirs("data", exist_ok=True)
DB_PATH = "data/game.db"

router = Router()

# ==================== БАЗА ДАННЫХ ====================

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 1000,
                banned INTEGER DEFAULT 0,
                last_bonus TEXT,
                daily_won INTEGER DEFAULT 0,
                daily_date TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game TEXT,
                bet INTEGER,
                win INTEGER,
                date TEXT
            )
        """)
        # Таблица для сохранения активных игр в Мины
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_mines (
                user_id INTEGER PRIMARY KEY,
                bet INTEGER,
                mines_count INTEGER,
                mines_positions TEXT,
                opened TEXT,
                message_id INTEGER
            )
        """)
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO users (user_id, balance, banned, last_bonus, daily_won, daily_date) VALUES (?, 1000, 0, NULL, 0, ?)",
                (user_id, datetime.now().strftime("%Y-%m-%d"))
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
    return row

async def update_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def set_banned(user_id: int, banned: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET banned = ? WHERE user_id = ?", (banned, user_id))
        await db.commit()

async def add_daily_win(user_id: int, amount: int):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT daily_date FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if row[0] != today:
            await db.execute("UPDATE users SET daily_won = ?, daily_date = ? WHERE user_id = ?", (amount, today, user_id))
        else:
            await db.execute("UPDATE users SET daily_won = daily_won + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def log_game(user_id: int, game: str, bet: int, win: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO games (user_id, game, bet, win, date) VALUES (?, ?, ?, ?, ?)",
            (user_id, game, bet, win, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        await db.commit()

async def is_banned(user_id: int):
    if user_id == ADMIN_ID:
        return False
    user = await get_user(user_id)
    return user[2] == 1

# ==================== СОСТОЯНИЯ ====================

class AdminStates(StatesGroup):
    waiting_give = State()
    waiting_id = State()
    waiting_amount = State()

# ==================== ХЕЛПЕРЫ ====================

def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", " ")

async def check_ban_msg(message: Message) -> bool:
    if await is_banned(message.from_user.id):
        await message.answer("🚫 Вы заблокированы и не можете играть.")
        return True
    return False

# ==================== КОМАНДЫ ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await get_user(message.from_user.id)
    text = (
        "🎮 <b>Добро пожаловать в игровой бот!</b>\n\n"
        "📌 Команды:\n"
        "• <b>б</b> — показать баланс\n"
        "• <b>лб</b> — лидерборд за сегодня\n"
        "• <b>бонус</b> — получить бонус (раз в 10 часов)\n"
        "• <b>мины [ставка] [мин]</b> — минное поле (2-24 мины)\n"
        "• <b>мины</b> — продолжить предыдущую игру\n"
        "• <b>кнб [ставка]</b> — камень-ножницы-бумага\n"
        "• <b>дать [сумма]</b> — ответом на сообщение игрока\n"
    )
    if message.from_user.id == ADMIN_ID:
        text += "\n👑 <b>Админ:</b> /admin — админ-панель"
    await message.answer(text)

@router.message(F.text.lower() == "б")
async def cmd_balance(message: Message):
    user = await get_user(message.from_user.id)
    await message.answer(
        f"💰 <b>Ваш баланс:</b> {fmt_num(user[1])} монет\n"
        f"📊 <b>Заработано сегодня:</b> {fmt_num(user[4])} монет"
    )

@router.message(F.text.lower() == "лб")
async def cmd_leaderboard(message: Message):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, daily_won FROM users WHERE daily_date = ? AND daily_won > 0 ORDER BY daily_won DESC LIMIT 10",
            (today,)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("📊 Сегодня ещё никто не выиграл. Будь первым!")
        return

    text = "🏆 <b>Лидерборд за сегодня:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, won) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        try:
            chat = await message.bot.get_chat(uid)
            name = chat.first_name or chat.username or str(uid)
        except Exception:
            name = str(uid)
        text += f"{medal} {name} — {fmt_num(won)} монет\n"
    await message.answer(text)

@router.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    if await check_ban_msg(message):
        return
    user = await get_user(message.from_user.id)
    now = datetime.now()

    if user[3]:
        last = datetime.fromisoformat(user[3])
        diff = now - last
        if diff < timedelta(hours=10):
            left = timedelta(hours=10) - diff
            hours = left.seconds // 3600
            minutes = (left.seconds % 3600) // 60
            await message.answer(f"⏳ Следующий бонус через <b>{hours}ч {minutes}мин</b>")
            return

    amount = random.randint(5000, 100000)
    await update_balance(message.from_user.id, amount)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?",
                         (now.isoformat(), message.from_user.id))
        await db.commit()
    await message.answer(f"🎁 <b>Бонус получен!</b>\n💵 +{fmt_num(amount)} монет")
# ==================== ИГРА: МИНЫ ====================

active_mines = {}

def mines_keyboard(user_id: int, opened: set, all_opened_reveal=None):
    kb = []
    for row in range(5):
        line = []
        for col in range(5):
            idx = row * 5 + col
            if idx in opened:
                line.append(InlineKeyboardButton(text="💎", callback_data="none"))
            else:
                line.append(InlineKeyboardButton(text="⬜", callback_data=f"mine:{user_id}:{idx}"))
        kb.append(line)
    kb.append([InlineKeyboardButton(text="💰 Забрать", callback_data=f"minecash:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(F.text.lower().startswith(("мины", "mines")))
async def cmd_mines(message: Message):
    parts = message.text.lower().replace("мины", "").replace("mines", "").strip().split()
    if len(parts) != 2:
        await message.answer("❌ Пиши: мины 100 2")
        return
    
    try:
        bet = int(parts[0])
        mines_count = int(parts[1])
    except ValueError:
        await message.answer("❌ Ставка и мины должны быть числами.")
        return

    if bet <= 0 or mines_count < 1 or mines_count > 24:
        await message.answer("❌ Ставка больше 0, мин от 1 до 24.")
        return

    user = await get_user(message.from_user.id)
    if bet > user[1]:
        await message.answer("❌ Недостаточно средств.")
        return

    await update_balance(message.from_user.id, -bet)
    active_mines[message.from_user.id] = {"bet": bet, "mines": mines_count, "opened": set()}

    await message.answer(f"💣 Игра началась! Ставка: {bet}, Мин: {mines_count}", reply_markup=mines_keyboard(message.from_user.id, set()))

@router.callback_query(F.data.startswith("mine:"))
async def cb_mine_open(callback: CallbackQuery):
    _, user_id_str, idx_str = callback.data.split(":")
    idx = int(idx_str)
    user_id = int(user_id_str)
    
    if user_id != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    game = active_mines.get(user_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    if idx in game["opened"]:
        await callback.answer("Уже открыто.")
        return

    game["opened"].add(idx)
    await callback.message.edit_text(f"💣 Открыто клеток: {len(game['opened'])}", reply_markup=mines_keyboard(user_id, game["opened"]))
    await callback.answer("Открыто!")

@router.callback_query(F.data.startswith("minecash:"))
async def cb_mine_cash(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    game = active_mines.get(user_id)
    if game:
        del active_mines[user_id]
        await callback.message.edit_text("💰 Вы забрали выигрыш (тест).")
        await callback.answer("Забрано!")

        
    # ==================== ВЫДАЧА МОНЕТ (ДАТЬ) ====================

@router.message(F.text.lower().startswith("дать"))
async def cmd_transfer(message: Message):
    if await check_ban_msg(message):
        return

    parts = message.text.split()
    
    if len(parts) != 2 and len(parts) != 3:
        await message.answer("❌ Формат: ответь на сообщение игрока командой <code>дать [сумма]</code>\nИли: <code>дать [сумма] [ID]</code>")
        return

    try:
        amount = int(parts[1])
    except ValueError:
        await message.answer("❌ Сумма должна быть числом.")
        return

    if amount <= 0:
        await message.answer("❌ Сумма должна быть больше 0.")
        return

    target = None
    if len(parts) == 3:
        try:
            target = int(parts[2])
        except ValueError:
            await message.answer("❌ Некорректный ID получателя.")
            return
    elif message.reply_to_message:
        target = message.reply_to_message.from_user.id

    if not target:
        await message.answer("❌ Ответь на сообщение игрока или укажи его ID.")
        return

    if target == message.from_user.id:
        await message.answer("❌ Нельзя выдать монеты самому себе.")
        return

    sender = await get_user(message.from_user.id)
    await get_user(target)

    if message.from_user.id != ADMIN_ID:
        if amount > 50000:
            await message.answer("❌ Максимальная сумма для выдачи игрокам — 50 000 монет.")
            return
        if sender[1] < amount:
            await message.answer("❌ Недостаточно средств для выдачи.")
            return

    await update_balance(message.from_user.id, -amount)
    await update_balance(target, amount)

    await message.answer(f"💸 Успешно выдано <b>{fmt_num(amount)}</b> монет игроку <code>{target}</code>.")

# ==================== АДМИН ПАНЕЛЬ ====================

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("💰 Начислить (ответом)", callback_data="admin_give_reply")],
        [InlineKeyboardButton("💰 Начислить (по ID)", callback_data="admin_give_id")],
        [InlineKeyboardButton("🚫 Бан (ответом)", callback_data="admin_ban_reply")],
        [InlineKeyboardButton("✅ Разбан (ответом)", callback_data="admin_unban_reply")],
        [InlineKeyboardButton("👑 Начислить себе 5118497284", callback_data="admin_give_self")],
    ])

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещён.")
        return
    await message.answer("👑 <b>Админ-панель</b>\nВыбери действие:", reply_markup=admin_kb())

@router.callback_query(F.data == "admin_give_self")
async def cb_admin_give_self(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_amount)
    await state.update_data(target_id=ADMIN_ID)
    await callback.message.edit_text("💰 Введите сумму для начисления себе (5118497284):")
    await callback.answer()

@router.callback_query(F.data == "admin_give_reply")
async def cb_admin_give_reply(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_give)
    await callback.message.edit_text(
        "💰 <b>Начисление (ответом)</b>\n\n"
        "Ответь командой на сообщение игрока: <code>/give 500</code>\n"
        "Где 500 — сумма."
    )
    await callback.answer()

@router.callback_query(F.data == "admin_give_id")
async def cb_admin_give_id(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_id)
    await callback.message.edit_text("💰 Введите ID игрока:")
    await callback.answer()

@router.message(AdminStates.waiting_id)
async def admin_waiting_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Некорректный ID.")
        return
    await state.update_data(target_id=target)
    await state.set_state(AdminStates.waiting_amount)
    await message.answer(f"💰 Введите сумму для начисления игроку <code>{target}</code>:")

@router.message(AdminStates.waiting_amount)
async def admin_waiting_amount(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Некорректная сумма.")
        return
    data = await state.get_data()
    target = data.get("target_id")
    await state.clear()
    await get_user(target)
    await update_balance(target, amount)
    await message.answer(f"✅ Начислено {fmt_num(amount)} монет игроку <code>{target}</code>.")

@router.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещён.")
        return
    if not message.reply_to_message:
        await message.answer("❌ Ответь на сообщение игрока командой /give СУММА")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Формат: /give СУММА (ответом на сообщение)")
        return
    try:
        amount = int(parts[1])
    except ValueError:
        await message.answer("❌ Сумма должна быть числом.")
        return
    target = message.reply_to_message.from_user.id
    await get_user(target)
    await update_balance(target, amount)
    await message.answer(f"✅ Начислено {fmt_num(amount)} монет игроку {target}.")

@router.callback_query(F.data == "admin_ban_reply")
async def cb_admin_ban_reply(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.message.edit_text(
        "🚫 <b>Бан</b>\n\nОтветь на сообщение игрока: <code>/ban</code>\n"
        "Также: <code>/ban ID</code>"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_unban_reply")
async def cb_admin_unban_reply(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.message.edit_text(
        "✅ <b>Разбан</b>\n\nОтветь на сообщение игрока: <code>/unban</code>\n"
        "Также: <code>/unban ID</code>"
    )
    await callback.answer()

@router.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    target = None
    if message.reply_to_message:
        target = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) == 2:
            try:
                target = int(parts[1])
            except ValueError:
                pass
    if not target:
        await message.answer("❌ Ответь на сообщение игрока или укажи ID: /ban ID")
        return
    await get_user(target)
    await set_banned(target, 1)
    await message.answer(f"🚫 Игрок <code>{target}</code> забанен.")

@router.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    target = None
    if message.reply_to_message:
        target = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) == 2:
            try:
                target = int(parts[1])
            except ValueError:
                pass
    if not target:
        await message.answer("❌ Ответь на сообщение игрока или укажи ID: /unban ID")
        return
    await get_user(target)
    await set_banned(target, 0)
    await message.answer(f"✅ Игрок <code>{target}</code> разбанен.")

async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
