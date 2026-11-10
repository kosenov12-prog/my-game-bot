import os
import asyncio
import random
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
import asyncpg

# --- Конфигурация ---
BOT_TOKEN = "9223869999:AAGCCEcj4H7-OWqTFbAffl_PBdHX_fXfLP0" # Замените на ваш токен
ADMIN_ID = 5118497284 # Замените на ваш ID администратора

# Убедитесь, что DATABASE_URL установлен в переменных окружения
# Пример: export DATABASE_URL="postgresql://user:password@host:port/database"
DATABASE_URL = os.environ.get("DATABASE_URL") 

if not DATABASE_URL:
    print("!!! ОШИБКА: Переменная окружения DATABASE_URL не установлена. !!!")
    print("!!! Пожалуйста, установите ее, например: export DATABASE_URL=\"postgresql://user:password@host:port/database\" !!!")
    # В реальном приложении лучше прервать выполнение, если БД недоступна
    # exit() 

router = Router()
db_pool = None # Глобальный пул соединений с БД

# --- Инициализация базы данных ---
async def init_db():
    global db_pool
    if not DATABASE_URL:
        print("!!! ОШИБКА: Невозможно инициализировать БД, DATABASE_URL не задан. !!!")
        return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as db:
            # Таблица пользователей
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
            # Таблица игр (для логов)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    game TEXT,
                    bet INTEGER,
                    win INTEGER, -- win здесь означает чистый выигрыш (win - bet)
                    date TEXT
                )
            """)
        print("База данных инициализирована успешно.")
    except Exception as e:
        print(f"!!! ОШИБКА инициализации базы данных: {e} !!!")
        # В реальном приложении здесь лучше выбросить исключение или завершить работу
        db_pool = None # Сбрасываем пул, если инициализация не удалась

# --- Функции для работы с БД ---
async def get_user(user_id: int):
    if not db_pool: 
        print(f"!!! ОШИБКА: Нет соединения с БД при попытке получить пользователя {user_id}. !!!")
        return None 
    async with db_pool.acquire() as db:
        row = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not row:
            # Если пользователя нет, создаем его
            today = datetime.now().strftime("%Y-%m-%d")
            try:
                await db.execute(
                    "INSERT INTO users (user_id, balance, banned, last_bonus, daily_won, daily_date) VALUES ($1, 1000, 0, NULL, 0, $2)",
                    user_id, today
                )
                row = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            except Exception as e:
                print(f"!!! ОШИБКА при создании пользователя {user_id}: {e} !!!")
                return None
    return row

async def update_balance(user_id: int, amount: int):
    if not db_pool: return
    try:
        async with db_pool.acquire() as db:
            await db.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, user_id)
    except Exception as e:
        print(f"!!! ОШИБКА обновления баланса для {user_id}: {e} !!!")

async def set_banned(user_id: int, banned: int):
    if not db_pool: return
    try:
        async with db_pool.acquire() as db:
            await db.execute("UPDATE users SET banned = $1 WHERE user_id = $2", banned, user_id)
    except Exception as e:
        print(f"!!! ОШИБКА установки бана для {user_id}: {e} !!!")
        
async def add_daily_win(user_id: int, amount: int):
    if not db_pool: return
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        async with db_pool.acquire() as db:
            row = await db.fetchrow("SELECT daily_date, daily_won FROM users WHERE user_id = $1", user_id)
            if row is None: # Пользователь не найден (маловероятно, но на всякий случай)
                return 
            
            if row['daily_date'] != today:
                new_win = max(0, amount) # Начинаем с нуля, если новый день
                await db.execute("UPDATE users SET daily_won = $1, daily_date = $2 WHERE user_id = $3", new_win, today, user_id)
            else:
                new_win = row['daily_won'] + amount
                if new_win < 0: new_win = 0 # Не допускаем отрицательного значения
                await db.execute("UPDATE users SET daily_won = $1 WHERE user_id = $2", new_win, user_id)
    except Exception as e:
        print(f"!!! ОШИБКА добавления ежедневного выигрыша для {user_id}: {e} !!!")

# --- Логирование игр (ТОЛЬКО для asyncpg) ---
async def log_game(user_id: int, game: str, bet: int, profit: int): # profit = win - bet
    if not db_pool: return
    try:
        async with db_pool.acquire() as db:
            await db.execute(
                "INSERT INTO games (user_id, game, bet, win, date) VALUES ($1, $2, $3, $4, $5)",
                user_id, game, bet, profit, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
    except Exception as e:
        print(f"!!! ОШИБКА логирования игры {game} для {user_id}: {e} !!!")

# --- Вспомогательные функции ---
def fmt_num(n: int) -> str:
    """Форматирует число с пробелами в качестве разделителя тысяч."""
    return f"{n:,}".replace(",", " ")

async def check_ban_msg(message: Message) -> bool:
    """Проверяет, забанен ли пользователь, и отправляет сообщение при бане."""
    if message.from_user.id == ADMIN_ID: # Админ всегда не забанен
        return False
    user = await get_user(message.from_user.id)
    if user is None:
        print(f"!!! ОШИБКА: Не удалось получить данные пользователя {message.from_user.id} для проверки бана. !!!")
        await message.answer("❌ Произошла ошибка при проверке статуса. Попробуйте позже.")
        return True # Считаем забаненным, чтобы предотвратить доступ
    if user['banned'] == 1:
        await message.answer("🚫 Вы заблокированы и не можете играть.")
        return True
    return False

# --- Состояния FSM для админ-панели ---
class AdminStates(StatesGroup):
    waiting_give_amount = State() # Ожидание суммы для начисления
    waiting_user_id_for_action = State() # Ожидание ID пользователя для бана/разбана/начисления
    waiting_target_user_id = State() # Ожидание ID пользователя для начисления по ID
    waiting_amount_for_id = State() # Ожидание суммы для начисления по ID

# --- Обработчики команд ---
@router.message(Command("start"))
async def cmd_start(message: Message):
    await get_user(message.from_user.id) # Убедимся, что пользователь есть в БД
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
    if user is None:
        await message.answer("❌ Произошла ошибка при получении данных. Попробуйте позже.")
        return
    await message.answer(
        f"💰 <b>Ваш баланс:</b> {fmt_num(user['balance'])} монет\n"
        f"📊 <b>Заработано сегодня:</b> {fmt_num(user['daily_won'])} монет"
    )

@router.message(F.text.lower() == "лб")
async def cmd_leaderboard(message: Message):
    today = datetime.now().strftime("%Y-%m-%d")
    if not db_pool: 
        await message.answer("❌ Не удалось подключиться к базе данных для отображения лидерборда.")
        return
    try:
        async with db_pool.acquire() as db:
            rows = await db.fetch(
                "SELECT user_id, daily_won FROM users WHERE daily_date = $1 AND daily_won > 0 ORDER BY daily_won DESC LIMIT 10",
                today
            )
    except Exception as e:
        print(f"!!! ОШИБКА получения лидерборда: {e} !!!")
        await message.answer("❌ Произошла ошибка при получении данных лидерборда.")
        return

    if not rows:
        await message.answer("📊 Сегодня ещё никто не выиграл. Будь первым!")
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
            if chat.username:
                name += f" (@{chat.username})"
        except Exception:
            name = f"Игрок {uid}" # Если не удалось получить информацию о пользователе
            
        text += f"{medal} {name} — {fmt_num(won)} монет\n"
        
    await message.answer(text)

@router.message(F.text.lower() == "бонус")
async def cmd_bonus(message: Message):
    if await check_ban_msg(message):
        return
    
    user = await get_user(message.from_user.id)
    if user is None:
        await message.answer("❌ Произошла ошибка при получении данных. Попробуйте позже.")
        return
        
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
        except ValueError: # Если формат даты некорректный
            print(f"!!! ОШИБКА: Некорректный формат last_bonus для пользователя {message.from_user.id}: {user['last_bonus']} !!!")
            # Продолжаем, как будто бонуса не было
            pass

    amount = random.randint(5000, 100000)
    await update_balance(message.from_user.id, amount)
    try:
        async with db_pool.acquire() as db:
            await db.execute("UPDATE users SET last_bonus = $1 WHERE user_id = $2",
                             now.isoformat(), message.from_user.id)
    except Exception as e:
        print(f"!!! ОШИБКА обновления last_bonus для {message.from_user.id}: {e} !!!")
        
    await message.answer(f"🎁 <b>Бонус получен!</b>\n💵 +{fmt_num(amount)} монет")

# ==================== ИГРА: МИНЫ ====================

active_mines = {} # Словарь для хранения активных игр в мины {user_id: game_data}

def mines_keyboard(user_id: int, opened: set, all_opened_reveal=None):
    """Создает клавиатуру для игры Мины."""
    kb = []
    for row in range(5):
        line = []
        for col in range(5):
            idx = row * 5 + col
            if idx in opened:
                # Если клетка уже открыта
                if all_opened_reveal and all_opened_reveal.get(idx) == "mine":
                    line.append(InlineKeyboardButton(text="💥", callback_data="none")) # Мина
                else:
                    line.append(InlineKeyboardButton(text="💎", callback_data="none")) # Безопасно
            else:
                # Если клетка закрыта
                if all_opened_reveal and all_opened_reveal.get(idx) == "mine":
                    line.append(InlineKeyboardButton(text="💥", callback_data="none")) # Мина (если игра окончена)
                else:
                    line.append(InlineKeyboardButton(text="🔒", callback_data=f"mine:{user_id}:{idx}")) # Закрытая клетка
        kb.append(line)
    
    # Добавляем кнопку "Забрать выигрыш", только если игра еще не окончена
    if all_opened_reveal is None:
        kb.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data=f"minecash:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def calc_multiplier(opened_count, mines_count):
    """Рассчитывает множитель для игры Мины."""
    if opened_count == 0:
        return 1.0
    # Формула расчета вероятности выживания
    prob_survival = 1.0
    for i in range(opened_count):
        prob_survival *= (25 - mines_count - i) / (25 - i)
    # Множитель = 0.97 / вероятность выживания (0.97 - небольшой коэффициент для казино)
    return round(0.97 / prob_survival, 2)

@router.message(F.text.lower().regexp(r'^(мины|mines)\s+(\d+)\s+(\d+)$'))
async def cmd_mines(message: Message):
    if await check_ban_msg(message):
        return
    
    match = F.text.lower().regexp(r'^(мины|mines)\s+(\d+)\s+(\d+)$').match(message.text)
    bet_str, mines_count_str = match.group(2), match.group(3)
    
    try:
        bet = int(bet_str)
        mines_count = int(mines_count_str)
    except ValueError:
        await message.answer("❌ Ставка и количество мин должны быть числами.")
        return

    if mines_count < 1 or mines_count > 24:
        await message.answer("❌ Количество мин должно быть от 1 до 24.")
        return
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return

    user = await get_user(message.from_user.id)
    if user is None:
        await message.answer("❌ Произошла ошибка при получении данных. Попробуйте позже.")
        return
    if bet > user['balance']:
        await message.answer("❌ Недостаточно средств.")
        return

    # Списываем ставку
    await update_balance(message.from_user.id, -bet)

    # Генерируем позиции мин
    positions = list(range(25))
    random.shuffle(positions)
    mines_positions = set(positions[:mines_count])

    # Сохраняем состояние игры
    active_mines[message.from_user.id] = {
        "bet": bet,
        "mines": mines_positions,
        "opened": set(),
        "mines_count": mines_count,
    }

    # Отправляем сообщение с клавиатурой
    await message.answer(
        f"💣 <b>Минное поле</b>\n"
        f"Ставка: {fmt_num(bet)} | Мин: {mines_count}\n"
        f"Открывай клетки. Чем больше открыл — тем больше выигрыш!\n"
        f"Множитель: <b>1.00x</b> | Выигрыш: <b>0</b>",
        reply_markup=mines_keyboard(message.from_user.id, set())
    )

@router.callback_query(F.data.startswith("mine:"))
async def cb_mine_open(callback: CallbackQuery):
    try:
        _, user_id_str, idx_str = callback.data.split(":")
        user_id = int(user_id_str)
        idx = int(idx_str)
    except ValueError:
        await callback.answer("❌ Ошибка в данных команды.", show_alert=True)
        return
        
    if user_id != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    game = active_mines.get(user_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        # Попытка удалить кнопку, если игра уже неактивна
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    if idx in game["opened"]:
        await callback.answer("Эта клетка уже открыта.")
        return

    # Проверяем, попал ли игрок на мину
    if idx in game["mines"]:
        reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
        for i in game["opened"]: # Отмечаем уже открытые безопасные клетки
            reveal[i] = "safe"
        
        # Логируем проигрыш
        await log_game(user_id, "mines", game["bet"], -game["bet"])
        
        del active_mines[user_id] # Удаляем игру из активных
        
        await callback.message.edit_text(
            f"💥 <b>БУМ! Ты наткнулся на мину.</b>\n"
            f"Потеряно: {fmt_num(game['bet'])} монет\n\n"
            f"<i>Вот где были мины:</i>",
            reply_markup=mines_keyboard(user_id, game["opened"] | {idx}, reveal) # Показываем все мины
        )
        await callback.answer("💥 Мина!")
        return

    # Если клетка безопасна
    game["opened"].add(idx)
    opened_count = len(game["opened"])
    mult = calc_multiplier(opened_count, game["mines_count"])
    win = int(game["bet"] * mult)

    # Обновляем сообщение с текущим состоянием игры
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
    try:
        user_id_str = callback.data.split(":")[1]
        user_id = int(user_id_str)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка в данных команды.", show_alert=True)
        return
        
    if user_id != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    game = active_mines.get(user_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        # Попытка удалить кнопку, если игра уже неактивна
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    if not game["opened"]:
        await callback.answer("Сначала открой хотя бы одну клетку!", show_alert=True)
        return

    opened_count = len(game["opened"])
    mult = calc_multiplier(opened_count, game["mines_count"])
    win = int(game["bet"] * mult)
    profit = win - game["bet"] # Чистый выигрыш

    # Обновляем баланс и статистику
    await update_balance(user_id, win)
    await add_daily_win(user_id, profit)
    await log_game(user_id, "mines", game["bet"], profit) # Логируем чистый выигрыш

    del active_mines[user_id] # Удаляем игру из активных

    # Показываем финальный результат с расположением мин
    reveal = {i: ("mine" if i in game["mines"] else "safe") for i in range(25)}
    for i in game["opened"]: # Отмечаем уже открытые безопасные клетки
        reveal[i] = "safe"
    
    await callback.message.edit_text(
        f"💰 <b>Выигрыш забран!</b>\n"
        f"Выигрыш: <b>{fmt_num(win)}</b> монет (x{mult:.2f})\n\n"
        f"<i>Вот где были мины:</i>",
        reply_markup=mines_keyboard(user_id, game["opened"], reveal) # Показываем все мины
    )
    await callback.answer("💰 Забрано!")

# ==================== ИГРА: HI-LO (ХАЙ-ЛОУ) ====================

active_hilo = {} # Словарь для хранения активных игр Hi-Lo {user_id: game_data}

SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANKS = { # Значения карт для сравнения
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K", 14: "A"
}

def draw_card():
    """Генерирует случайную карту (ранг, масть)."""
    rank = random.randint(2, 14) # Ранг от 2 до Туза (14)
    suit = random.choice(SUITS)
    return rank, suit

def get_card_str(rank, suit):
    """Возвращает строковое представление карты."""
    return f"[{RANKS[rank]} {suit}]"

def calc_hilo_mult(current_rank, guess):
    """Рассчитывает множитель для следующего хода в Hi-Lo."""
    if guess == "high":
        # Количество карт с рангом выше текущего
        higher_ranks_count = 14 - current_rank
        # Общее количество возможных карт для выигрыша (учитывая, что одинаковые ранги тоже считаются)
        # Всего 52 карты. Из них 4 текущего ранга. Остается 48.
        # Карты выше: (14 - current_rank) * 4
        # Карты ниже: (current_rank - 2) * 4
        
        # Если выпал тот же ранг, это тоже считается выигрышем "выше или равно"
        possible_win_cards = (higher_ranks_count * 4) + 4 # Добавляем 4 карты того же ранга
        
        # Если текущая карта Туз (14), то выше ничего нет
        if current_rank == 14: return 1.0 
        
        # Вероятность выигрыша = (количество карт, которые нас устроят) / (общее количество оставшихся карт)
        # Общее количество карт = 52. Убираем 4 карты текущего ранга. Остается 48.
        prob = (higher_ranks_count * 4) / 48.0 
        
    elif guess == "low":
        # Количество карт с рангом ниже текущего
        lower_ranks_count = current_rank - 2
        if current_rank == 2: return 1.0 # Если текущая карта 2, то ниже ничего нет
        
        possible_win_cards = (lower_ranks_count * 4) + 4 # Добавляем 4 карты того же ранга
        prob = (lower_ranks_count * 4) / 48.0
    else:
        return 1.0 # Некорректный ход

    if prob <= 0: 
        return 1.0 # На всякий случай
        
    # Множитель = 1 / вероятность (с учетом комиссии казино)
    return round((1.0 / prob) * 0.95, 2)

def hilo_keyboard(user_id: int, current_card_rank, current_mult=1.0):
    """Создает клавиатуру для игры Hi-Lo."""
    high_mult = calc_hilo_mult(current_card_rank, "high")
    low_mult = calc_hilo_mult(current_card_rank, "low")
    
    kb = []
    # Кнопки "Выше/Равно" и "Ниже/Равно"
    row1 = []
    if high_mult > 1.0: # Показываем только если множитель больше 1
        row1.append(InlineKeyboardButton(text=f"⬆️ Выше/={high_mult:.2f}x", callback_data=f"hilo:{user_id}:high"))
    if low_mult > 1.0: # Показываем только если множитель больше 1
        row1.append(InlineKeyboardButton(text=f"⬇️ Ниже/={low_mult:.2f}x", callback_data=f"hilo:{user_id}:low"))
    
    if row1: # Добавляем строку, только если есть кнопки
        kb.append(row1)
    
    # Кнопка "Забрать выигрыш", если множитель больше 1
    if current_mult > 1.0:
        kb.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data=f"hilocash:{user_id}")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(F.text.lower().regexp(r'^(хило|хл|hilo)\s+(\d+)$'))
async def cmd_hilo(message: Message):
    if await check_ban_msg(message):
        return
    
    match = F.text.lower().regexp(r'^(хило|хл|hilo)\s+(\d+)$').match(message.text)
    bet_str = match.group(2)
    
    try:
        bet = int(bet_str)
    except ValueError:
        await message.answer("❌ Ставка должна быть числом. Пример: <code>хило 100</code>")
        return

    user = await get_user(message.from_user.id)
    if user is None:
        await message.answer("❌ Произошла ошибка при получении данных. Попробуйте позже.")
        return
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return
    if bet > user['balance']:
        await message.answer("❌ Недостаточно средств.")
        return

    # Списываем ставку
    await update_balance(message.from_user.id, -bet)

    # Генерируем первую карту
    rank, suit = draw_card()
    
    # Сохраняем состояние игры
    active_hilo[message.from_user.id] = {
        "bet": bet,
        "current_rank": rank,
        "current_suit": suit,
        "multiplier": 1.0, # Начинаем с множителем 1.0
    }

    card_str = get_card_str(rank, suit)
    text = (
        f"🃏 <b>Игра Hi-Lo началась!</b>\n"
        f"Текущая карта: <b>{card_str}</b>\n"
        f"Ставка: {fmt_num(bet)}\n\n"
        f"Угадай, будет ли следующая карта <b>Выше/Равно</b> или <b>Ниже/Равно</b>:"
    )
    await message.answer(text, reply_markup=hilo_keyboard(message.from_user.id, rank, 1.0))

@router.callback_query(F.data.startswith("hilo:"))
async def cb_hilo_guess(callback: CallbackQuery):
    try:
        _, user_id_str, guess = callback.data.split(":")
        user_id = int(user_id_str)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка в данных команды.", show_alert=True)
        return
        
    if user_id != callback.from_user.id:
        await callback.answer("Это не твоя игра.", show_alert=True)
        return

    game = active_hilo.get(user_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    current_rank = game["current_rank"]
    current_card = get_card_str(current_rank, game["current_suit"])
    
    # Рассчитываем множитель для текущего шага
    step_mult = calc_hilo_mult(current_rank, guess)
    
    # Генерируем новую карту
    new_rank, new_suit = draw_card()
    new_card = get_card_str(new_rank, new_suit)
    
    win = False
    # Проверяем, угадал ли игрок
    if guess == "high" and new_rank >= current_rank:
        win = True
    elif guess == "low" and new_rank <= current_rank:
        win = True
    
    if win:
        # Увеличиваем общий множитель игры
        game["multiplier"] = round(game["multiplier"] * step_mult, 2)
        
        # Обновляем текущую карту для следующего хода
        game["current_rank"] = new_rank
        game["current_suit"] = new_suit
        
        mult = game["multiplier"]
        win_amount = int(game["bet"] * mult)
        
        msg_prefix = "🎉 <b>Угадал!</b>\n\n"
        # Особый случай: выпал тот же ранг
        if new_rank == current_rank:
            msg_prefix = "😮 <b>Выпал тот же ранг! Продолжаем.</b>\n\n"
            
        text = (
            f"{msg_prefix}"
            f"Было: {current_card} ➡️ Стало: {new_card}\n"
            f"Текущий множитель: <b>{mult:.2f}x</b>\n"
            f"Потенциальный выигрыш: <b>{fmt_num(win_amount)}</b> монет\n\n"
            f"Продолжаем или забираем?"
        )
        await callback.message.edit_text(text, reply_markup=hilo_keyboard(user_id, new_rank, game["multiplier"]))
    else:
        # Проигрыш
        profit = -game["bet"] # Чистый проигрыш равен
