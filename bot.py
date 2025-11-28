import aiosqlite
import asyncio
import os
import stat
import re
import time
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.client.default import DefaultBotProperties

# Состояния для анкеты
class ProfileStates(StatesGroup):
    waiting_name = State()
    waiting_role = State()
    waiting_age = State()
    waiting_city = State()
    waiting_bio = State()
    waiting_photo = State()

# Токен бота
BOT_TOKEN = "8240552495:AAF-g-RGQKzxIGuXs5PQZwf1Asp6hIJ93U4"

# ID администратора
ADMIN_ID = 7788888499

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())

# Глобальное соединение с БД
db = None

# Защита от флуда
user_cooldowns = defaultdict(dict)
SPAM_LIMIT = 5
SPAM_WINDOW = 10
BAN_DURATION = 3600

# Фильтр нецензурной лексики
BAD_WORDS = ['мат1', 'мат2', 'оскорбление']  # добавьте нужные слова

# Основное меню кнопок
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Создать анкету"), KeyboardButton(text="👤 Моя анкета")],
        [KeyboardButton(text="🔍 Найти анкеты"), KeyboardButton(text="ℹ️ Помощь")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие..."
)

# Меню отмены
cancel_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# Функции защиты
def contains_bad_words(text):
    text_lower = text.lower()
    return any(bad_word in text_lower for bad_word in BAD_WORDS)

def is_spamming(user_id):
    now = time.time()
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {'messages': [], 'banned_until': 0}
    
    user_data = user_cooldowns[user_id]
    
    # Проверка бана
    if user_data['banned_until'] > now:
        return True
    
    # Очистка старых сообщений
    user_data['messages'] = [msg_time for msg_time in user_data['messages'] 
                           if now - msg_time < SPAM_WINDOW]
    
    # Проверка лимита
    if len(user_data['messages']) >= SPAM_LIMIT:
        user_data['banned_until'] = now + BAN_DURATION
        return True
    
    user_data['messages'].append(now)
    return False

# Валидация данных
def validate_name(name):
    if len(name) < 2 or len(name) > 50:
        return False, "Имя должно быть от 2 до 50 символов"
    
    if not re.match(r'^[a-zA-Zа-яА-ЯёЁ\s\-]+$', name):
        return False, "Имя может содержать только буквы, пробелы и дефисы"
    
    return True, ""

def validate_age(age):
    if age < 12 or age > 100:
        return False, "Возраст должен быть от 12 до 100 лет"
    return True, ""

def validate_city(city):
    if len(city) < 2 or len(city) > 50:
        return False, "Название города должно быть от 2 до 50 символов"
    return True, ""

def validate_bio(bio):
    if len(bio) < 10:
        return False, "Расскажите о себе подробнее (минимум 10 символов)"
    if len(bio) > 1000:
        return False, "Слишком длинный текст (максимум 1000 символов)"
    
    if contains_bad_words(bio):
        return False, "Текст содержит запрещенные слова"
    
    return True, ""

# Middleware для защиты
@dp.message.middleware
async def protection_middleware(handler, event: types.Message, data):
    user_id = event.from_user.id
    
    # Проверка на спам
    if is_spamming(user_id):
        await event.answer("🚫 Слишком много запросов. Попробуйте позже.")
        return
    
    # Проверка бана
    if await is_user_banned(user_id):
        await event.answer("🚫 Ваш аккаунт заблокирован.")
        return
    
    return await handler(event, data)

# Проверка прав доступа к БД
async def ensure_db_permissions():
    if os.path.exists('flood.db'):
        os.chmod('flood.db', stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
        print("✅ Права доступа к БД установлены")

# Проверка является ли пользователь администратором
def is_admin(user_id):
    return user_id == ADMIN_ID

# Проверка заблокирован ли пользователь
async def is_user_banned(user_id):
    try:
        cursor = await db.execute(
            "SELECT 1 FROM banned_users WHERE user_id = ? AND (expires_at IS NULL OR expires_at > datetime('now'))",
            (user_id,)
        )
        return await cursor.fetchone() is not None
    except Exception as e:
        print(f"❌ Ошибка проверки бана: {e}")
        return False

# Инициализация базы данных
async def init_db():
    global db
    await ensure_db_permissions()
    
    db = await aiosqlite.connect('flood.db')
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")
    
    # Основная таблица анкет
    await db.execute("""
        CREATE TABLE IF NOT EXISTS flood (
            users_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            age INTEGER NOT NULL,
            city TEXT NOT NULL,
            bio TEXT NOT NULL,
            photo TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица для жалоб
    await db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            reported_user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reported_user_id) REFERENCES flood (users_id)
        )
    """)
    
    # Таблица для блокировок
    await db.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL,
            banned_by INTEGER NOT NULL,
            banned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME
        )
    """)
    
    await db.commit()
    print("✅ База данных инициализирована")

# Функция для сохранения профиля
async def save_profile(user_id, full_name, username, name, role, age, city, bio, photo):
    try:
        cursor = await db.execute("SELECT users_id FROM flood WHERE users_id = ?", (user_id,))
        existing_user = await cursor.fetchone()
        
        if existing_user:
            await db.execute("""
                UPDATE flood SET 
                full_name = ?, username = ?, name = ?, role = ?, age = ?, city = ?, bio = ?, photo = ?, updated_at = CURRENT_TIMESTAMP
                WHERE users_id = ?
            """, (full_name, username, name, role, age, city, bio, photo, user_id))
            action = "обновлена"
        else:
            await db.execute("""
                INSERT INTO flood 
                (users_id, full_name, username, name, role, age, city, bio, photo) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, full_name, username, name, role, age, city, bio, photo))
            action = "создана"
        
        await db.commit()
        return True, action
        
    except Exception as e:
        print(f"❌ Ошибка сохранения для user_id {user_id}: {e}")
        return False, str(e)

# Команда /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
    welcome_text = (
        "👋 Привет! Я бот для создания и поиска анкет.\n\n"
        "📝 <b>Создать анкету</b> - заполните информацию о себе\n"
        "👤 <b>Моя анкета</b> - посмотреть свою анкету\n"
        "🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей\n"
        "ℹ️ <b>Помощь</b> - показать это сообщение\n\n"
        "Выберите действие на клавиатуре ниже 👇"
    )
    await message.answer(welcome_text, reply_markup=main_menu)

# Команда /help
@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Помощь")
async def help_command(message: types.Message):
    help_text = (
        "📋 <b>Доступные команды:</b>\n\n"
        "📝 <b>Создать анкету</b> - заполните информацию о себе\n"
        "👤 <b>Моя анкета</b> - посмотреть свою анкету\n"
        "🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей\n\n"
        "Также вы можете использовать команды:\n"
        "/start - главное меню\n"
        "/help - эта справка\n"
        "/delete - удалить свою анкету\n"
        "/report - пожаловаться на пользователя (ответьте на его сообщение)\n"
        "/debug - отладочная информация (только для админа)\n"
        "/stats - статистика (только для админа)"
    )
    await message.answer(help_text, reply_markup=main_menu)

# Команда для отладки
@dp.message(Command("debug"))
async def debug_profiles(message: types.Message):
    if not is_admin(message.from_user.id):
        if message.chat.type == "private":
            await message.answer("❌ У вас нет прав доступа к этой команде.")
        return
    
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM flood")
        count = await cursor.fetchone()
        
        cursor = await db.execute("SELECT users_id, name, role, age, city FROM flood ORDER BY created_at DESC")
        profiles = await cursor.fetchall()
        
        result = f"📊 <b>Статистика базы данных</b>\n\n"
        result += f"📈 Всего анкет: <b>{count[0]}</b>\n\n"
        
        if profiles:
            result += "<b>📋 Список анкет:</b>\n"
            result += "─" * 40 + "\n"
            
            for i, (user_id, name, role, age, city) in enumerate(profiles, 1):
                result += f"#{i:02d} │ ID: {user_id}\n"
                result += f"    │ 👤 {name}\n"
                result += f"    │ 🎭 {role}\n"
                result += f"    │ 🎂 {age} лет │ 🏙️ {city}\n"
                
                if i < len(profiles):
                    result += "    ├" + "─" * 38 + "\n"
                else:
                    result += "    └" + "─" * 38 + "\n"
                    
        else:
            result += "📭 Анкет нет в базе данных"
            
        await message.answer(f"<pre>{result}</pre>")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении данных: {e}")

# Кнопка "Создать анкету"
@dp.message(F.text == "📝 Создать анкету")
async def start_anketa(message: types.Message, state: FSMContext):
    await message.answer(
        "📝 Давайте создадим вашу анкету!\n\n"
        "Как вас зовут? (Имя и фамилия)",
        reply_markup=cancel_menu
    )
    await state.set_state(ProfileStates.waiting_name)

# Обработчик отмены
@dp.message(F.text == "❌ Отмена")
async def cancel_anketa(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Заполнение анкеты отменено", reply_markup=main_menu)

# Шаг 1: Имя
@dp.message(ProfileStates.waiting_name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    
    is_valid, error_msg = validate_name(name)
    if not is_valid:
        await message.answer(f"❌ {error_msg} Попробуйте еще раз:")
        return
    
    await state.update_data(name=name)
    await message.answer(
        "🎭 Напишите вашу роль:",
        reply_markup=cancel_menu
    )
    await state.set_state(ProfileStates.waiting_role)

# Шаг 2: Роль
@dp.message(ProfileStates.waiting_role, F.text)
async def process_role(message: types.Message, state: FSMContext):
    role = message.text.strip()
    
    if role == "❌ Отмена":
        await cancel_anketa(message, state)
        return
        
    if len(role) < 2:
        await message.answer("Роль должна содержать минимум 2 символа. Попробуйте еще раз:")
        return
    
    await state.update_data(role=role)
    await message.answer("Сколько вам лет?", reply_markup=cancel_menu)
    await state.set_state(ProfileStates.waiting_age)

# Шаг 3: Возраст
@dp.message(ProfileStates.waiting_age, F.text)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите число:")
        return
    
    age = int(message.text)
    
    is_valid, error_msg = validate_age(age)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    
    await state.update_data(age=age)
    await message.answer("Из какого вы города?")
    await state.set_state(ProfileStates.waiting_city)

# Шаг 4: Город
@dp.message(ProfileStates.waiting_city, F.text)
async def process_city(message: types.Message, state: FSMContext):
    city = message.text.strip()
    
    is_valid, error_msg = validate_city(city)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    
    await state.update_data(city=city)
    await message.answer("Расскажите о себе (интересы, хобби, увлечения и т.д.):")
    await state.set_state(ProfileStates.waiting_bio)

# Шаг 5: О себе
@dp.message(ProfileStates.waiting_bio, F.text)
async def process_bio(message: types.Message, state: FSMContext):
    bio = message.text.strip()
    
    is_valid, error_msg = validate_bio(bio)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    
    await state.update_data(bio=bio)
    await message.answer("📸 Отлично! Теперь отправьте ваше фото:")
    await state.set_state(ProfileStates.waiting_photo)

# Шаг 6: Фото и сохранение
@dp.message(ProfileStates.waiting_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        photo = message.photo[-1]
        photo_file_id = photo.file_id
        
        success, action = await save_profile(
            message.from_user.id,
            message.from_user.full_name,
            message.from_user.username,
            user_data['name'],
            user_data['role'],
            user_data['age'],
            user_data['city'],
            user_data['bio'],
            photo_file_id
        )
        
        if success:
            await message.answer_photo(
                photo=photo_file_id,
                caption=f"✅ Анкета успешно {action}!\n\n"
                       f"👤 <b>Имя:</b> {user_data['name']}\n"
                       f"🎭 <b>Роль:</b> {user_data['role']}\n"
                       f"🎂 <b>Возраст:</b> {user_data['age']}\n"
                       f"🏙️ <b>Город:</b> {user_data['city']}\n"
                       f"📝 <b>О себе:</b> {user_data['bio']}",
                reply_markup=main_menu
            )
            await state.clear()
        else:
            await message.answer(f"❌ Ошибка: {action}", reply_markup=main_menu)
            await state.clear()
        
    except Exception as e:
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=main_menu)
        await state.clear()

# Если пользователь в состоянии ожидания фото, но отправил не фото
@dp.message(ProfileStates.waiting_photo)
async def process_photo_invalid(message: types.Message, state: FSMContext):
    await message.answer("📸 Пожалуйста, отправьте фото для анкеты:")

# Просмотр своей анкеты
@dp.message(F.text == "👤 Моя анкета")
@dp.message(Command("myprofile"))
async def show_profile(message: types.Message):
    try:
        cursor = await db.execute("SELECT * FROM flood WHERE users_id = ?", (message.from_user.id,))
        profile = await cursor.fetchone()
        
        if profile:
            users_id, full_name, username, name, role, age, city, bio, photo, is_active, created_at, updated_at = profile
            await message.answer_photo(
                photo=photo,
                caption=f"📋 <b>Ваша анкета:</b>\n\n"
                       f"👤 <b>Имя:</b> {name}\n"
                       f"🎭 <b>Роль:</b> {role}\n"
                       f"🎂 <b>Возраст:</b> {age}\n"
                       f"🏙️ <b>Город:</b> {city}\n"
                       f"📝 <b>О себе:</b> {bio}",
                reply_markup=main_menu
            )
        else:
            await message.answer("У вас нет анкеты. Создайте её!", reply_markup=main_menu)
            
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# Поиск анкет
@dp.message(F.text == "🔍 Найти анкеты")
@dp.message(Command("search"))
async def search_profiles(message: types.Message):
    try:
        cursor = await db.execute(
            "SELECT name, role, age, city, bio, photo FROM flood WHERE users_id != ? AND is_active = 1 LIMIT 3",
            (message.from_user.id,)
        )
        profiles = await cursor.fetchall()
        
        if profiles:
            for name, role, age, city, bio, photo in profiles:
                bio_preview = bio[:100] + "..." if len(bio) > 100 else bio
                caption = (
                    f"🔍 <b>Найдена анкета:</b>\n\n"
                    f"👤 <b>Имя:</b> {name}\n"
                    f"🎭 <b>Роль:</b> {role}\n" 
                    f"🎂 <b>Возраст:</b> {age}\n"
                    f"🏙️ <b>Город:</b> {city}\n"
                    f"📝 <b>О себе:</b> {bio_preview}"
                )
                await message.answer_photo(photo=photo, caption=caption)
        else:
            await message.answer("Пока нет других анкет.", reply_markup=main_menu)
            
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# Команда для жалобы на анкету
@dp.message(Command("report"))
async def report_user(message: types.Message):
    try:
        # Получаем ID пользователя из ответа на сообщение
        if not message.reply_to_message:
            await message.answer("❌ Ответьте на сообщение пользователя, на которого хотите пожаловаться")
            return
        
        reported_user_id = message.reply_to_message.from_user.id
        
        # Проверяем существует ли анкета
        cursor = await db.execute("SELECT 1 FROM flood WHERE users_id = ?", (reported_user_id,))
        if not await cursor.fetchone():
            await message.answer("❌ У этого пользователя нет анкеты")
            return
        
        # Сохраняем жалобу
        reason = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else "Не указана"
        await db.execute(
            "INSERT INTO reports (reporter_id, reported_user_id, reason) VALUES (?, ?, ?)",
            (message.from_user.id, reported_user_id, reason)
        )
        await db.commit()
        
        # Уведомляем админа
        await bot.send_message(
            ADMIN_ID,
            f"🚨 Новая жалоба!\n"
            f"👤 От: {message.from_user.id}\n"
            f"⚠️ На: {reported_user_id}\n"
            f"📝 Причина: {reason}"
        )
        
        await message.answer("✅ Жалоба отправлена администратору")
        
    except Exception as e:
        await message.answer("❌ Ошибка при отправке жалобы")

# Команда для бана пользователя (только админ)
@dp.message(Command("ban"))
async def ban_user(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("❌ Использование: /ban <user_id> <причина>")
            return
        
        user_id = int(parts[1])
        reason = parts[2]
        
        await db.execute(
            "INSERT OR REPLACE INTO banned_users (user_id, reason, banned_by) VALUES (?, ?, ?)",
            (user_id, reason, message.from_user.id)
        )
        await db.commit()
        
        await message.answer(f"✅ Пользователь {user_id} заблокирован")
        
        # Уведомляем забаненного
        try:
            await bot.send_message(user_id, f"🚫 Ваш аккаунт заблокирован. Причина: {reason}")
        except:
            pass
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# Команда для разбана
@dp.message(Command("unban"))
async def unban_user(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.text.split()[1])
        
        await db.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        await db.commit()
        
        await message.answer(f"✅ Пользователь {user_id} разблокирован")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# Команда для удаления своей анкеты
@dp.message(Command("delete"))
async def delete_profile(message: types.Message):
    try:
        await db.execute("DELETE FROM flood WHERE users_id = ?", (message.from_user.id,))
        await db.commit()
        await message.answer("✅ Ваша анкета удалена", reply_markup=main_menu)
    except Exception as e:
        await message.answer("❌ Ошибка при удалении анкеты")

# Статистика для админа
@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM flood")
        total_profiles = await cursor.fetchone()
        
        cursor = await db.execute("SELECT COUNT(*) FROM banned_users")
        banned_users = await cursor.fetchone()
        
        cursor = await db.execute("SELECT COUNT(*) FROM reports")
        total_reports = await cursor.fetchone()
        
        stats_text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👤 Всего анкет: {total_profiles[0]}\n"
            f"🚫 Заблокировано: {banned_users[0]}\n"
            f"⚠️ Жалоб: {total_reports[0]}\n"
            f"🕒 Время работы: {time.ctime()}"
        )
        
        await message.answer(stats_text)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# Обработчик других сообщений - ТОЛЬКО когда пользователь не в состоянии
@dp.message()
async def other_messages(message: types.Message):
    if message.chat.type != "private":
        return
        
    # Получаем текущее состояние пользователя
    current_state = await dp.current_state(user=message.from_user.id).get_state()
    
    # Если пользователь не в состоянии - показываем меню
    if current_state is None:
        await message.answer("Используйте кнопки меню для навигации", reply_markup=main_menu)

# Запуск бота
async def main():
    await init_db()
    print("🤖 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())