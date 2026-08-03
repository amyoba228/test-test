import asyncio
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Токен берется из переменных окружения хостинга
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Не найден токен бота! Укажите переменную окружения BOT_TOKEN.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Временное хранилище сессий пользователей
active_sessions = {}

CATEGORIES_INFO = {
    "general": {
        "title": "🌟 Общие",
        "traits": {
            "str": "Сила", "spd": "Скорость", "react": "Реакция",
            "swim": "Плавание", "inv": "Изобретательность", "agi": "Ловкость", "sky": "Связь с Небом"
        }
    },
    "combat": {
        "title": "⚔️ Бой и охота",
        "traits": {
            "c_fight": "в бою", "c_hunt": "в охоте"
        }
    },
    "senses": {
        "title": "👁 Здоровье",
        "traits": {
            "s_smell": "Нюх", "s_hear": "Слух", "s_sight": "Зрение", "s_touch": "Осязание"
        }
    },
    "discussed": {
        "title": "🗣 Обговорённые",
        "traits": {
            "d_herbs": "Знание трав", "d_heal": "Навык лечения", "d_talk": "Разговор с иными видами"
        }
    }
}

def get_points(moons: int):
    if 0 <= moons <= 5: return {"combat": 4, "general": 14, "senses": 16}
    elif 6 <= moons <= 11: return {"combat": 8, "general": 28, "senses": 20}
    elif 12 <= moons <= 23: return {"combat": 10, "general": 35, "senses": 25}
    elif 24 <= moons <= 71: return {"combat": 13, "general": 40, "senses": 30}
    elif 72 <= moons <= 95: return {"combat": 10, "general": 35, "senses": 25}
    else: return {"combat": 8, "general": 30, "senses": 20}

# --- ГЛАВНОЕ МЕНЮ ---
def get_home_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Распределить очки (Ввести луны)", callback_data="start_distrib")]
    ])

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    text = "Привет! Это бот для распределения очков характеристик по возрасту (лунам).\n\nНажми кнопку ниже, чтобы начать:"
    await message.answer(text, reply_markup=get_home_keyboard())

@dp.callback_query(F.data == "go_home")
async def go_home(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in active_sessions:
        del active_sessions[user_id]
    
    text = "Главное меню:"
    await callback.message.edit_text(text, reply_markup=get_home_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "start_distrib")
async def start_distrib(callback: types.CallbackQuery):
    await callback.message.edit_text("Напиши мне числом, сколько у тебя лун:")
    active_sessions[callback.from_user.id] = {"step": "waiting_moons"}
    await callback.answer()

# Обработка текстовых сообщений (ввод лун)
@dp.message(F.text)
async def process_text_messages(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in active_sessions and active_sessions[user_id].get("step") == "waiting_moons":
        if not message.text.isdigit():
            return await message.answer("Пожалуйста, введи возраст числом (например: 12):")
        
        moons = int(message.text)
        points = get_points(moons)
        
        active_sessions[user_id] = {
            "step": "distributing",
            "moons": moons,
            "total": points,
            "traits": {
                "general": {"str": 0, "spd": 0, "react": 0, "swim": 0, "inv": 0, "agi": 0, "sky": 0},
                "combat": {"c_fight": 0, "c_hunt": 0},
                "senses": {"s_smell": 0, "s_hear": 0, "s_sight": 0, "s_touch": 0},
                "discussed": {"d_herbs": 0, "d_heal": 0, "d_talk": 0}
            }
        }
        
        text = f"🌙 Возраст: {moons} лун\n\nВыбери категорию для распределения очков:"
        await message.answer(text, reply_markup=get_main_keyboard(active_sessions[user_id]))
        return

def get_main_keyboard(data):
    tot = data["total"]
    spent_gen = sum(data["traits"]["general"].values())
    spent_com = sum(data["traits"]["combat"].values())
    spent_sen = sum(data["traits"]["senses"].values())
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌟 Общие ({spent_gen}/{tot['general']})", callback_data="cat_general")],
        [InlineKeyboardButton(text=f"⚔️ Боёвка (техники) ({spent_com}/{tot['combat']})", callback_data="cat_combat")],
        [InlineKeyboardButton(text=f"👁 Здоровье ({spent_sen}/{tot['senses']})", callback_data="cat_senses")],
        [InlineKeyboardButton(text="🗣 Обговорённые", callback_data="cat_discussed")],
        [InlineKeyboardButton(text="🏠 Начать заново / В меню", callback_data="go_home")]
    ])

@dp.callback_query(F.data.in_(["cat_general", "cat_combat", "cat_senses", "cat_discussed"]))
async def open_category(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in active_sessions or active_sessions[user_id].get("step") != "distributing":
        return await callback.answer("Сначала введи луны через главное меню!", show_alert=True)
    
    cat_key = callback.data.replace("cat_", "")
    await update_category_menu(callback, cat_key)
    await callback.answer()

async def update_category_menu(callback: types.CallbackQuery, cat_key: str):
    user_id = callback.from_user.id
    data = active_sessions[user_id]
    cat_info = CATEGORIES_INFO[cat_key]
    spent_points = sum(data["traits"][cat_key].values())
    
    if cat_key == "discussed":
        remains_text = f"Потрачено очков: {spent_points} (без лимита)"
    else:
        total_points = data["total"][cat_key]
        remains = total_points - spent_points
        remains_text = f"Остаток очков: {remains}"

    kb = []
    for trait_id, current_val in data["traits"][cat_key].items():
        base_name = cat_info["traits"][trait_id]
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"minus:{cat_key}:{trait_id}"),
            InlineKeyboardButton(text=base_name, callback_data="ignore"),
            InlineKeyboardButton(text=f"[{current_val}]", callback_data=f"plus:{cat_key}:{trait_id}")
        ])
    
    kb.append([InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_distrib")])

    display_title = "⚔️ Боёвка (техники)" if cat_key == "combat" else cat_info['title']
    text = f"{display_title}\n{remains_text}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("plus:") | F.data.startswith("minus:"))
async def change_trait(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in active_sessions:
        return await callback.answer("Сессия не найдена!", show_alert=True)

    parts = callback.data.split(":")
    action = parts[0]
    cat_key = parts[1]
    trait_id = parts[2]

    data = active_sessions[user_id]
    current_val = data["traits"][cat_key][trait_id]
    spent_points = sum(data["traits"][cat_key].values())

    if action == "plus":
        if current_val >= 10:
            return await callback.answer("Максимум 10 очков на одну характеристику!", show_alert=True)
        if cat_key != "discussed":
            remains = data["total"][cat_key] - spent_points
            if remains <= 0:
                return await callback.answer("Превышен лимит очков!", show_alert=True)
        data["traits"][cat_key][trait_id] += 1
    elif action == "minus":
        if current_val <= 0:
            return await callback.answer("Нельзя сделать меньше нуля!", show_alert=True)
        data["traits"][cat_key][trait_id] -= 1

    await update_category_menu(callback, cat_key)

@dp.callback_query(F.data == "back_to_distrib")
async def back_to_distrib(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in active_sessions:
        return await callback.answer("Сессия не найдена!", show_alert=True)
        
    moons = active_sessions[user_id]["moons"]
    text = f"🌙 Возраст: {moons} лун\n\nВыбери категорию для распределения очков:"
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(active_sessions[user_id]))

async def main():
    print("Бот распределения очков успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
