import random
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5118497284  # ВАШ ИГРОВОЙ ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# База данных игроков
users = {}
# Состояния игр
games_state = {}

def get_user(user_id, name="Игрок"):
    if user_id not in users:
        users[user_id] = {"name": name, "balance": 100, "total_won": 0}
    return users[user_id]

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    get_user(message.from_user.id, message.from_user.first_name)
    
    # Убрали кнопки игр, так как игры теперь пишутся текстом
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Бонус", callback_data="menu_bonus")
    builder.button(text="🏦 Банк (Перевод)", callback_data="menu_bank")
    builder.button(text="🏆 Лидерборд", callback_data="menu_top")
    builder.button(text="💰 Мой баланс", callback_data="menu_balance")
    builder.adjust(2, 2)
    
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n"
        f"Твой баланс: {users[message.from_user.id]['balance']} Bin\n\n"
        f"🎮 **Доступные игры (пиши в чат):**\n"
        f"├ 💣 `Мины [ставка] [мины]` (Пример: Мины 100 2)\n"
        f"├ 🪙 `Флип [ставка]` (Орел/Решка)\n"
        f"├ ♦️ `Хило [ставка]` (Больше/Меньше)\n"
        f"└ 💥 `Хотлайн [ставка]` (Рискнуть всем)\n\n"
        f"Напиши **Б**, чтобы узнать баланс.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# --- БАЛАНС ПО БУКВЕ Б ---
@dp.message(F.text.lower() == "б")
async def show_balance_letter(message: types.Message):
    user = get_user(message.from_user.id)
    await message.answer(f"💰 Твой баланс: **{user['balance']} Bin**\n📈 Всего выиграно: {user['total_won']} Bin", parse_mode="Markdown")

# --- БАЗОВЫЕ КНОПКИ ---
@dp.callback_query(F.data == "menu_balance")
async def show_balance(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    await callback.message.answer(f"💰 Твой баланс: {user['balance']} Bin\n📈 Всего выиграно: {user['total_won']} Bin")
    await callback.answer()

@dp.callback_query(F.data == "menu_bonus")
async def daily_bonus(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    bonus = random.randint(50000, 100000) 
    user['balance'] += bonus
    await callback.message.answer(f"🎁 Ты получил бонус: {bonus} Bin!\nТвой баланс: {user['balance']} Bin")
    await callback.answer()

@dp.callback_query(F.data == "menu_top")
async def show_top(callback: types.CallbackQuery):
    sorted_users = sorted(users.items(), key=lambda item: item[1]['total_won'], reverse=True)
    text = "🏆 **Лидерборд (Топ игроков):**\n\n"
    count = 0
    for uid, data in sorted_users:
        if data['total_won'] > 0:
            count += 1
            text += f"{count}. {data['name']} — {data['total_won']} Bin\n"
        if count == 10:
            break
    if count == 0:
        text = "Пока никто не играл. Станьте первым!"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

# --- БАНК (ПЕРЕВОДЫ) ---
@dp.callback_query(F.data == "menu_bank")
async def start_transfer(callback: types.CallbackQuery):
    await callback.message.edit_text("🏦 Введите имя игрока и сумму через пробел.\nПример: `Вася 10000`\n\nМаксимум за раз: 50 000 Bin.", parse_mode="Markdown")
    games_state[callback.from_user.id] = {"game": "transfer"}

@dp.message(F.text.regexp(r'^.+ \d+$'))
async def process_transfer(message: types.Message):
    uid = message.from_user.id
    if uid in games_state and games_state[uid].get("game") == "transfer":
        try:
            name_target, amount_str = message.text.rsplit(' ', 1)
            amount = int(amount_str)
            sender = get_user(uid)
            
            if amount > 50000:
                await message.answer("❌ Максимум за один перевод — 50 000 Bin.")
                return
            if amount <= 0:
                await message.answer("❌ Сумма должна быть больше нуля.")
                return
            if sender['balance'] < amount:
                await message.answer("❌ У вас недостаточно средств на балансе.")
                return
                
            found = False
            for target_uid, target_data in users.items():
                if target_data['name'].lower() == name_target.lower() and target_uid != uid:
                    sender['balance'] -= amount
                    target_data['balance'] += amount
                    await message.answer(f"✅ Вы перевели {amount} Bin игроку {target_data['name']}.")
                    found = True
                    break
            
            if not found:
                await message.answer("❌ Игрок с таким именем не найден (он должен зайти в бота).")
            
            del games_state[uid]
        except Exception:
            await message.answer("Ошибка формата. Введите: Имя Сумма")

# --- АДМИН КОМАНДА (/give) ---
@dp.message(Command("give"))
async def admin_give(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет прав.")
        return
    try:
        args = message.text.split()
        target_username = args[1]
        amount = int(args[2])
        
        if amount > 9999999999:
            await message.answer("❌ Максимум можно выдать 9 999 999 999 Bin.")
            return
            
        found = False
        for uid, data in users.items():
            if data['name'].lower() == target_username.lower():
                data['balance'] += amount
                await message.answer(f"✅ Админ начислил {amount} Bin игроку {data['name']}.")
                found = True
                break
        if not found:
            await message.answer("Игрок не найден.")
    except:
        await message.answer("Формат: /give Имя 5000")

# --- ИГРА 1: МИНЫ (25 клеток) ---
@dp.message(F.text.lower().startswith("мины "))
async def start_mines(message: types.Message):
    uid = message.from_user.id
    user = get_user(uid)
    try:
        args = message.text.split()
        bet = int(args[1])
        mine_count = int(args[2])
        
        if bet <= 0 or bet > user['balance']:
            await message.answer("Недостаточно средств!")
            return
        if mine_count < 1 or mine_count > 24:
            await message.answer("Количество мин должно быть от 1 до 24!")
            return
            
        user['balance'] -= bet
        mines = random.sample(range(1, 26), mine_count)
        games_state[uid] = {"game": "mines_play", "bet": bet, "mines": mines, "mine_count": mine_count}
        
        builder = InlineKeyboardBuilder()
        for i in range(1, 26):
            builder.button(text=str(i), callback_data=f"mines_{i}")
        builder.adjust(5)
        
        await message.answer(f"💣 Ставка {bet} Bin. Мин: {mine_count}.\nВыбери клетку на поле 5х5:", reply_markup=builder.as_markup())
    except:
        await message.answer("Формат: Мины [ставка] [мины]\nПример: Мины 100 2")

@dp.callback_query(F.data.startswith("mines_"))
async def play_mines(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in games_state or games_state[uid].get("game") != "mines_play":
        await callback.answer("Игра не найдена.")
        return
        
    choice = int(callback.data.split("_")[1])
    state = games_state[uid]
    user = get_user(uid)
    
    if choice in state['mines']:
        await callback.message.edit_text(f"💥 БУМ! Ты попал на мину ({choice}). Потеряно {state['bet']} Bin.\nБаланс: {user['balance']}")
    else:
        # Чем больше мин, тем больше множитель (упрощенно x2)
        win = state['bet'] * 2
        user['balance'] += win
        user['total_won'] += state['bet']
        await callback.message.edit_text(f"✅ Фух! Мины были на {state['mines']}.\nТы выиграл {win} Bin!\nБаланс: {user['balance']}")
        
    del games_state[uid]

# --- ИГРА 2: ФЛИП (Орел/Решка) ---
@dp.message(F.text.lower().startswith("флип "))
async def start_flip(message: types.Message):
    uid = message.from_user.id
    user = get_user(uid)
    try:
        bet = int(message.text.split()[1])
        if bet <= 0 or bet > user['balance']:
            await message.answer("Недостаточно средств!")
            return
            
        user['balance'] -= bet
        games_state[uid] = {"game": "flip_play", "bet": bet}
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🦅 Орел", callback_data="flip_heads")
        builder.button(text="🪙 Решка", callback_data="flip_tails")
        
        await message.answer(f"🪙 Ставка {bet} Bin. На что ставишь?", reply_markup=builder.as_markup())
    except:
        await message.answer("Формат: Флип [ставка]\nПример: Флип 100")

@dp.callback_query(F.data.startswith("flip_"))
async def play_flip(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in games_state or games_state[uid].get("game") != "flip_play":
        await callback.answer("Игра не найдена.")
        return
        
    choice = callback.data.split("_")[1]
    state = games_state[uid]
    user = get_user(uid)
    
    result = random.choice(["heads", "tails"])
    result_ru = "Орел 🦅" if result == "heads" else "Решка 🪙"
    
    if choice == result:
        win = state['bet'] * 2
        user['balance'] += win
        user['total_won'] += state['bet']
        await callback.message.edit_text(f"Выпало: {result_ru}\n🎉 Ты угадал! Выигрыш: {win} Bin.\nБаланс: {user['balance']}")
    else:
        await callback.message.edit_text(f"Выпало: {result_ru}\n❌ Не угадал. Потеряно: {state['bet']} Bin.\nБаланс: {user['balance']}")
        
    del games_state[uid]

# --- ИГРА 3: ХИЛО (Больше/Меньше) ---
@dp.message(F.text.lower().startswith("хило "))
async def start_hilo(message: types.Message):
    uid = message.from_user.id
    user = get_user(uid)
    try:
        bet = int(message.text.split()[1])
        if bet <= 0 or bet > user['balance']:
            await message.answer("Недостаточно средств!")
            return
            
        user['balance'] -= bet
        card = random.randint(2, 14)
        games_state[uid] = {"game": "hilo_play", "bet": bet, "card": card}
        
        builder = InlineKeyboardBuilder()
        builder.button(text="⬆️ Больше", callback_data="hilo_more")
        builder.button(text="⬇️ Меньше", callback_data="hilo_less")
        
        await message.answer(f"♦️ Ставка {bet} Bin.\nТекущая карта: {get_card_name(card)}\nСледующая будет больше или меньше?", reply_markup=builder.as_markup())
    except:
        await message.answer("Формат: Хило [ставка]\nПример: Хило 100")

@dp.callback_query(F.data.startswith("hilo_"))
async def play_hilo(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in games_state or games_state[uid].get("game") != "hilo_play":
        await callback.answer("Игра не найдена.")
        return
        
    choice = callback.data.split("_")[1]
    state = games_state[uid]
    user = get_user(uid)
    
    next_card = random.randint(2, 14)
    while next_card == state['card']:
        next_card = random.randint(2, 14)
        
    win = False
    if choice == "more" and next_card > state['card']: win = True
    if choice == "less" and next_card < state['card']: win = True
    
    if win:
        win_amount = state['bet'] * 2
        user['balance'] += win_amount
        user['total_won'] += state['bet']
        result_text = f"🎉 Угадал! Выигрыш: {win_amount} Bin."
    else:
        result_text = f"❌ Не угадал. Потеряно: {state['bet']} Bin."
        
    await callback.message.edit_text(
        f"Была: {get_card_name(state['card'])}\nСтала: {get_card_name(next_card)}\n\n{result_text}\nБаланс: {user['balance']}"
    )
    del games_state[uid]

# --- ИГРА 4: ХОТЛАЙН (Рискнуть всем) ---
@dp.message(F.text.lower().startswith("хотлайн "))
async def start_hotline(message: types.Message):
    uid = message.from_user.id
    user = get_user(uid)
    try:
        bet = int(message.text.split()[1])
        if bet <= 0 or bet > user['balance']:
            await message.answer("Недостаточно средств!")
            return
            
        user['balance'] -= bet
        games_state[uid] = {"game": "hotline_play", "bet": bet}
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔥 Рискнуть (x2)", callback_data="hotline_risk")
        
        await message.answer(f"💥 Ставка {bet} Bin принята.\nНажми кнопку, чтобы испытать удачу!", reply_markup=builder.as_markup())
    except:
        await message.answer("Формат: Хотлайн [ставка]\nПример: Хотлайн 100")

@dp.callback_query(F.data == "hotline_risk")
async def play_hotline(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in games_state or games_state[uid].get("game") != "hotline_play":
        await callback.answer("Игра не найдена.")
        return
        
    state = games_state[uid]
    user = get_user(uid)
    
    # Шанс выигрыша 45% (как в рулетке)
    if random.random() < 0.45:
        win = state['bet'] * 2
        user['balance'] += win
        user['total_won'] += state['bet']
        await callback.message.edit_text(f"🔥 Тебе повезло! Выигрыш: {win} Bin.\nБаланс: {user['balance']}")
    else:
        await callback.message.edit_text(f"💥 Не повезло... Потеряно: {state['bet']} Bin.\nБаланс: {user['balance']}")
        
    del games_state[uid]

# Вспомогательная функция карт
def get_card_name(card):
    if card == 11: return "Валет (11)"
    if card == 12: return "Дама (12)"
    if card == 13: return "Король (13)"
    if card == 14: return "Туз (14)"
    return str(card)

# Обработка прочего текста
@dp.message()
async def catch_all(message: types.Message):
    await message.answer("Напиши /start для выхода в главное меню.")

if __name__ == "__main__":
    print("Бот запущен!")
    dp.run_polling(bot)
