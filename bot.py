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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5118497284
DB_PATH = "game.db"

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


async def set_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
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

class BetStates(StatesGroup):
    waiting_rps_bet = State()

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
        "• <b>кнб [ставка]</b> — камень-ножницы-бумага\n"
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

# game_id -> dict с данными игры
active_mines = {}

def mines_keyboard(game_id: str, opened: set, all_opened_reveal=None):
    kb = []
    for row in range(5):
        line = []
        for col in range(5):
            idx = row * 5 + col
            if idx in opened:
                if all_opened_reveal and all_opened_reveal[idx] == "mine":
                    line.append(InlineKeyboardButton("💥", callback_data="none"))
                else:
                    line.append(InlineKeyboardButton("💎", callback_data="none"))
            else:
                line.append(InlineKeyboardButton("⬜", callback_data=f"mine:{game_id}:{idx}"))
        kb.append(line)
    if all_opened_reveal is None:
        kb.append([InlineKeyboardButton("💰 Забрать выигрыш", callback_data=f"minecash:{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(F.text.lower().startswith("мины"))
async def cmd_mines(message: Message):
    if await check_ban_msg(message):
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("❌ Формат: <code>мины [ставка] [мин]</code>\nПример: <code>мины 100 2</code>")
        return
    try:
        bet = int(parts[1])
        mines_count = int(parts[2])
    except ValueError:
        await message.answer("❌ Ставка и количество мин должны быть числами.")
        return

    if mines_count < 2 or mines_count > 24:
        await message.answer("❌ Количество мин должно быть от 2 до 24.")
        return

    user = await get_user(message.from_user.id)
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return
    if bet > user[1]:
        await message.answer("❌ Недостаточно средств.")
        return

    # Списание ставки
    await update_balance(message.from_user.id, -bet)

    # Генерация поля
    positions = list(range(25))
    random.shuffle(positions)
    mines_positions = set(positions[:mines_count])

    game_id = f"{message.from_user.id}_{int(datetime.now().timestamp() * 1000)}"
    active_mines[game_id] = {
        "user_id": message.from_user.id,
        "bet": bet,
        "mines": mines_positions,
        "opened": set(),
        "mines_count": mines_count,
        "multiplier": 1.0,
    }

    # Расчёт множителя
    def calc_multiplier(opened_count, mines_count):
        # множитель = (25 / (25 - mines))^opened, с небольшим house edge
        if opened_count == 0:
            return 1.0
        m = 1.0
        for i in range(opened_count):
            m *= (25 - i) / (25 - mines_count - i)
        return m * 0.95  # house edge 5%

    active_mines[game_id]["calc"] = calc_multiplier

    await message.answer(
        f"💣 <b>Минное поле</b>\n"
        f"Ставка: {fmt_num(bet)} | Мин: {mines_count}\n"
        f"Открывай клетки. Чем больше открыл — тем больше выигрыш!\n"
        f"Множитель: <b>1.00x</b> | Выигрыш: <b>0</b>",
        reply_markup=mines_keyboard(game_id, set())
    )


@router.callback_query(F.data.startswith("mine:"))
async def cb_mine_open(callback: CallbackQuery):
    _, game_id, idx_str = callback.data.split(":")
    idx = int(idx_str)
    game = active_mines.get(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if game["user_id"] != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return
    if idx in game["opened"]:
        await callback.answer("Уже открыто.")
        return

    if idx in game["mines"]:
        # Проигрыш
        reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
        for i in game["opened"]:
            reveal[i] = "safe"
        del active_mines[game_id]
        await log_game(callback.from_user.id, "mines", game["bet"], -game["bet"])
        await callback.message.edit_text(
            f"💥 <b>БУМ! Ты наткнулся на мину.</b>\n"
            f"Потеряно: {fmt_num(game['bet'])} монет",
            reply_markup=mines_keyboard(game_id, game["opened"] | {idx}, reveal)
        )
        await callback.answer("💥 Мина!")
        return

    game["opened"].add(idx)
    opened_count = len(game["opened"])
    mult = game["calc"](opened_count, game["mines_count"])
    game["multiplier"] = mult
    win = int(game["bet"] * mult)

    # Если открыты все безопасные клетки — авто-победа
    safe_total = 25 - game["mines_count"]
    if opened_count >= safe_total:
        await update_balance(callback.from_user.id, win)
        await add_daily_win(callback.from_user.id, win - game["bet"])
        await log_game(callback.from_user.id, "mines", game["bet"], win - game["bet"])
        reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
        del active_mines[game_id]
        await callback.message.edit_text(
            f"🎉 <b>ПОБЕДА! Все клетки открыты!</b>\n"
            f"Выигрыш: <b>{fmt_num(win)}</b> монет (x{mult:.2f})",
            reply_markup=mines_keyboard(game_id, game["opened"], reveal)
        )
        await callback.answer("🎉 Победа!")
        return

    await callback.message.edit_text(
        f"💣 <b>Минное поле</b>\n"
        f"Ставка: {fmt_num(game['bet'])} | Мин: {game['mines_count']}\n"
        f"Открыто: {opened_count}/{safe_total}\n"
        f"Множитель: <b>{mult:.2f}x</b> | Выигрыш: <b>{fmt_num(win)}</b>",
        reply_markup=mines_keyboard(game_id, game["opened"])
    )
    await callback.answer(f"💎 Безопасно! x{mult:.2f}")


@router.callback_query(F.data.startswith("minecash:"))
async def cb_mine_cash(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    game = active_mines.get(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if game["user_id"] != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return
    if not game["opened"]:
        await callback.answer("Сначала открой хотя бы одну клетку!", show_alert=True)
        return

    win = int(game["bet"] * game["multiplier"])
    await update_balance(callback.from_user.id, win)
    await add_daily_win(callback.from_user.id, win - game["bet"])
    await log_game(callback.from_user.id, "mines", game["bet"], win - game["bet"])

    reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
    del active_mines[game_id]

    await callback.message.edit_text(
        f"💰 <b>Выигрыш забран!</b>\n"
        f"Выигрыш: <b>{fmt_num(win)}</b> монет (x{game['multiplier']:.2f})",
        reply_markup=mines_keyboard(game_id, game["opened"], reveal)
    )
    await callback.answer("💰 Забрано!")


# ==================== ИГРА: КНБ ====================

@router.message(F.text.lower().startswith("кнб"))
async def cmd_rps(message: Message):
    if await check_ban_msg(message):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Формат: <code>кнб [ставка]</code>\nПример: <code>кнб 100</code>")
        return
    try:
        bet = int(parts[1])
    except ValueError:
        await message.answer("❌ Ставка должна быть числом.")
        return

    user = await get_user(message.from_user.id)
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return
    if bet > user[1]:
        await message.answer("❌ Недостаточно средств.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton("🪨 Камень", callback_data=f"rps:{bet}:rock"),
        InlineKeyboardButton("✂️ Ножницы", callback_data=f"rps:{bet}:scissors"),
        InlineKeyboardButton("📄 Бумага", callback_data=f"rps:{bet}:paper"),
    ]])
    await message.answer(f"🎮 Выбери свой ход (ставка {fmt_num(bet)}):", reply_markup=kb)


@router.callback_query(F.data.startswith("rps:"))
async def cb_rps(callback: CallbackQuery):
    _, bet_str, player_choice = callback.data.split(":")
    bet = int(bet_str)

    user = await get_user(callback.from_user.id)
    if user[1] < bet:
        await callback.answer("❌ Недостаточно средств.", show_alert=True)
        return

    await update_balance(callback.from_user.id, -bet)

    bot_choice = random.choice(["rock", "scissors", "paper"])
    emoji = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
    names = {"rock": "Камень", "scissors": "Ножницы", "paper": "Бумага"}

    if player_choice == bot_choice:
        result = "draw"
        delta = 0
    elif (player_choice == "rock" and bot_choice == "scissors") or \
         (player_choice == "scissors" and bot_choice == "paper") or \
         (player_choice == "paper" and bot_choice == "rock"):
        result = "win"
        delta = bet
    else:
        result = "lose"
        delta = -bet

    if result == "win":
        await update_balance(callback.from_user.id, bet * 2)
        await add_daily_win(callback.from_user.id, bet)
        await log_game(callback.from_user.id, "rps", bet, bet)
        text_result = f"🎉 <b>Победа!</b> +{fmt_num(bet)} монет"
    elif result == "lose":
        await log_game(callback.from_user.id, "rps", bet, -bet)
        text_result = f"😢 <b>Проигрыш.</b> -{fmt_num(bet)} монет"
    else:
        await update_balance(callback.from_user.id, bet)  # возврат ставки
        await log_game(callback.from_user.id, "rps", bet, 0)
        text_result = "🤝 <b>Ничья.</b> Ставка возвращена."

    await callback.message.edit_text(
        f"{emoji[player_choice]} Ты: <b>{names[player_choice]}</b>\n"
        f"{emoji[bot_choice]} Бот: <b>{names[bot_choice]}</b>\n\n"
        f"{text_result}"
    )
    await callback.answer()


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
    awa
