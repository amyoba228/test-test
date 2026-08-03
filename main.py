import asyncio
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Токен берется из переменных окружения хостинга
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Не найден токен бота! Укажите переменную окружения BOT_TOKEN.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Сюда вставьте правильный ID группы после того, как узнаете его через команду /myid
MODERATOR_CHAT_ID = -1004456272439  

# --- РАБОТА С БАЗОЙ ДАННЫХ SQLite ---
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            text_content TEXT,
            status TEXT DEFAULT 'pending',
            mod_message_id INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Временное хранилище для процесса отправки анкеты
active_sessions = {}

# --- КЛАВИАТУРЫ ---
def get_home_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Отправить анкету на проверку", callback_data="start_submit")]
    ])

# --- КОМАНДА СТАРТ И ГЛАВНОЕ МЕНЮ ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != "private":
        return await message.answer("Этот бот принимает анкеты только в личных сообщениях!")
    
    text = "Привет! Это бот для отправки анкет на проверку анкетологам.\n\nНажми кнопку ниже, чтобы отправить свою анкету:"
    await message.answer(text, reply_markup=get_home_keyboard())

@dp.callback_query(F.data == "go_home")
async def go_home(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in active_sessions:
        del active_sessions[user_id]
    
    text = "Главное меню:"
    await callback.message.edit_text(text, reply_markup=get_home_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "start_submit")
async def start_submit(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "✍️ Пожалуйста, отправь текст своей готовой анкеты **одним сообщением** (имя, возраст, описание и т.д.):"
    )
    active_sessions[callback.from_user.id] = {"step": "waiting_ticket_text"}
    await callback.answer()

# --- КОМАНДА /myid (УЗНАТЬ АЙДИ ЧАТА) ---
@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"📌 ID этого чата: `{message.chat.id}`")

# --- КОМАНДА /list ДЛЯ АНКЕТОЛОГОВ ---
@dp.message(Command("list"))
async def mod_list_tickets(message: types.Message):
    if message.chat.id != MODERATOR_CHAT_ID:
        return

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM tickets WHERE status = 'pending'")
    tickets = cursor.fetchall()
    conn.close()

    if not tickets:
        return await message.answer("📂 На данный момент нет непроверенных анкет.")

    text = "📋 **Список анкет на проверку:**\n"
    for t_id, uname in tickets:
        text += f"• Тикет #{t_id} — Игрок: {uname}\n"
    
    await message.answer(text)

# --- ЗАКРЫТИЕ ТИКЕТА КНОПКОЙ ---
@dp.callback_query(F.data.startswith("close_ticket:"))
async def close_ticket(callback: types.CallbackQuery):
    ticket_id = int(callback.data.split(":")[1])

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()

    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n❌ **[ТИКЕТ ЗАКРЫТ]**", 
            reply_markup=None
        )
    except Exception:
        pass

    await callback.answer("Тикет успешно закрыт!", show_alert=True)

# --- ОБРАБОТКА РЕПЛАЯ АНКЕТОЛОГОВ (ОТВЕТ ИГРОКУ) ---
@dp.message(F.reply_to_message)
async def handle_mod_reply(message: types.Message):
    if message.chat.id != MODERATOR_CHAT_ID or message.from_user.is_bot:
        return

    replied_msg_id = message.reply_to_message.message_id

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, id FROM tickets WHERE mod_message_id = ?", (replied_msg_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return await message.reply("⚠️ Не удалось найти тикет, привязанный к этому сообщению.")

    user_id, ticket_id = row
    admin_answer = message.text

    try:
        await bot.send_message(
            user_id,
            f"📬 **Ответ от анкетологов по вашей анкете (Тикет #{ticket_id}):**\n\n{admin_answer}"
        )
        await message.reply("✅ Ответ успешно доставлен игроку!")
    except Exception as e:
        await message.reply(f"⚠️ Не удалось отправить сообщение игроку (возможно, он заблокировал бота). Ошибка: {e}")

# --- ЛОВИМ ТЕКСТ АНКЕТЫ ОТ ИГРОКА (ТОЛЬКО В ЛИЧКЕ) ---
@dp.message(F.text & ~F.text.startswith("/"))
async def process_user_text(message: types.Message):
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    
    if user_id not in active_sessions or active_sessions.get(user_id, {}).get("step") != "waiting_ticket_text":
        return

    ticket_text = message.text
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tickets (user_id, username, text_content, status) VALUES (?, ?, ?, 'pending')",
        (user_id, username, ticket_text)
    )
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()

    del active_sessions[user_id]

    mod_text = (
        f"📥 **Новая анкета на проверку!** (Тикет #{ticket_id})\n"
        f"👤 От: {username} (ID: `{user_id}`)\n\n"
        f"{ticket_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть тикет", callback_data=f"close_ticket:{ticket_id}")]
    ])

    try:
        sent_msg = await bot.send_message(MODERATOR_CHAT_ID, mod_text, reply_markup=kb)
        
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE tickets SET mod_message_id = ? WHERE id = ?", (sent_msg.message_id, ticket_id))
        conn.commit()
        conn.close()

    except Exception as e:
        print(f"❌ ОШИБКА ОТПРАВКИ В ЧАТ МОДЕРАТОРОВ: {repr(e)}")
        return await message.answer(f"⚠️ Ошибка отправки модераторам: {e}")

    await message.answer(
        "✅ Твоя анкета успешно отправлена анкетологам на проверку!\nОжидай ответа.",
        reply_markup=get_home_keyboard()
    )


async def main():
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
