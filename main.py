import asyncio
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

# Токен берется из переменных окружения хостинга
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Не найден токен бота! Укажите переменную окружения BOT_TOKEN.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ID чата анкетологов (в кавычках)
MODERATOR_CHAT_ID = "-1004456272439"  

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

# Временное хранилище для сбора анкет (текст + фото)
active_sessions = {}

# --- КЛАВИАТУРЫ ---
def get_home_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Отправить анкету на проверку", callback_data="start_submit")]
    ])

def get_finish_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Всё, отправить анкету", callback_data="finish_submit")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="go_home")]
    ])

# --- КОМАНДА СТАРТ И ГЛАВНОЕ МЕНЮ ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != "private":
        return await message.answer("Этот бот принимает анкеты только в личных сообщениях!")
    
    text = "Привет! Это бот для отправки анкет на проверку анкетологам.\n\nНажми кнопку ниже, чтобы начать заполнение:"
    await message.answer(text, reply_markup=get_home_keyboard())

@dp.callback_query(F.data == "go_home")
async def go_home(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in active_sessions:
        del active_sessions[user_id]
    
    text = "Главное меню:"
    try:
        await callback.message.edit_text(text, reply_markup=get_home_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_home_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "start_submit")
async def start_submit(callback: types.CallbackQuery):
    active_sessions[callback.from_user.id] = {"step": "collecting", "messages": [], "photos": []}
    await callback.message.edit_text(
        "✍️ Отправляй свою анкету **любым количеством текстовых сообщений** и прикрепляй **до 3 фотографий** (по одной или с текстом).\n\n"
        "Когда закончишь отправлять всё, нажми кнопку ниже:",
        reply_markup=get_finish_keyboard()
    )
    await callback.answer()

# --- КОМАНДА /myid (УЗНАТЬ АЙДИ ЧАТА) ---
@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"📌 ID этого чата: `{message.chat.id}`")

# --- КОМАНДА /list ДЛЯ АНКЕТОЛОГОВ (С КНОПКАМИ ДО 5 ШТУК) ---
@dp.message(Command("list"))
async def mod_list_tickets(message: types.Message):
    if str(message.chat.id) != str(MODERATOR_CHAT_ID):
        return

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM tickets WHERE status = 'pending' LIMIT 5")
    tickets = cursor.fetchall()
    conn.close()

    if not tickets:
        return await message.answer("📂 На данный момент нет непроверенных анкет.")

    text = "📋 **Список анкет на проверку (первые 5):**\nНажми на кнопку ниже, чтобы открыть анкету:"
    
    kb = []
    for t_id, uname in tickets:
        kb.append([InlineKeyboardButton(text=f"📌 Тикет #{t_id} ({uname})", callback_data=f"view_ticket:{t_id}")])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# --- ПРОСМОТР АНКЕТЫ ИЗ КНОПКИ В ЧАТЕ МОДЕРАТОРОВ ---
@dp.callback_query(F.data.startswith("view_ticket:"))
async def view_ticket_button(callback: types.CallbackQuery):
    if str(callback.message.chat.id) != str(MODERATOR_CHAT_ID):
        return

    ticket_id = int(callback.data.split(":")[1])

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, text_content, status FROM tickets WHERE id = ?", (ticket_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return await callback.answer("Тикет не найден или уже удален!", show_alert=True)

    user_id, username, text_content, status = row
    
    status_text = "🟢 Активен" if status == "pending" else "❌ Закрыт"
    response_text = (
        f"📄 **Информация по тикету #{ticket_id}**\n"
        f"👤 Игрок: {username} (ID: `{user_id}`)\n"
        f"Статус: {status_text}\n\n"
        f"__Текст анкеты:__\n{text_content}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть этот тикет", callback_data=f"close_ticket:{ticket_id}")]
    ])

    await callback.message.answer(response_text, reply_markup=kb)
    await callback.answer()

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
    if str(message.chat.id) != str(MODERATOR_CHAT_ID) or message.from_user.is_bot:
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

# --- СБОР ТЕКСТА АНКЕТЫ ОТ ИГРОКА ---
@dp.message(F.text & ~F.text.startswith("/"))
async def process_user_text(message: types.Message):
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    
    if user_id in active_sessions and active_sessions[user_id].get("step") == "collecting":
        active_sessions[user_id]["messages"].append(message.text)
        await message.answer("➕ Текст принят! Можешь отправить еще текст или фото, либо нажать кнопку отправки.", reply_markup=get_finish_keyboard())
        return

# --- СБОР ФОТОГРАФИЙ ОТ ИГРОКА (ДО 3 ШТУК) ---
@dp.message(F.photo)
async def process_user_photo(message: types.Message):
    if message.chat.type != "private":
        return

    user_id = message.from_user.id

    if user_id in active_sessions and active_sessions[user_id].get("step") == "collecting":
        session = active_sessions[user_id]
        
        if len(session["photos"]) >= 3:
            return await message.answer("⚠️ Можно загрузить максимум 3 фотографии!", reply_markup=get_finish_keyboard())
        
        # Берем фото в самом высоком разрешении
        photo_id = message.photo[-1].file_id
        session["photos"].append(photo_id)

        # Если к фотке была прикреплена подпись (текст), тоже сохраняем её
        if message.caption:
            session["messages"].append(message.caption)

        count = len(session["photos"])
        await message.answer(f"📸 Фото принято ({count}/3)! Можешь отправить еще фото/текст или нажать кнопку отправки.", reply_markup=get_finish_keyboard())
        return

# --- ФИНАЛ: ОТПРАВКА СОБРАННОЙ АНКЕТЫ И ФОТО МОДЕРАТОРАМ ---
@dp.callback_query(F.data == "finish_submit")
async def finish_submit(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_sessions:
        return await callback.answer("Сессия не найдена, начни заново.", show_alert=True)

    session = active_sessions[user_id]
    if not session["messages"] and not session["photos"]:
        return await callback.answer("Ты не отправил ни текста, ни фотографий!", show_alert=True)

    full_ticket_text = "\n\n".join(session["messages"]) if session["messages"] else "(Без текста)"
    photos = session["photos"]
    
    username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    # Сохраняем в базу данных
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tickets (user_id, username, text_content, status) VALUES (?, ?, ?, 'pending')",
        (user_id, username, full_ticket_text)
    )
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()

    del active_sessions[user_id]

    mod_text = (
        f"📥 **Новая анкета на проверку!** (Тикет #{ticket_id})\n"
        f"👤 От: {username} (ID: `{user_id}`)\n\n"
        f"{full_ticket_text}"
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

        # Если есть фотографии, отправляем их группой с подписью на первом фото
        if photos:
            media = []
            for i, p_id in enumerate(photos):
                if i == 0:
                    media.append(InputMediaPhoto(media=p_id, caption=f"🖼 Фотографии к тикету #{ticket_id}"))
                else:
                    media.append(InputMediaPhoto(media=p_id))
            
            await bot.send_media_group(MODERATOR_CHAT_ID, media=media)

    except Exception as e:
        print(f"❌ ОШИБКА ОТПРАВКИ В ЧАТ МОДЕРАТОРОВ: {repr(e)}")
        return await callback.message.edit_text(f"⚠️ Ошибка отправки модераторам: {e}")

    await callback.message.edit_text(
        "✅ Твоя анкета и фотографии успешно отправлены анкетологам на проверку!\nОжидай ответа.",
        reply_markup=get_home_keyboard()
    )
    await callback.answer()


async def main():
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
