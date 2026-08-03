import asyncio
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Сюда вставь свой токен для Pydroid или оставь для хостинга через env
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ТВОЙ_ТОКЕН_ОТ_BOTFATHER"

if not BOT_TOKEN or "BOTFATHER" in BOT_TOKEN:
    raise ValueError("Не найден токен бота! Укажите действительный BOT_TOKEN.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- РАБОТА С БАЗОЙ ДАННЫХ SQLite ---
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            moons INTEGER,
            name TEXT,
            traits TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Временное хранилище для анкеты, которую пользователь прямо сейчас создает
active_creations = {}

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
        [InlineKeyboardButton(text="➕ Ввести возраст (Новая анкета)", callback_data="start_new_char")],
        [InlineKeyboardButton(text="📂 Посмотреть мои анкеты", callback_data="my_characters")]
    ])

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    text = "Привет! Это бот для создания характеристик персонажей.\n\nВыбери действие в меню:"
    await message.answer(text, reply_markup=get_home_keyboard())

@dp.callback_query(F.data == "go_home")
async def go_home(callback: types.CallbackQuery):
    text = "Главное меню:"
    await callback.message.edit_text(text, reply_markup=get_home_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "start_new_char")
async def start_new_char(callback: types.CallbackQuery):
    await callback.message.edit_text("Напиши мне числом, сколько лун твоему новому персонажу:")
    active_creations[callback.from_user.id] = {"step": "waiting_moons"}
    await callback.answer()

# Обработка текстовых сообщений
@dp.message(F.text)
async def process_text_messages(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in active_creations and active_creations[user_id].get("step") == "waiting_moons":
        if not message.text.isdigit():
            return await message.answer("Пожалуйста, введи возраст числом (например: 12):")
        
        moons = int(message.text)
        points = get_points(moons)
        
        active_creations[user_id] = {
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
        await message.answer(text, reply_markup=get_main_keyboard(active_creations[user_id]))
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
        [InlineKeyboardButton(text="💾 Сохранить анкету", callback_data="save_character")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="go_home")]
    ])

@dp.callback_query(F.data.in_(["cat_general", "cat_combat", "cat_senses", "cat_discussed"]))
async def open_category(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in active_creations or active_creations[user_id].get("step") != "distributing":
        return await callback.answer("Сначала начни создание персонажа через главное меню!", show_alert=True)
    
    cat_key = callback.data.replace("cat_", "")
    await update_category_menu(callback, cat_key)
    await callback.answer()

async def update_category_menu(callback: types.CallbackQuery, cat_key: str):
    user_id = callback.from_user.id
    data = active_creations[user_id]
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
    
    kb.append([InlineKeyboardButton(text="🔙 Назад к распределению", callback_data="back_to_distrib")])

    display_title = "⚔️ Боёвка (техники)" if cat_key == "combat" else cat_info['title']
    text = f"{display_title}\n{remains_text}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("plus:") | F.data.startswith("minus:"))
async def change_trait(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in active_creations:
        return await callback.answer("Данные не найдены!", show_alert=True)

    parts = callback.data.split(":")
    action = parts[0]
    cat_key = parts[1]
    trait_id = parts[2]

    data = active_creations[user_id]
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
    if user_id not in active_creations:
        return await callback.answer("Данные не найдены!", show_alert=True)
        
    moons = active_creations[user_id]["moons"]
    text = f"🌙 Возраст: {moons} лун\n\nВыбери категорию для распределения очков:"
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(active_creations[user_id]))

# --- СОХРАНЕНИЕ АНКЕТЫ В БД ---
@dp.callback_query(F.data == "save_character")
async def save_character(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in active_creations:
        return await callback.answer("Нет активной анкеты для сохранения!", show_alert=True)

    data = active_creations[user_id]
    moons = data["moons"]
    traits = data["traits"]

    template_text = f"📋 **Характеристики персонажа**\n🌙 Возраст: {moons} лун\n\n"

    template_text += "Общие\n"
    for trait_id, val in traits["general"].items():
        name = CATEGORIES_INFO["general"]["traits"][trait_id]
        template_text += f"• {name} {val}/10\n"
    template_text += "\n"

    template_text += "Здоровье\n"
    for trait_id, val in traits["senses"].items():
        name = CATEGORIES_INFO["senses"]["traits"][trait_id]
        template_text += f"• {name} {val}/10\n"
    template_text += "\n"

    template_text += "Бой и охота\n"
    for trait_id, val in traits["combat"].items():
        name = CATEGORIES_INFO["combat"]["traits"][trait_id]
        template_text += f"• Техника {name} {val}/10\n"
    template_text += "\n"

    template_text += "Травничество\n"
    template_text += f"• Знание трав {traits['discussed']['d_herbs']}/10\n"
    template_text += f"• Навык лечения {traits['discussed']['d_heal']}/10\n\n"

    template_text += "Уникальные навыки\n"
    template_text += f"• Разговор с иными видами {traits['discussed']['d_talk']}/10"

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO characters (user_id, moons, name, traits) VALUES (?, ?, ?, ?)",
        (user_id, moons, f"Персонаж ({moons} лун)", template_text)
    )
    conn.commit()
    conn.close()

    del active_creations[user_id]

    await callback.message.edit_text(
        "✅ Анкета успешно сохранена!\nТы можешь найти её в разделе «Посмотреть мои анкеты».",
        reply_markup=get_home_keyboard()
    )
    await callback.answer()

# --- ПРОСМОТР СОХРАНЕННЫХ АНКЕТ ---
@dp.callback_query(F.data == "my_characters")
async def show_my_characters(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM characters WHERE user_id = ?", (user_id,))
    chars = cursor.fetchall()
    conn.close()

    if not chars:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="go_home")]
        ])
        return await callback.message.edit_text("📂 У тебя пока нет сохраненных анкет.", reply_markup=kb)

    kb = []
    for char_id, char_name in chars:
        kb.append([InlineKeyboardButton(text=char_name, callback_data=f"view_char:{char_id}")])
    
    kb.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="go_home")])

    await callback.message.edit_text("📂 Твои сохраненные анкеты (нажми, чтобы посмотреть):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("view_char:"))
async def view_single_character(callback: types.CallbackQuery):
    char_id = int(callback.data.split(":")[1])

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT traits FROM characters WHERE id = ?", (char_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return await callback.answer("Анкета не найдена!", show_alert=True)

    template_text = row[0]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data=f"del_char:{char_id}")],
        [InlineKeyboardButton(text="📂 К списку анкет", callback_data="my_characters")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="go_home")]
    ])

    await callback.message.edit_text(template_text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("del_char:"))
async def delete_character(callback: types.CallbackQuery):
    char_id = int(callback.data.split(":")[1])

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM characters WHERE id = ?", (char_id,))
    conn.commit()
    conn.close()

    await callback.answer("Анкета удалена!", show_alert=True)
    await show_my_characters(callback)

async def main():
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
