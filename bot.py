import random
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Берем токен из переменной окружения, которую вы настроили на Bothost
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Словарь для хранения загаданных чисел (в реальном проекте лучше использовать базу данных)
games = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Создаем кнопку для начала игры
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="🎮 Начать игру", 
        callback_data="start_game")
    )
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n"
        "Я загадаю число от 1 до 100, а ты попробуй угадать!\n"
        "Нажми на кнопку ниже, чтобы начать.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "start_game")
async def process_start_game(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # Загадываем число и сохраняем его для игрока
    secret_number = random.randint(1, 100)
    games[user_id] = secret_number
    
    await callback.message.edit_text(
        "Я загадал число от 1 до 100. Напиши свою догадку!"
    )
    await callback.answer()

@dp.message()
async def process_guess(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем, играет ли пользователь
    if user_id not in games:
        await message.answer("Сначала напиши /start, чтобы начать игру!")
        return

    # Пытаемся превратить текст в число
    try:
        guess = int(message.text)
        if guess < 1 or guess > 100:
            await message.answer("Пожалуйста, введи число от 1 до 100.")
            return
    except ValueError:
        await message.answer("Это не похоже на число. Введи цифру от 1 до 100.")
        return

    secret_number = games[user_id]

    # Логика игры
    if guess == secret_number:
        await message.answer(f"🎉 Поздравляю! Ты угадал число {secret_number}!\nНапиши /start, чтобы сыграть еще раз.")
        del games[user_id]  # Удаляем игру, так как она закончена
    elif guess < secret_number:
        await message.answer("📉 Мое число больше. Попробуй еще!")
    else:
        await message.answer("📈 Мое число меньше. Попробуй еще!")

# Запуск бота
if __name__ == "__main__":
    print("Бот запущен!")
    dp.run_polling(bot)
