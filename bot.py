import os
import asyncio
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
import asyncpg

BOT_TOKEN = "9223869999:AAGCCEcj4H7-OWqTFbAffl_PBdHX_fXfLP0"
ADMIN_ID = 5118497284
DATABASE_URL = os.environ.get("DATABASE_URL") 

if not DATABASE_URL:
    print("!!! КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения DATABASE_URL не установлена. !!!")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
db_pool = None

async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    balance INTEGER DEFAULT 1000,
                    banned INTEGER DEFAULT 0,
                    last_bonus TEXT,
                    daily_won INTEGER DEFAULT 0,
                    daily_date TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    game TEXT,
                    bet INTEGER,
                    win INTEGER,
                    date TEXT
                )
            """)
    except Exception as e:
        print(f"[DB] Ошибка инициализации: {e} !!!")

async def get_user(user_id: int):
    if not db_pool: return None 
    async with db_pool.acquire() as db:
        row = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not row:
            today = datetime.now().strftime("%Y-%m-%d")
            try:
                await db.execute(
                    "INSERT INTO users (user_id, balance, banned, last_bonus, daily_won, daily_date) VALUES ($1, 1000, 0, NULL, 0, $2)",
                    user_id, today
                )
                row = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            except Exception as e:
                return None
    return row

async def update_balance(user_id: int, amount: int):
    if not db_pool: return
    async with db_pool.acquire() as db:
        await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, user_id)

async def set_banned(user_id: int, banned: int):
    if not db_pool: return
    async with db_pool.acquire() as db:
        await db.execute("UPDATE users SET banned = $1 WHERE user_id = $2", banned, user_id)
        
async def add_daily_win(user_id: int, amount: int):
    if not db_pool: return
    today = datetime.now().strftime("%Y-%m-%d")
    async with db_pool.acquire() as db:
        row = await db.fetchrow("SELECT daily_date, daily_won FROM users WHERE user_id = $1", user_id)
        if row is None: return 
        
        if row['daily_date'] != today:
            new_win = max(0, amount) 
            await db.execute("UPDATE users SET daily_won = $1, daily_date = $2 WHERE user_id = $3", new_win, today, user_id)
        else:
            new_win = row['daily_won'] + amount
            if new_win < 0: new_win = 0 
            await db.execute("UPDATE users SET daily_won = $1 WHERE user_id = $2", new_win, user_id)

async def log_game(user_id: int, game: str, bet: int, profit: int):
    if not db_pool: return
    async with db_pool.acquire() as db:
        await db.execute(
            "INSERT INTO games (user_id, game, bet, win, date) VALUES ($1, $2, $3, $4, $5)",
            user_id, game, bet, profit, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

def fmt_num(n: int) -> str:
    if n is None: return "N/A"
    return f"{n:,}".replace(",", " ")

async def check_ban_msg(message: Message) -> bool:
    if message.from_user.id == ADMIN_ID: return False
    user = await get_user(message.from_user.id)
    if user is None:
        await message.answer("❌ Произошла ошибка при проверке статуса.")
        return True 
    if user['banned'] == 1:
        await message.answer("🚫 Вы заблокированы и не можете играть.")
        return True
    return False

class AdminStates(StatesGroup):
    waiting_give_amount = State() 
    waiting_user_id_for_action = State() 
@router.message(Command("start"))
async def cmd_start(message: Message):
    await get_user(message.from_user.id) 
    text = (
        "🎮 <b>Добро пожаловать в игровой бот!</b>\n\n"
        "📌 Команды:\n"
        "• <b>б</b> — показать баланс\n"
        "• <b>лб</b> — лидерборд за сегодня\n"
        "• <b>бонус</b> — получить бонус (раз в 10 часов)\n"
        "• <b>мины [ставка] [мин]</b> — минное поле\n"
        "• <b>хило [ставка]</b> — игра Hi-Lo\n"
    )
    if message.from_user.id == ADMIN_ID:
        text += "\n👑 <b>Админ:</b> /admin — админ-панель"
    await message.answer(text)

@router.message(F.text.lower() == "б")
async def cmd_balance(message: Message):
    user = await get_user(message.from_user.id)
    if user is None: return
    await message.answer(
        f"💰 <b>Ваш баланс:</b> {fmt_num(user['balance'])} монет\n"
        f"📊 <b>Заработано сегодня:</b> {fmt_num(user['daily_won'])} монет"
    )

@router.message(F.text.lower() == "лб")
async def cmd_leaderboard(message: Message):
    today = datetime.now().strftime("%Y-%m-%d")
    if not db_pool: return
    async with db_pool.acquire() as db:
        rows = await db.fetch(
            "SELECT user_id, daily_won FROM users WHERE daily_date = $1 AND daily_won > 0 ORDER BY daily_won DESC LIMIT 10",
            today
        )
    if not rows:
        await message.answer("📊 Сегодня ещё никто не выиграл.")
        return
    text = "🏆 <b>Лидерборд за сегодня:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        uid = row['user_id']
        won = row['daily_won']
        medal = medals[i] if i < 3 else f"{i+1}."
        try:
            chat = await message.bot.get_chat(uid)
            name = chat.first_name
        except Exception:
            name = f"Игрок {uid}" 
        text += f"{medal} {name} — {fmt_num(won)} монет\n"
    await message.answer(text)

@router.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    if await check_ban_msg(message): return
    user = await get_user(message.from_user.id)
    if user is None: return
    now = datetime.now()
    bonus_cooldown = timedelta(hours=10)
    if user['last_bonus']:
        try:
            last = datetime.fromisoformat(user['last_bonus'])
            diff = now - last
            if diff < bonus_cooldown:
                left = bonus_cooldown - diff
                hours = left.seconds // 3600
                minutes = (left.seconds % 3600) // 60
                await message.answer(f"⏳ Следующий бонус через <b>{hours}ч {minutes}мин</b>")
                return
        except ValueError: pass
    amount = random.randint(5000, 100000)
    await update_balance(message.from_user.id, amount)
    async with db_pool.acquire() as db:
        await db.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2", now.isoformat(), message.from_user.id)
    await message.answer(f"🎁 <b>Бонус получен!</b>\n💵 +{fmt_num(amount)} монет")

active_mines = {}

def mines_keyboard(user_id: int, opened: set, all_opened_reveal=None):
    kb = []
    for row in range(5):
        line = []
        for col in range(5):
            idx = row * 5 + col
            if idx in opened:
                if all_opened_reveal and all_opened_reveal.get(idx) == "mine":
                    line.append(InlineKeyboardButton(text="💥", callback_data="none"))
                else:
                    line.append(InlineKeyboardButton(text="💎", callback_data="none"))
            else:
                if all_opened_reveal and all_opened_reveal.get(idx) == "mine":
                    line.append(InlineKeyboardButton(text="💥", callback_data="none"))
                else:
                    line.append(InlineKeyboardButton(text="🔒", callback_data=f"mine:{user_id}:{idx}"))
        kb.append(line)
    if all_opened_reveal is None:
        kb.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data=f"minecash:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def calc_multiplier(opened_count, mines_count):
    if opened_count == 0: return 1.0
    prob_survival = 1.0
    for i in range(opened_count):
        prob_survival *= (25 - mines_count - i) / (25 - i)
    return round(0.97 / prob_survival, 2) if prob_survival > 0 else 999.99

@router.message(F.text.lower().regexp(r'^(мины|mines)\s+(\d+)\s+(\d+)$'))
async def cmd_mines(message: Message):
    if await check_ban_msg(message): return
    match = F.text.lower().regexp(r'^(мины|mines)\s+(\d+)\s+(\d+)$').match(message.text)
    bet_str, mines_count_str = match.group(2), match.group(3)
    try:
        bet = int(bet_str)
        mines_count = int(mines_count_str)
    except ValueError: return
    if not (1 <= mines_count <= 24): return
    if bet <= 0: return
    user = await get_user(message.from_user.id)
    if user is None or bet > user['balance']:
        await message.answer("❌ Недостаточно средств.")
        return
    await update_balance(message.from_user.id, -bet)
    positions = list(range(25))
    random.shuffle(positions)
    mines_positions = set(positions[:mines_count])
    active_mines[message.from_user.id] = {
        "bet": bet, "mines": mines_positions, "opened": set(), "mines_count": mines_count,
    }
    await message.answer(
        f"💣 <b>Минное поле</b>\nСтавка: {fmt_num(bet)} | Мин: {mines_count}\nМножитель: <b>1.00x</b> | Выигрыш: <b>0</b>",
        reply_markup=mines_keyboard(message.from_user.id, set())
    )
    @router.callback_query(F.data.startswith("mine:"))
    async def cb_mine_open(callback: CallbackQuery):
    try:
        _, user_id_str, idx_str = callback.data.split(":")
        user_id = int(user_id_str)
        idx = int(idx_str)
    except: return
    if user_id != callback.from_user.id: return
    game = active_mines.get(user_id)
    if not game: return
    if idx in game["opened"]: return
    if idx in game["mines"]:
        reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
        for i in game["opened"]: reveal[i] = "safe"
        await log_game(user_id, "mines", game["bet"], -game["bet"])
        del active_mines[user_id]
        await callback.message.edit_text(
            f"💥 <b>БУМ! Ты наткнулся на мину.</b>\nПотеряно: {fmt_num(game['bet'])} монет",
            reply_markup=mines_keyboard(user_id, game["opened"] | {idx}, reveal)
        )
        return
    game["opened"].add(idx)
    opened_count = len(game["opened"])
    mult = calc_multiplier(opened_count, game["mines_count"])
    win = int(game["bet"] * mult)
    await callback.message.edit_text(
        f"💣 <b>Минное поле</b>\nСтавка: {fmt_num(game['bet'])}\nОткрыто: {opened_count}/25\nМножитель: <b>{mult:.2f}x</b> | Выигрыш: <b>{fmt_num(win)}</b>",
        reply_markup=mines_keyboard(user_id, game["opened"])
    )

@router.callback_query(F.data.startswith("minecash:"))
async def cb_mine_cash(callback: CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
    except: return
    if user_id != callback.from_user.id: return
    game = active_mines.get(user_id)
    if not game or not game["opened"]: return
    opened_count = len(game["opened"])
    mult = calc_multiplier(opened_count, game["mines_count"])
    win = int(game["bet"] * mult)
    profit = win - game["bet"]
    await update_balance(user_id, win)
    await add_daily_win(user_id, profit)
    await log_game(user_id, "mines", game["bet"], profit)
    del active_mines[user_id]
    reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
    for i in game["opened"]: reveal[i] = "safe"
    await callback.message.edit_text(
        f"💰 <b>Выигрыш забран!</b>\nВыигрыш: <b>{fmt_num(win)}</b> монет",
        reply_markup=mines_keyboard(user_id, game["opened"], reveal)
    )

active_hilo = {}
SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANKS = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}

def draw_card():
    return random.randint(2, 14), random.choice(SUITS)

def get_card_str(rank, suit):
    return f"[{RANKS[rank]} {suit}]"

def calc_hilo_mult(current_rank, guess):
    if guess == "high":
        prob = ((14 - current_rank) * 4 + 3) / 51.0
    elif guess == "low":
        prob = ((current_rank - 2) * 4 + 3) / 51.0
    else: prob = 0
    return round((1.0 / prob) * 0.95, 2) if prob > 0 else 1.0

def hilo_keyboard(user_id: int, current_card_rank, current_mult=1.0):
    high_mult = calc_hilo_mult(current_card_rank, "high")
    low_mult = calc_hilo_mult(current_card_rank, "low")
    row = [
        InlineKeyboardButton(text=f"⬆️ Выше или = ({high_mult}x)", callback_data=f"hilo:{user_id}:high"),
        InlineKeyboardButton(text=f"⬇️ Ниже или = ({low_mult}x)", callback_data=f"hilo:{user_id}:low")
    ]
    kb = [row]
    if current_mult > 1.0:
        kb.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data=f"hilocash:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(F.text.lower().regexp(r'^(хило|хл|hilo)\s+(\d+)$'))
async def cmd_hilo(message: Message):
    if await check_ban_msg(message): return
    match = F.text.lower().regexp(r'^(хило|хл|hilo)\s+(\d+)$').match(message.text)
    try: bet = int(match.group(2))
    except: return
    user = await get_user(message.from_user.id)
    if user is None or bet <= 0 or bet > user['balance']: return
    await update_balance(message.from_user.id, -bet)
    rank, suit = draw_card()
    active_hilo[message.from_user.id] = {"bet": bet, "current_rank": rank, "current_suit": suit, "multiplier": 1.0}
    await message.answer(
        f"🃏 <b>Игра Hi-Lo началась!</b>\nТекущая карта: <b>{get_card_str(rank, suit)}</b>\nСтавка: {fmt_num(bet)}",
        reply_markup=hilo_keyboard(message.from_user.id, rank, 1.0)
    )
    @router.callback_query(F.data.startswith("hilo:"))
async def cb_hilo_guess(callback: CallbackQuery):
    try:
        _, user_id_str, guess = callback.data.split(":")
        user_id = int(user_id_str)
    except: return
    if user_id != callback.from_user.id: return
    game = active_hilo.get(user_id)
    if not game: return
    current_rank = game["current_rank"]
    current_card = get_card_str(current_rank, game["current_suit"])
    step_mult = calc_hilo_mult(current_rank, guess)
    new_rank, new_suit = draw_card()
    new_card = get_card_str(new_rank, new_suit)
    win = False
    if guess == "high" and new_rank >= current_rank: win = True
    elif guess == "low" and new_rank <= current_rank: win = True
    if win:
        if new_rank == current_rank:
            game["multiplier"] = round(game["multiplier"] * (step_mult * 1.5), 2)
            msg_prefix = "😮 <b>Выпало то же число! Но ты в игре.</b>\n\n"
        else:
            game["multiplier"] = round(game["multiplier"] * step_mult, 2)
            msg_prefix = "🎉 <b>Угадал!</b>\n\n"
        game["current_rank"] = new_rank
        game["current_suit"] = new_suit
        mult = game["multiplier"]
        win_amount = int(game["bet"] * mult)
        await callback.message.edit_text(
            f"{msg_prefix}Было: {current_card} ➡️ Стало: {new_card}\n"
            f"Текущий множитель: <b>{mult:.2f}x</b>\nПотенциальный выигрыш: <b>{fmt_num(win_amount)}</b>",
            reply_markup=hilo_keyboard(user_id, new_rank, game["multiplier"])
        )
    else:
        await log_game(user_id, "hilo", game["bet"], -game["bet"])
        del active_hilo[user_id]
        await callback.message.edit_text(
            f"💥 <b>Не угадал!</b>\nБыло: {current_card} ➡️ Стало: {new_card}\nСтавка {fmt_num(game['bet'])} монет сгорела."
        )

@router.callback_query(F.data.startswith("hilocash:"))
async def cb_hilo_cash(callback: CallbackQuery):
    try: user_id = int(callback.data.split(":")[1])
    except: return
    if user_id != callback.from_user.id: return
    game = active_hilo.get(user_id)
    if not game: return
    win = int(game["bet"] * game["multiplier"])
    if win > game["bet"]:
        await update_balance(user_id, win)
        await add_daily_win(user_id, win - game["bet"])
        await log_game(user_id, "hilo", game["bet"], win)
    del active_hilo[user_id]
    await callback.message.edit_text(f"💰 <b>Выигрыш забран!</b>\nВыигрыш: <b>{fmt_num(win)}</b> монет")

@router.message(F.text.lower().startswith("дать"))
async def cmd_transfer(message: Message):
    if await check_ban_msg(message): return
    parts = message.text.split()
    if len(parts) not in [2, 3]: return
    try: amount = int(parts[1])
    except: return
    if amount <= 0: return
    target = int(parts[2]) if len(parts) == 3 else (message.reply_to_message.from_user.id if message.reply_to_message else None)
    if not target or target == message.from_user.id: return
    sender = await get_user(message.from_user.id)
    await get_user(target)
    if message.from_user.id != ADMIN_ID:
        if amount > 50000 or sender['balance'] < amount: return
    await update_balance(message.from_user.id, -amount)
    await update_balance(target, amount)
    await message.answer(f"💸 Успешно выдано <b>{fmt_num(amount)}</b> монет игроку <code>{target}</code>.")

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Начислить (ответом)", callback_data="admin_give_reply")],
        [InlineKeyboardButton(text="💰 Начислить (по ID)", callback_data="admin_give_id")],
        [InlineKeyboardButton(text="🚫 Бан (ответом)", callback_data="admin_ban_reply")],
        [InlineKeyboardButton(text="👑 Начислить себе 5118497284", callback_data="admin_give_self")],
    ])

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_kb())

@router.callback_query(F.data == "admin_give_self")
async def cb_admin_give_self(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.waiting_give_amount)
    await state.update_data(target_id=ADMIN_ID)
    await callback.message.edit_text("💰 Введите сумму для начисления себе:")

@router.callback_query(F.data == "admin_give_id")
async def cb_admin_give_id(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.waiting_user_id_for_action)
    await callback.message.edit_text("💰 Введите ID игрока:")

@router.message(AdminStates.waiting_user_id_for_action)
async def admin_waiting_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try: target = int(message.text.strip())
    except: return
    await state.update_data(target_id=target)
    await state.set_state(AdminStates.waiting_give_amount)
    await message.answer(f"💰 Введите сумму для игрока <code>{target}</code>:")

@router.message(AdminStates.waiting_give_amount)
async def admin_waiting_amount(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try: amount = int(message.text.strip())
    except: return
    data = await state.get_data()
    target = data.get("target_id")
    await state.clear()
    await update_balance(target, amount)
    await message.answer(f"✅ Начислено {fmt_num(amount)} монет игроку <code>{target}</code>.")

@router.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID or not message.reply_to_message: return
    parts = message.text.split()
    if len(parts) != 2: return
    try: amount = int(parts[1])
    except: return
    target = message.reply_to_message.from_user.id
    await update_balance(target, amount)
    await message.answer(f"✅ Начислено {fmt_num(amount)} монет игроку {target}.")

@router.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != ADMIN_ID: return
    target = message.reply_to_message.from_user.id if message.reply_to_message else (int(message.text.split()[1]) if len(message.text.split()) == 2 else None)
    if target:
        await set_banned(target, 1)
        await message.answer(f"🚫 Игрок <code>{target}</code> забанен.")

@router.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != ADMIN_ID: return
    target = message.reply_to_message.from_user.id if message.reply_to_message else (int(message.text.split()[1]) if len(message.text.split()) == 2 else None)
    if target:
        await set_banned(target, 0)
        await message.answer(f"✅ Игрок <code>{target}</code> разбанен.")

async def main():
    await init_db()
    await bot.set_my_commands([BotCommand(command="start", description="Запустить бота"), BotCommand(command="admin", description="Админ-панель")])
    dp.include_router(router)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
