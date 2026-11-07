import random
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилища для игр
mines_games = {}
hilo_games = {}

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="💣 Минное поле", callback_data="game_mines")
    builder.button(text="🃏 Хило (Карты)", callback_data="game_hilo")
    builder.adjust(1)
    
    await message.answer(
        f"Привет, {message.from_user.first_name}!\nВыбери игру:",
        reply_markup=builder.as_markup()
    )

# --- ИГРА 1: МИННОЕ ПОЛЕ ---
@dp.callback_query(F.data == "game_mines")
async def start_mines(callback: types.CallbackQuery):
    # Загадываем позицию мины от 1 до 10
    mines_games[callback.from_user.id] = random.randint(1, 10)
    await callback.message.edit_text("💣 Я заминировал поле от 1 до 10.\nНапиши число, где, по-твоему, мина (или безопасная клетка):")

@dp.message(F.text.regexp(r'^\d+$'))
async def process_mines(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in mines_games:
        guess = int(message.text)
        if guess < 1 or guess > 10:
            await message.answer("Введи число от 1 до 10!")
            return
            
        secret_mine = mines_games[user_id]
        
        if guess == secret_mine:
            await message.answer(f"💥 БУМ! Ты наступил на мину (она была на {secret_mine}).\nНапиши /start, чтобы сыграть еще.")
            del mines_games[user_id]
        else:
            await message.answer(f"✅ Фух! Здесь мины нет (она была на {secret_mine}).\nНапиши /start для выхода в меню.")
            del mines_games[user_id]

# --- ИГРА 2: ХИЛО (КАРТЫ) ---
@dp.callback_query(F.data == "game_hilo")
async def start_hilo(callback: types.CallbackQuery):
    # Генерируем первую карту от 2 до 14 (11=Валет, 12=Дама, 13=Король, 14=Туз)
    first_card = random.randint(2, 14)
    hilo_games[callback.from_user.id] = first_card
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⬆️ Больше", callback_data="hilo_more")
    builder.button(text="⬇️ Меньше", callback_data="hilo_less")
    
    card_name = get_card_name(first_card)
    await callback.message.edit_text(
        f"Текущая карта: {card_name}\n\nСледующая карта будет больше или меньше?",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("hilo_"))
async def process_hilo(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in hilo_games:
        await callback.answer("Игра не найдена. Напиши /start")
        return
        
    current_card = hilo_games[user_id]
    # Генерируем новую карту, чтобы она не была равна текущей
    next_card = random.randint(2, 14)
    while next_card == current_card:
        next_card = random.randint(2, 14)
        
    choice = callback.data.split("_")[1]
    
    win = False
    if choice == "more" and next_card > current_card:
        win = True
    elif choice == "less" and next_card < current_card:
        win = True
        
    result_text = "🎉 Ты угадал!" if win else "❌ Не угадал."
    
    await callback.message.edit_text(
        f"Была карта: {get_card_name(current_card)}\n"
        f"Стала карта: {get_card_name(next_card)}\n\n"
        f"{result_text}\n\nНапиши /start, чтобы сыграть еще."
    )
    del hilo_games[user_id]

# Вспомогательная функция для названий карт
def get_card_name(card):
    if card == 11: return "Валет (11)"
    if card == 12: return "Дама (12)"
    if card == 13: return "Король (13)"
    if card == 14: return "Туз (14)"
    return str(card)

# Обработка прочего текста
@dp.message()
async def process_other(message: types.Message):
    await message.answer("Напиши /start, чтобы выбрать игру!")

if __name__ == "__main__":
    print("Бот запущен!")
    dp.run_polling(bot)
