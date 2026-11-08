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

os.makedirs("data", exist_ok=True)
DB_PATH = "data/game.db"

router = Router()

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

class AdminStates(StatesGroup):
    waiting_give = State()
    waiting_id = State()
    waiting_amount = State()

def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", " ")

async def check_ban_msg(message: Message) -> bool:
    if await is_banned(message.from_user.id):
        await message.answer("🚫 Вы заблокированы и не можете играть.")
        return True
    return False

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
        "• <b>хило [ставка]</b> — игра Hi-Lo\n"
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
                if all_opened_reveal and all_opened_reveal[idx] == "mine":
                    line.append(InlineKeyboardButton(text="💥", callback_data="none"))
                else:
                    line.append(InlineKeyboardButton(text="💎", callback_data="none"))
            else:
                if all_opened_reveal and all_opened_reveal[idx] == "mine":
                    line.append(InlineKeyboardButton(text="💥", callback_data="none"))
                else:
                    line.append(InlineKeyboardButton(text="🔒", callback_data=f"mine:{user_id}:{idx}"))
        kb.append(line)
    
    if all_opened_reveal is None:
        kb.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data=f"minecash:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def calc_multiplier(opened_count, mines_count):
    if opened_count == 0:
        return 1.0
    prob = 1.0
    for i in range(opened_count):
        prob *= (25 - mines_count - i) / (25 - i)
    return round(0.97 / prob, 2)

@router.message(F.text.lower().startswith(("мины", "mines")))
async def cmd_mines(message: Message):
    if await check_ban_msg(message):
        return
    
    parts = message.text.lower().replace("мины", "").replace("mines", "").strip().split()
    
    if len(parts) == 0:
        if message.from_user.id in active_mines:
            game = active_mines[message.from_user.id]
            opened_count = len(game["opened"])
            mult = calc_multiplier(opened_count, game["mines_count"])
            win = int(game["bet"] * mult)
            await message.answer(
                f"💣 <b>Твоя игра:</b>\n"
                f"Ставка: {fmt_num(game['bet'])} | Мин: {game['mines_count']}\n"
                f"Открыто: {opened_count}/25\n"
                f"Множитель: <b>{mult:.2f}x</b> | Выигрыш: <b>{fmt_num(win)}</b>",
                reply_markup=mines_keyboard(message.from_user.id, game["opened"])
            )
        else:
            await message.answer("❌ У тебя нет активной игры. Напиши: <code>мины 100 2</code>")
        return

    if len(parts) != 2:
        await message.answer("❌ Формат: <code>мины [ставка] [мин]</code>\nПример: <code>мины 100 2</code>")
        return
        
    try:
        bet = int(parts[0])
        mines_count = int(parts[1])
    except ValueError:
        await message.answer("❌ Ставка и количество мин должны быть числами.")
        return

    if mines_count < 1 or mines_count > 24:
        await message.answer("❌ Количество мин должно быть от 1 до 24.")
        return

    user = await get_user(message.from_user.id)
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return
    if bet > user[1]:
        await message.answer("❌ Недостаточно средств.")
        return

    await update_balance(message.from_user.id, -bet)

    positions = list(range(25))
    random.shuffle(positions)
    mines_positions = set(positions[:mines_count])

    active_mines[message.from_user.id] = {
        "bet": bet,
        "mines": mines_positions,
        "opened": set(),
        "mines_count": mines_count,
    }

    await message.answer(
        f"💣 <b>Минное поле</b>\n"
        f"Ставка: {fmt_num(bet)} | Мин: {mines_count}\n"
        f"Открывай клетки. Чем больше открыл — тем больше выигрыш!\n"
        f"Множитель: <b>1.00x</b> | Выигрыш: <b>0</b>",
        reply_markup=mines_keyboard(message.from_user.id, set())
    )

@router.callback_query(F.data.startswith("mine:"))
async def cb_mine_open(callback: CallbackQuery):
    _, user_id_str, idx_str = callback.data.split(":")
    user_id = int(user_id_str)
    idx = int(idx_str)
    
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

    if idx in game["mines"]:
        reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
        for i in game["opened"]:
            reveal[i] = "safe"
        
        del active_mines[user_id]
        await log_game(user_id, "mines", game["bet"], -game["bet"])
        
        await callback.message.edit_text(
            f"💥 <b>БУМ! Ты наткнулся на мину.</b>\n"
            f"Потеряно: {fmt_num(game['bet'])} монет\n\n"
            f"<i>Вот где были мины:</i>",
            reply_markup=mines_keyboard(user_id, game["opened"] | {idx}, reveal)
        )
        await callback.answer("💥 Мина!")
        return

    game["opened"].add(idx)
    opened_count = len(game["opened"])
    mult = calc_multiplier(opened_count, game["mines_count"])
    win = int(game["bet"] * mult)

    await callback.message.edit_text(
        f"💣 <b>Минное поле</b>\n"
        f"Ставка: {fmt_num(game['bet'])} | Мин: {game['mines_count']}\n"
        f"Открыто: {opened_count}/25\n"
        f"Множитель: <b>{mult:.2f}x</b> | Выигрыш: <b>{fmt_num(win)}</b>",
        reply_markup=mines_keyboard(user_id, game["opened"])
    )
    await callback.answer(f"💎 Безопасно! x{mult:.2f}")

@router.callback_query(F.data.startswith("minecash:"))
async def cb_mine_cash(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    
    if user_id != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    game = active_mines.get(user_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    if not game["opened"]:
        await callback.answer("Сначала открой хотя бы одну клетку!", show_alert=True)
        return

    opened_count = len(game["opened"])
    mult = calc_multiplier(opened_count, game["mines_count"])
    win = int(game["bet"] * mult)
    
    await update_balance(user_id, win)
    await add_daily_win(user_id, win - game["bet"])
    await log_game(user_id, "mines", game["bet"], win - game["bet"])

    del active_mines[user_id]

    reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
    
    await callback.message.edit_text(
        f"💰 <b>Выигрыш забран!</b>\n"
        f"Выигрыш: <b>{fmt_num(win)}</b> монет (x{mult:.2f})\n\n"
        f"<i>Вот где были мины:</i>",
        reply_markup=mines_keyboard(user_id, game["opened"], reveal)
    )
    await callback.answer("💰 Забрано!")
    # ==================== ИГРА: HI-LO (ХАЙ-ЛОУ) ====================

active_hilo = {}

SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANKS = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K", 14: "A"
}

def draw_card():
    rank = random.randint(2, 14)
    suit = random.choice(SUITS)
    return rank, suit

def get_card_str(rank, suit):
    return f"[{RANKS[rank]} {suit}]"

def calc_hilo_mult(current_rank, guess):
    if guess == "high":
        higher_ranks = 14 - current_rank
        cards_win = higher_ranks * 4
    elif guess == "low":
        lower_ranks = current_rank - 2
        cards_win = lower_ranks * 4
    else:
        return 1.0

    if cards_win == 0:
        return 1.0

    prob = cards_win / 51.0
    
    if prob == 0:
        return 1.0
    mult = (1.0 / prob) * 0.95
    return round(mult, 2)

def hilo_keyboard(user_id: int, current_card_rank):
    high_mult = calc_hilo_mult(current_card_rank, "high")
    low_mult = calc_hilo_mult(current_card_rank, "low")
    
    row1 = []
    if high_mult > 1.01:
        row1.append(InlineKeyboardButton(text=f"⬆️ Выше ({high_mult}x)", callback_data=f"hilo:{user_id}:high"))
    
    row2 = []
    if low_mult > 1.01:
        row2.append(InlineKeyboardButton(text=f"⬇️ Ниже ({low_mult}x)", callback_data=f"hilo:{user_id}:low"))
    
    kb = []
    if row1: kb.append(row1)
    if row2: kb.append(row2)
    
    kb.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data=f"hilocash:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(F.text.lower().startswith(("хило", "хл", "hilo")))
async def cmd_hilo(message: Message):
    if await check_ban_msg(message):
        return
    
    parts = message.text.lower().replace("хило", "").replace("хл", "").replace("hilo", "").strip().split()
    
    if len(parts) == 0:
        if message.from_user.id in active_hilo:
            game = active_hilo[message.from_user.id]
            card_str = get_card_str(game["current_rank"], game["current_suit"])
            mult = game["multiplier"]
            win = int(game["bet"] * mult)
            await message.answer(
                f"🃏 <b>Твоя игра Hi-Lo:</b>\n"
                f"Текущая карта: <b>{card_str}</b>\n"
                f"Ставка: {fmt_num(game['bet'])} | Множитель: <b>{mult:.2f}x</b>\n"
                f"Потенциальный выигрыш: <b>{fmt_num(win)}</b>",
                reply_markup=hilo_keyboard(message.from_user.id, game["current_rank"])
            )
        else:
            await message.answer("❌ У тебя нет активной игры. Напиши: <code>хило 100</code>")
        return

    try:
        bet = int(parts[0])
    except ValueError:
        await message.answer("❌ Ставка должна быть числом. Пример: <code>хило 100</code>")
        return

    user = await get_user(message.from_user.id)
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return
    if bet > user[1]:
        await message.answer("❌ Недостаточно средств.")
        return

    await update_balance(message.from_user.id, -bet)

    rank, suit = draw_card()
    active_hilo[message.from_user.id] = {
        "bet": bet,
        "current_rank": rank,
        "current_suit": suit,
        "multiplier": 1.0,
    }

# ==================== ИГРА: HI-LO (ХАЙ-ЛОУ) ====================

active_hilo = {}

SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANKS = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K", 14: "A"
}

def draw_card():
    rank = random.randint(2, 14)
    suit = random.choice(SUITS)
    return rank, suit

def get_card_str(rank, suit):
    return f"<b>{RANKS[rank]}</b> {suit}"

def calc_hilo_mult(current_rank, guess):
    if guess == "high":
        higher_ranks = 14 - current_rank
        cards_win = higher_ranks * 4
    elif guess == "low":
        lower_ranks = current_rank - 2
        cards_win = lower_ranks * 4
    else:
        return 1.0

    if cards_win == 0:
        return 1.0

    prob = cards_win / 51.0
    if prob == 0:
        return 1.0
    mult = (1.0 / prob) * 0.95
    return round(mult, 2)

def hilo_keyboard(user_id: int, current_card_rank):
    high_mult = calc_hilo_mult(current_card_rank, "high")
    low_mult = calc_hilo_mult(current_card_rank, "low")
    
    row = []
    if high_mult > 1.01:
        row.append(InlineKeyboardButton(text=f"🟢 ⏸️ Выше x{high_mult}", callback_data=f"hilo:{user_id}:high"))
    if low_mult > 1.01:
        row.append(InlineKeyboardButton(text=f"🔴 ⏸️ Ниже x{low_mult}", callback_data=f"hilo:{user_id}:low"))
    
    kb = []
    if row: kb.append(row)
    
    kb.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data=f"hilocash:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(F.text.lower().regexp(r'^(хило|хл|hilo|хил|hailo|hill)\s+\d+$'))
async def cmd_hilo(message: Message):
    if await check_ban_msg(message):
        return
    
    parts = message.text.lower().replace("хило", "").replace("хл", "").replace("hilo", "").strip().split()
    
    if len(parts) == 0:
        if message.from_user.id in active_hilo:
            game = active_hilo[message.from_user.id]
            card_str = get_card_str(game["current_rank"], game["current_suit"])
            mult = game["multiplier"]
            win = int(game["bet"] * mult)
            text = (
                f"🃏 Выпавшая карта: {card_str}\n"
                f"💵 Ваша ставка: {fmt_num(game['bet'])} монет\n\n"
                f"Сделайте выбор, будет ли следующая карта выше или ниже!\n"
                f"Текущий множитель: <b>{mult:.2f}x</b> | Выигрыш: <b>{fmt_num(win)}</b>"
            )
            await message.answer(text, reply_markup=hilo_keyboard(message.from_user.id, game["current_rank"]))
        else:
            await message.answer("❌ У тебя нет активной игры. Напиши: <code>хило 100</code>")
        return

    try:
        bet = int(parts[0])
    except ValueError:
        await message.answer("❌ Ставка должна быть числом. Пример: <code>хило 100</code>")
        return

    user = await get_user(message.from_user.id)
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return
    if bet > user[1]:
        await message.answer("❌ Недостаточно средств.")
        return

    await update_balance(message.from_user.id, -bet)

    rank, suit = draw_card()
    active_hilo[message.from_user.id] = {
        "bet": bet,
        "current_rank": rank,
        "current_suit": suit,
        "multiplier": 1.0,
    }

    card_str = get_card_str(rank, suit)
    text = (
        f"🃏 Выпавшая карта: {card_str}\n"
        f"💵 Ваша ставка: {fmt_num(bet)} монет\n\n"
        f"Сделайте выбор, будет ли следующая карта выше или ниже!"
    )
    await message.answer(text, reply_markup=hilo_keyboard(message.from_user.id, rank))

@router.callback_query(F.data.startswith("hilo:"))
async def cb_hilo_guess(callback: CallbackQuery):
    _, user_id_str, guess = callback.data.split(":")
    user_id = int(user_id_str)
    
    if user_id != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    game = active_hilo.get(user_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    current_rank = game["current_rank"]
    current_card = get_card_str(current_rank, game["current_suit"])
    
    step_mult = calc_hilo_mult(current_rank, guess)
    
    new_rank, new_suit = draw_card()
    new_card = get_card_str(new_rank, new_suit)
    
    win = False
    if guess == "high" and new_rank > current_rank:
        win = True
    elif guess == "low" and new_rank < current_rank:
        win = True
    
    if win:
        game["multiplier"] = round(game["multiplier"] * step_mult, 2)
        game["current_rank"] = new_rank
        game["current_suit"] = new_suit
        
        mult = game["multiplier"]
        win_amount = int(game["bet"] * mult)
        
        text = (
            f"🎉 <b>Угадал!</b>\n\n"
            f"Было: {current_card} ➡️ Стало: {new_card}\n"
            f"Текущий множитель: <b>{mult:.2f}x</b>\n"
            f"Потенциальный выигрыш: <b>{fmt_num(win_amount)}</b> монет\n\n"
            f"Продолжаем или забираем?"
        )
        await callback.message.edit_text(text, reply_markup=hilo_keyboard(user_id, new_rank))
    else:
        del active_hilo[user_id]
        await log_game(user_id, "hilo", game["bet"], -game["bet"])
        
        text = (
            f"💥 <b>Не угадал!</b>\n\n"
            f"Было: {current_card} ➡️ Стало: {new_card}\n"
            f"К сожалению, ставка {fmt_num(game['bet'])} монет сгорела."
        )
        await callback.message.edit_text(text)
    await callback.answer()

@router.callback_query(F.data.startswith("hilocash:"))
async def cb_hilo_cash(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    
    if user_id != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    game = active_hilo.get(user_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    win = int(game["bet"] * game["multiplier"])
    
    if win > game["bet"]:
        await update_balance(user_id, win)
        await add_daily_win(user_id, win - game["bet"])
        await log_game(user_id, "hilo", game["bet"], win - game["bet"])
    
    del active_hilo[user_id]
    
    await callback.message.edit_text(
        f"💰 <b>Выигрыш забран!</b>\n"
        f"Выигрыш: <b>{fmt_num(win)}</b> монет (x{game['multiplier']:.2f})"
    )
    await callback.answer("💰 Забрано!")
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
        [InlineKeyboardButton(text="💰 Начислить (ответом)", callback_data="admin_give_reply")],
        [InlineKeyboardButton(text="💰 Начислить (по ID)", callback_data="admin_give_id")],
        [InlineKeyboardButton(text="🚫 Бан (ответом)", callback_data="admin_ban_reply")],
        [InlineKeyboardButton(text="✅ Разбан (ответом)", callback_data="admin_unban_reply")],
        [InlineKeyboardButton(text="👑 Начислить себе 5118497284", callback_data="admin_give_self")],
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
    
async def cb_admin_ban_reply(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.message.edit_text(
        "🚫 <b>Бан</b>\n\nОтветь на сообщение игрока: <code>/ban</code>\n"
        "Также: <code>/ban ID</code>"
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

# ==================== ЗАПУСК ====================

async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
