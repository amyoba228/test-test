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
    # Таблица тикетов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            text_content TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    # Таблица связей сообщений с тикетами для двустороннего Reply
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_map (
            message_id INTEGER,
            chat_id INTEGER,
            ticket_id INTEGER,
            PRIMARY KEY (message_id, chat_id)
        )
    """)
    # Таблица забаненных пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            reason TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Временное хранилище для сбора новых анкет
active_sessions = {}

def map_message(message_id: int, chat_id: int, ticket_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO message_map (message_id, chat_id, ticket_id) VALUES (?, ?, ?)", (message_id, chat_id, ticket_id))
    conn.commit()
    conn.close()

def get_ticket_by_message(message_id: int, chat_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT ticket_id FROM message_map WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def is_user_banned(user_id: int) -> bool:
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

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

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ДЛИННЫХ СООБЩЕНИЙ ---
async def send_long_message(chat_id, text, reply_markup=None):
    max_length = 4000
    if len(text) <= max_length:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)
    
    chunks = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    sent_msg = None
    for idx, chunk in enumerate(chunks):
        markup = reply_markup if idx == len(chunks) - 1 else None
        sent_msg = await bot.send_message(chat_id, chunk, reply_markup=markup)
    return sent_msg

# --- КОМАНДА СТАРТ И ГЛАВНОЕ МЕНЮ ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != "private":
        return await message.answer("Этот бот принимает анкеты только в личных сообщениях!")
    
    user_id = message.from_user.id
    if is_user_banned(user_id):
        return await message.answer("❌ Вы заблокированы в этом боте и не можете отправлять анкеты.")
    
    text = "Привет! Это бот для отправки анкет на проверку анкетологам.\n\nНажми кнопку ниже, чтобы начать заполнение:"
    await message.answer(text, reply_markup=get_home_keyboard())

@dp.callback_query(F.data == "go_home")
async def go_home(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if is_user_banned(user_id):
        return await callback.answer("❌ Вы заблокированы.", show_alert=True)

    if user_id in active_sessions:
        del active_sessions[user_id]
    
    text = "Главное меню:"
    try:
        await callback.message.edit_text(text, reply_markup=get_home_keyboard())
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "start_submit")
async def start_submit(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if is_user_banned(user_id):
        return await callback.answer("❌ Вы заблокированы в этом боте.", show_alert=True)

    active_sessions[user_id] = {"step": "collecting", "messages": [], "photos": []}
    try:
        await callback.message.edit_text(
            "✍️ Отправляй свою анкету частями:\n"
            "• Текстовые сообщения\n"
            "• **Статьи Telegram** (ссылки на статьи)\n"
            "• **До 3 фотографий**\n\n"
            "Можешь отправлять их вперемешку. Когда закончишь, нажми кнопку ниже:",
            reply_markup=get_finish_keyboard()
        )
    except Exception:
        pass
    await callback.answer()

# --- КОМАНДА /myid ---
@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"📌 ID этого чата: `{message.chat.id}`")

# --- КОМАНДА /list ДЛЯ АНКЕТОЛОГОВ ---
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
        f"__Текст / статьи анкеты:__\n{text_content}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть этот тикет", callback_data=f"close_ticket:{ticket_id}")]
    ])

    sent_msg = await send_long_message(callback.message.chat.id, response_text, reply_markup=kb)
    if sent_msg:
        map_message(sent_msg.message_id, int(MODERATOR_CHAT_ID), ticket_id)

    await callback.answer()

# --- ЗАКРЫТИЕ ТИКЕТА КНОПКОЙ ---
@dp.callback_query(F.data.startswith("close_ticket:"))
async def close_ticket(callback: types.CallbackQuery):
    ticket_id = int(callback.data.split(":")[1])

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, status FROM tickets WHERE id = ?", (ticket_id,))
    row = cursor.fetchone()
    
    if row and row[1] == 'pending':
        user_id = row[0]
        cursor.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
        conn.commit()

        try:
            await bot.send_message(user_id, f"🔒 **Ваша анкета (Тикет #{ticket_id}) закрыта анкетологами.** Переписка завершена.")
        except Exception:
            pass

    conn.close()

    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n❌ **[ТИКЕТ ЗАКРЫТ]**", 
            reply_markup=None
        )
    except Exception:
        pass

    await callback.answer("Тикет успешно закрыт!", show_alert=True)


# --- КОМАНДЫ БАНА И РАЗБАНА (;бан / ;разбан) ---
@dp.message(F.text.startswith(";бан") & (F.chat.id == int(MODERATOR_CHAT_ID)))
async def cmd_ban(message: types.Message):
    parts = message.text.split(maxsplit=2)
    reason = parts[2] if len(parts) > 2 else "Причина не указана"
    target_user_id = None
    target_username = None

    # Способ 1: Реплаем на сообщение
    if message.reply_to_message:
        replied_msg_id = message.reply_to_message.message_id
        ticket_id = get_ticket_by_message(replied_msg_id, message.chat.id)
        if ticket_id:
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, username FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                target_user_id, target_username = row[0], row[1]
    
    # Способ 2: Через аргумент (@юзернейм или ID)
    elif len(parts) > 1:
        arg = parts[1]
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        if arg.startswith("@"):
            cursor.execute("SELECT user_id, username FROM tickets WHERE username = ? ORDER BY id DESC LIMIT 1", (arg,))
        elif arg.isdigit():
            target_user_id = int(arg)
            cursor.execute("SELECT username FROM tickets WHERE user_id = ? ORDER BY id DESC LIMIT 1", (target_user_id,))
            res = cursor.fetchone()
            target_username = res[0] if res else f"ID: {target_user_id}"
        
        row = cursor.fetchone() if arg.startswith("@") else None
        if row:
            target_user_id, target_username = row[0], row[1]
        conn.close()

    if not target_user_id:
        return await message.reply("⚠️ Не удалось определить пользователя. Укажите @юзернейм, ID или сделайте Reply на его тикет/сообщение.")

    # Заносим в базу забаненных
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO banned_users (user_id, username, reason) VALUES (?, ?, ?)", (target_user_id, str(target_username), reason))
    conn.commit()
    conn.close()

    # Закрываем активный тикет пользователя, если он был
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET status = 'closed' WHERE user_id = ? AND status = 'pending'", (target_user_id,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(target_user_id, f"❌ **Вы были заблокированы администрацией.**\nПричина: {reason}")
    except Exception:
        pass

    await message.reply(f"🔨 Пользователь `{target_username}` (ID: `{target_user_id}`) успешно заблокирован.\nПричина: {reason}")


@dp.message(F.text.startswith(";разбан") & (F.chat.id == int(MODERATOR_CHAT_ID)))
async def cmd_unban(message: types.Message):
    parts = message.text.split(maxsplit=1)
    target_user_id = None
    target_identifier = None

    if message.reply_to_message:
        replied_msg_id = message.reply_to_message.message_id
        ticket_id = get_ticket_by_message(replied_msg_id, message.chat.id)
        if ticket_id:
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                target_user_id = row[0]
    elif len(parts) > 1:
        arg = parts[1]
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        if arg.startswith("@"):
            cursor.execute("SELECT user_id FROM banned_users WHERE username = ?", (arg,))
            row = cursor.fetchone()
            if row:
                target_user_id = row[0]
        elif arg.isdigit():
            target_user_id = int(arg)
        conn.close()

    if not target_user_id:
        return await message.reply("⚠️ Не удалось определить пользователя для разбана. Укажите @юзернейм, ID или сделайте Reply.")

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (target_user_id,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(target_user_id, "✅ **Вы были разблокированы!** Теперь вы снова можете пользоваться ботом.")
    except Exception:
        pass

    await message.reply(f"🔓 Пользователь с ID `{target_user_id}` успешно разблокирован.")


# --- ДВУСТОРОННЯЯ ПЕРЕПИСКА ЧЕРЕЗ REPLY ---

@dp.message(F.reply_to_message & (F.chat.id == int(MODERATOR_CHAT_ID)))
async def handle_mod_reply(message: types.Message):
    if message.from_user.is_bot or message.text.startswith(";"):
        return

    replied_msg_id = message.reply_to_message.message_id
    ticket_id = get_ticket_by_message(replied_msg_id, message.chat.id)

    if not ticket_id:
        return await message.reply("⚠️ Не удалось найти тикет, привязанный к этому сообщению.")

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, status FROM tickets WHERE id = ?", (ticket_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or row[1] != 'pending':
        return await message.reply("⚠️ Этот тикет уже закрыт, переписка недоступна.")

    user_id = row[0]
    admin_answer = message.text

    try:
        sent_to_user = await bot.send_message(
            user_id,
            f"📬 **Ответ от анкетологов (Тикет #{ticket_id}):**\n\n{admin_answer}"
        )
        map_message(sent_to_user.message_id, user_id, ticket_id)
        map_message(message.message_id, int(MODERATOR_CHAT_ID), ticket_id)
        
        await message.reply("✅ Ответ успешно доставлен игроку!")
    except Exception as e:
        await message.reply(f"⚠️ Не удалось отправить сообщение игроку: {e}")


@dp.message(F.reply_to_message & F.chat.type.in_({"private"}))
async def handle_user_reply(message: types.Message):
    if message.from_user.is_bot or message.text.startswith("/"):
        return

    user_id = message.from_user.id
    if is_user_banned(user_id):
        return await message.answer("❌ Вы заблокированы в этом боте.")

    replied_msg_id = message.reply_to_message.message_id
    ticket_id = get_ticket_by_message(replied_msg_id, user_id)

    if not ticket_id:
        return

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM tickets WHERE id = ? AND user_id = ?", (ticket_id, user_id))
    row = cursor.fetchone()
    conn.close()

    if not row or row[0] != 'pending':
        return await message.answer("⚠️ Этот тикет уже закрыт. Отправка сообщений недоступна.")

    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    forward_text = f"💬 **Ответ от игрока {username}** (Тикет #{ticket_id}):\n\n{message.text}"

    try:
        sent_to_mod = await bot.send_message(MODERATOR_CHAT_ID, forward_text)
        map_message(sent_to_mod.message_id, int(MODERATOR_CHAT_ID), ticket_id)
        await message.answer("✅ Ваше сообщение отправлено анкетологам.")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка отправки модераторам: {e}")


@dp.message(F.text & ~F.text.startswith("/"))
async def process_user_text(message: types.Message):
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    if is_user_banned(user_id):
        return await message.answer("❌ Вы заблокированы в этом боте.")
    
    if user_id in active_sessions and active_sessions[user_id].get("step") == "collecting":
        active_sessions[user_id]["messages"].append(message.text)
        await message.answer("➕ Материал (текст / статья) успешно добавлен! Можешь отправить ещё или нажать кнопку отправки.", reply_markup=get_finish_keyboard())
        return

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND status = 'pending'", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        ticket_id = row[0]
        username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
        forward_text = f"💬 **Сообщение от игрока {username}** (Тикет #{ticket_id}):\n\n{message.text}"
        
        try:
            sent_to_mod = await bot.send_message(MODERATOR_CHAT_ID, forward_text)
            map_message(sent_to_mod.message_id, int(MODERATOR_CHAT_ID), ticket_id)
            await message.answer("✅ Ваше сообщение отправлено анкетологам.")
        except Exception as e:
            await message.answer(f"⚠️ Ошибка отправки сообщения модераторам: {e}")
        return

    await message.answer("Нажми кнопку ниже, чтобы отправить анкету:", reply_markup=get_home_keyboard())


@dp.message(F.photo)
async def process_user_photo(message: types.Message):
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    if is_user_banned(user_id):
        return await message.answer("❌ Вы заблокированы в этом боте.")

    if user_id in active_sessions and active_sessions[user_id].get("step") == "collecting":
        session = active_sessions[user_id]
        
        if len(session["photos"]) >= 3:
            return await message.answer("⚠️ Можно загрузить максимум 3 фотографии!", reply_markup=get_finish_keyboard())
        
        photo_id = message.photo[-1].file_id
        session["photos"].append(photo_id)

        if message.caption:
            session["messages"].append(message.caption)

        count = len(session["photos"])
        await message.answer(f"📸 Фото принято ({count}/3)! Можешь отправить еще материалы или нажать кнопку отправки.", reply_markup=get_finish_keyboard())
        return


@dp.callback_query(F.data == "finish_submit")
async def finish_submit(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if is_user_banned(user_id):
        return await callback.answer("❌ Вы заблокированы.", show_alert=True)
    
    if user_id not in active_sessions:
        return await callback.answer("Сессия не найдена, начни заново.", show_alert=True)

    session = active_sessions[user_id]
    if not session["messages"] and not session["photos"]:
        return await callback.answer("Ты не отправил ни текста, ни статей, ни фотографий!", show_alert=True)

    full_ticket_text = "\n\n".join(session["messages"]) if session["messages"] else "(Без текста и статей)"
    photos = session["photos"]
    
    username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

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
        f"📥 **Новая анкета / статья на проверку!** (Тикет #{ticket_id})\n"
        f"👤 От: {username} (ID: `{user_id}`)\n\n"
    
