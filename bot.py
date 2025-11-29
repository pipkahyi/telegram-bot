import asyncpg
import asyncio
import re
import time
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
from datetime import datetime, timedelta

# ===== КОНФИГУРАЦИЯ =====
class Config:
    # ИСПРАВЛЕННЫЕ НАСТРОЙКИ ИЗ ВАШЕГО СКРИНШОТА
    POSTGRES_CONFIG = {
        'user': 'neondb_owner',
        'password': 'npg_g9V7oqFCiZwY',  # Нажмите "Show password" чтобы увидеть реальный пароль
        'database': 'neondb',
        'host': 'ep-bold-sunset-ahlhp31q-pooler.c-3.us-east-1.aws.neon.tech',  # Точный хост из скриншота
        'port': 5432,
        'ssl': 'require'
    }

    # Токен бота
    BOT_TOKEN = "8240552495:AAF-g-RGQKzxIGuXs5PQZwf1Asp6hIJ93U4"
    
    # ID администратора и модераторов
    ADMIN_ID = 7788088499
    MODERATORS = [7788088499]  # список ID модераторов
    
    # Тип модерации: "group" или "private"
    MODERATION_TYPE = "private"
    
    # Защита от спама
    SPAM_LIMIT = 5
    SPAM_WINDOW = 10
    BAN_DURATION = 3600
    
    # Запрещенные слова
    BAD_WORDS = ['Котакбас', 'Секс', 'Порно', 'Дошан', 'Тошан', 'Котак', 'Еблан']
    
    # Лимиты для пользователей
    FREE_MAX_PROFILES = 1
    FREE_DAILY_SEARCHES = 5
    PREMIUM_MAX_PROFILES = 10

# ===== СОСТОЯНИЯ FSM =====
class ProfileStates(StatesGroup):
    waiting_name = State()
    waiting_role = State()
    waiting_age = State()
    waiting_city = State()
    waiting_bio = State()
    waiting_photo = State()

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
pool = None

# ===== СИСТЕМА ЗАЩИТЫ =====
user_cooldowns = defaultdict(dict)

def contains_bad_words(text):
    text_lower = text.lower()
    return any(bad_word in text_lower for bad_word in Config.BAD_WORDS)

def is_spamming(user_id):
    now = time.time()
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {'messages': [], 'banned_until': 0}
    
    user_data = user_cooldowns[user_id]
    
    if user_data['banned_until'] > now:
        return True
    
    user_data['messages'] = [msg_time for msg_time in user_data['messages'] 
                           if now - msg_time < Config.SPAM_WINDOW]
    
    if len(user_data['messages']) >= Config.SPAM_LIMIT:
        user_data['banned_until'] = now + Config.BAN_DURATION
        return True
    
    user_data['messages'].append(now)
    return False

# ===== ВАЛИДАЦИЯ ДАННЫХ =====
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

# ===== MIDDLEWARE ЗАЩИТЫ =====
@dp.message.middleware
async def protection_middleware(handler, event: types.Message, data):
    user_id = event.from_user.id
    
    if is_spamming(user_id):
        await event.answer("🚫 Слишком много запросов. Попробуйте позже.")
        return
    
    if await is_user_banned(user_id):
        await event.answer("🚫 Ваш аккаунт заблокирован.")
        return
    
    return await handler(event, data)

# ===== КЛАВИАТУРЫ =====
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Создать анкету"), KeyboardButton(text="👤 Моя анкета")],
        [KeyboardButton(text="🔍 Найти анкеты"), KeyboardButton(text="ℹ️ Помощь")],
        [KeyboardButton(text="💰 Тарифы"), KeyboardButton(text="📊 Статистика")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие..."
)

cancel_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# ===== БАЗА ДАННЫХ =====
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(**Config.POSTGRES_CONFIG)
        print("✅ Подключение к PostgreSQL установлено")
        
        async with pool.acquire() as conn:
            # Таблица профилей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    age INTEGER NOT NULL,
                    city TEXT NOT NULL,
                    bio TEXT NOT NULL,
                    photo TEXT,
                    status TEXT DEFAULT 'pending',
                    moderated_by BIGINT,
                    moderation_reason TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица жалоб
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    reporter_id BIGINT NOT NULL,
                    reported_user_id BIGINT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица банов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id BIGINT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    banned_by BIGINT NOT NULL,
                    banned_at TIMESTAMP DEFAULT NOW(),
                    expires_at TIMESTAMP
                )
            """)
            
            # Таблица активных модераций
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_moderations (
                    user_id BIGINT PRIMARY KEY,
                    moderator_id BIGINT NOT NULL,
                    taken_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица подписок
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id BIGINT PRIMARY KEY,
                    plan TEXT NOT NULL,
                    starts_at TIMESTAMP DEFAULT NOW(),
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица поисковых запросов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS search_usage (
                    user_id BIGINT,
                    search_date DATE DEFAULT CURRENT_DATE,
                    search_count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, search_date)
                )
            """)
            
            print("✅ Таблицы созданы/проверены")
            
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def is_admin(user_id):
    return user_id == Config.ADMIN_ID

def is_moderator(user_id):
    return user_id in Config.MODERATORS

async def is_user_banned(user_id):
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM banned_users WHERE user_id = $1 AND (expires_at IS NULL OR expires_at > NOW())",
                user_id
            )
            return row is not None
    except Exception as e:
        print(f"❌ Ошибка проверки бана: {e}")
        return False

async def check_user_limits(user_id):
    """Проверяет лимиты пользователя"""
    try:
        async with pool.acquire() as conn:
            # Проверяем подписку
            subscription = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE user_id = $1 AND expires_at > NOW()",
                user_id
            )
            
            is_premium = subscription is not None
            
            # Проверяем количество анкет
            profile_count = await conn.fetchval(
                "SELECT COUNT(*) FROM profiles WHERE user_id = $1",
                user_id
            )
            
            max_profiles = Config.PREMIUM_MAX_PROFILES if is_premium else Config.FREE_MAX_PROFILES
            
            return {
                'can_create': profile_count < max_profiles,
                'profiles_left': max_profiles - profile_count,
                'is_premium': is_premium,
                'max_profiles': max_profiles
            }
            
    except Exception as e:
        print(f"❌ Ошибка проверки лимитов: {e}")
        return {'can_create': False, 'profiles_left': 0, 'is_premium': False, 'max_profiles': 0}

async def check_search_limit(user_id):
    """Проверяет лимит поисковых запросов"""
    try:
        async with pool.acquire() as conn:
            # Проверяем подписку
            subscription = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE user_id = $1 AND expires_at > NOW()",
                user_id
            )
            
            if subscription:  # Премиум пользователи без лимитов
                return True, 0
                
            # Для бесплатных пользователей
            today = datetime.now().date()
            usage = await conn.fetchrow(
                "SELECT search_count FROM search_usage WHERE user_id = $1 AND search_date = $2",
                user_id, today
            )
            
            if not usage:
                return True, Config.FREE_DAILY_SEARCHES - 1
                
            searches_left = Config.FREE_DAILY_SEARCHES - usage['search_count']
            return searches_left > 0, searches_left
            
    except Exception as e:
        print(f"❌ Ошибка проверки лимита поиска: {e}")
        return False, 0

async def increment_search_count(user_id):
    """Увеличивает счетчик поисковых запросов"""
    try:
        async with pool.acquire() as conn:
            today = datetime.now().date()
            await conn.execute("""
                INSERT INTO search_usage (user_id, search_date, search_count) 
                VALUES ($1, $2, 1)
                ON CONFLICT (user_id, search_date) 
                DO UPDATE SET search_count = search_usage.search_count + 1
            """, user_id, today)
    except Exception as e:
        print(f"❌ Ошибка увеличения счетчика поиска: {e}")

async def save_profile(user_id, username, name, role, age, city, bio, photo):
    try:
        async with pool.acquire() as conn:
            existing_user = await conn.fetchrow(
                "SELECT user_id FROM profiles WHERE user_id = $1", 
                user_id
            )
            
            if existing_user:
                await conn.execute("""
                    UPDATE profiles SET 
                    username = $1, name = $2, role = $3, age = $4, city = $5, 
                    bio = $6, photo = $7, updated_at = NOW(), status = 'pending'
                    WHERE user_id = $8
                """, username, name, role, age, city, bio, photo, user_id)
                action = "обновлена"
            else:
                await conn.execute("""
                    INSERT INTO profiles 
                    (user_id, username, name, role, age, city, bio, photo) 
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, user_id, username, name, role, age, city, bio, photo)
                action = "создана"
            
            return True, action
            
    except Exception as e:
        print(f"❌ Ошибка сохранения для user_id {user_id}: {e}")
        return False, str(e)

async def notify_all_moderators(user_id, username, name, role, age, city, bio, photo):
    """Уведомляет всех модераторов о новой анкете"""
    try:
        moderation_text = (
            "🆕 <b>НОВАЯ АНКЕТА НА МОДЕРАЦИЮ</b>\n\n"
            f"👤 <b>ID:</b> <code>{user_id}</code>\n"
            f"📛 <b>Имя:</b> {name}\n"
            f"🔗 <b>Username:</b> @{username if username else 'нет'}\n"
            f"🎭 <b>Роль:</b> {role}\n"
            f"🎂 <b>Возраст:</b> {age}\n"
            f"🏙️ <b>Город:</b> {city}\n"
            f"📝 <b>О себе:</b> {bio}\n\n"
            f"⏰ <b>Время подачи:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        
        moderation_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{user_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}"),
             InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{user_id}")],
            [InlineKeyboardButton(text="👨‍💻 Взять в работу", callback_data=f"take_{user_id}")]
        ])
        
        success_count = 0
        for moderator_id in Config.MODERATORS:
            try:
                if photo:
                    await bot.send_photo(
                        chat_id=moderator_id,
                        photo=photo,
                        caption=moderation_text,
                        reply_markup=moderation_keyboard
                    )
                else:
                    await bot.send_message(
                        chat_id=moderator_id,
                        text=moderation_text,
                        reply_markup=moderation_keyboard
                    )
                success_count += 1
            except Exception as e:
                print(f"❌ Не удалось уведомить модератора {moderator_id}: {e}")
        
        return success_count > 0
        
    except Exception as e:
        print(f"❌ Ошибка отправки уведомлений модераторам: {e}")
        return False

# ===== КОМАНДЫ БОТА =====
@dp.message(Command("start"))
async def start_command(message: types.Message):
    welcome_text = (
        "👋 Привет! Я бот для создания и поиска анкет.\n\n"
        "📝 <b>Создать анкету</b> - заполните информацию о себе\n"
        "👤 <b>Моя анкета</b> - посмотреть свою анкету\n"
        "🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей\n"
        "💰 <b>Тарифы</b> - информация о премиум подписке\n"
        "📊 <b>Статистика</b> - статистика бота\n"
        "ℹ️ <b>Помощь</b> - показать это сообщение\n\n"
        "Выберите действие на клавиатуре ниже 👇"
    )
    await message.answer(welcome_text, reply_markup=main_menu)

@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Помощь")
async def help_command(message: types.Message):
    help_text = (
        "📋 <b>Доступные команды:</b>\n\n"
        "📝 <b>Создать анкету</b> - заполните информацию о себе\n"
        "👤 <b>Моя анкета</b> - посмотреть свою анкету\n"
        "🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей\n"
        "💰 <b>Тарифы</b> - информация о премиум подписке\n\n"
        "Также вы можете использовать команды:\n"
        "/start - главное меню\n"
        "/help - эта справка\n"
        "/delete - удалить свою анкету\n"
        "/report - пожаловаться на пользователя\n"
        "/list - список одобренных анкет\n"
        "/stats - статистика\n"
        "/buy - информация о покупке премиума"
    )
    await message.answer(help_text, reply_markup=main_menu)

@dp.message(Command("get_chat_id"))
async def get_chat_id(message: types.Message):
    chat_id = message.chat.id
    await message.answer(f"ID этого чата: <code>{chat_id}</code>")

# ===== СИСТЕМА ПОДПИСОК =====
@dp.message(Command("buy"))
@dp.message(F.text == "💰 Тарифы")
async def buy_premium(message: types.Message):
    pricing_text = """
💰 <b>Тарифы бота</b>

🎯 <b>Бесплатный тариф:</b>
• 1 анкета
• 5 поисков в день
• Базовая функциональность

💎 <b>Премиум подписка:</b>
• До 10 анкет
• Неограниченный поиск
• Приоритетная модерация
• Расширенная статистика

💵 <b>Стоимость:</b>
• 3,000 ₸ в месяц
• 7,500 ₸ за 3 месяца
• 25,000 ₸ за год

📞 <b>Для покупки:</b>
Свяжитесь с администратором: @ваш_аккаунт

💳 <b>Способы оплаты:</b>
• Kaspi Gold
• Банковский перевод
• ЮMoney
    """
    
    await message.answer(pricing_text, reply_markup=main_menu)

# ===== СОЗДАНИЕ АНКЕТЫ =====
@dp.message(F.text == "📝 Создать анкету")
async def start_anketa(message: types.Message, state: FSMContext):
    # Проверяем лимиты пользователя
    limits = await check_user_limits(message.from_user.id)
    
    if not limits['can_create']:
        if limits['is_premium']:
            await message.answer(
                f"❌ Вы достигли лимита анкет для премиум аккаунта ({limits['max_profiles']} анкет).\n"
                "Удалите одну из старых анкет чтобы создать новую."
            )
        else:
            await message.answer(
                f"❌ Вы достигли лимита бесплатных анкет (1 анкета).\n\n"
                "💎 <b>Премиум подписка</b> позволяет создавать до 10 анкет!\n"
                "Нажмите '💰 Тарифы' для получения информации.",
                reply_markup=main_menu
            )
        return

    await message.answer(
        "📝 Давайте создадим вашу анкету!\n\n"
        "Как вас зовут? (Имя и фамилия)",
        reply_markup=cancel_menu
    )
    await state.set_state(ProfileStates.waiting_name)

@dp.message(F.text == "❌ Отмена")
async def cancel_anketa(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Заполнение анкеты отменено", reply_markup=main_menu)

@dp.message(ProfileStates.waiting_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    is_valid, error_msg = validate_name(name)
    if not is_valid:
        await message.answer(f"❌ {error_msg} Попробуйте еще раз:")
        return
    await state.update_data(name=name)
    await message.answer("🎭 Напишите вашу роль:", reply_markup=cancel_menu)
    await state.set_state(ProfileStates.waiting_role)

@dp.message(ProfileStates.waiting_role)
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

@dp.message(ProfileStates.waiting_age)
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

@dp.message(ProfileStates.waiting_city)
async def process_city(message: types.Message, state: FSMContext):
    city = message.text.strip()
    is_valid, error_msg = validate_city(city)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    await state.update_data(city=city)
    await message.answer("Расскажите о себе (интересы, хобби, увлечения и т.д.):")
    await state.set_state(ProfileStates.waiting_bio)

@dp.message(ProfileStates.waiting_bio)
async def process_bio(message: types.Message, state: FSMContext):
    bio = message.text.strip()
    is_valid, error_msg = validate_bio(bio)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    await state.update_data(bio=bio)
    await message.answer("📸 Отлично! Теперь отправьте ваше фото:")
    await state.set_state(ProfileStates.waiting_photo)

@dp.message(ProfileStates.waiting_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        photo = message.photo[-1]
        photo_file_id = photo.file_id
        
        success, action = await save_profile(
            message.from_user.id,
            message.from_user.username,
            user_data['name'],
            user_data['role'],
            user_data['age'],
            user_data['city'],
            user_data['bio'],
            photo_file_id
        )
        
        if success:
            moderation_sent = await notify_all_moderators(
                message.from_user.id,
                message.from_user.username,
                user_data['name'],
                user_data['role'],
                user_data['age'],
                user_data['city'],
                user_data['bio'],
                photo_file_id
            )
            
            if moderation_sent:
                await message.answer_photo(
                    photo=photo_file_id,
                    caption=f"✅ Анкета успешно {action} и отправлена на модерацию!\n\n"
                           f"👤 <b>Имя:</b> {user_data['name']}\n"
                           f"🎭 <b>Роль:</b> {user_data['role']}\n"
                           f"🎂 <b>Возраст:</b> {user_data['age']}\n"
                           f"🏙️ <b>Город:</b> {user_data['city']}\n"
                           f"📝 <b>О себе:</b> {user_data['bio']}\n\n"
                           f"⏳ <i>Ожидайте решения модератора</i>",
                    reply_markup=main_menu
                )
            else:
                await message.answer("❌ Ошибка отправки на модерацию", reply_markup=main_menu)
            
            await state.clear()
        else:
            await message.answer(f"❌ Ошибка: {action}", reply_markup=main_menu)
            await state.clear()
        
    except Exception as e:
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=main_menu)
        await state.clear()

# Обработка текста вместо фото
@dp.message(ProfileStates.waiting_photo, ~F.photo)
async def process_photo_invalid(message: types.Message, state: FSMContext):
    await message.answer("❌ Пожалуйста, отправьте фото для анкеты")

# ===== ПРОСМОТР АНКЕТ =====
@dp.message(F.text == "👤 Моя анкета")
@dp.message(Command("myprofile"))
async def show_profile(message: types.Message):
    try:
        async with pool.acquire() as conn:
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE user_id = $1", 
                message.from_user.id
            )
            
            if profile:
                status_text = {
                    'pending': '⏳ На модерации',
                    'approved': '✅ Одобрена',
                    'rejected': '❌ Отклонена'
                }.get(profile['status'], '❓ Неизвестно')
                
                await message.answer_photo(
                    photo=profile['photo'],
                    caption=f"📋 <b>Ваша анкета:</b>\n\n"
                           f"👤 <b>Имя:</b> {profile['name']}\n"
                           f"🎭 <b>Роль:</b> {profile['role']}\n"
                           f"🎂 <b>Возраст:</b> {profile['age']}\n"
                           f"🏙️ <b>Город:</b> {profile['city']}\n"
                           f"📝 <b>О себе:</b> {profile['bio']}\n\n"
                           f"📊 <b>Статус:</b> {status_text}",
                    reply_markup=main_menu
                )
            else:
                await message.answer("У вас нет анкеты. Создайте её!", reply_markup=main_menu)
                
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(F.text == "🔍 Найти анкеты")
@dp.message(Command("search"))
async def search_profiles(message: types.Message):
    # Проверяем лимит поиска
    can_search, searches_left = await check_search_limit(message.from_user.id)
    
    if not can_search:
        await message.answer(
            f"❌ Вы исчерпали лимит поисков на сегодня ({Config.FREE_DAILY_SEARCHES} в день).\n\n"
            "💎 <b>Премиум подписка</b> снимает все ограничения!\n"
            "Нажмите '💰 Тарифы' для получения информации.",
            reply_markup=main_menu
        )
        return
    
    try:
        async with pool.acquire() as conn:
            profiles = await conn.fetch(
                "SELECT name, role, age, city, bio, photo FROM profiles WHERE user_id != $1 AND status = 'approved' AND is_active = true LIMIT 3",
                message.from_user.id
            )
            
            if profiles:
                await increment_search_count(message.from_user.id)
                
                for profile in profiles:
                    name, role, age, city, bio, photo = profile
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
                    
                if searches_left > 0:
                    await message.answer(f"🔍 Осталось поисков сегодня: {searches_left}")
            else:
                await message.answer("Пока нет других анкет.", reply_markup=main_menu)
                
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("list"))
async def list_profiles(message: types.Message):
    try:
        async with pool.acquire() as conn:
            profiles = await conn.fetch(
                "SELECT name, role, age, city, bio, photo FROM profiles WHERE status = 'approved' AND is_active = true ORDER BY created_at DESC LIMIT 10"
            )
            
            if not profiles:
                await message.answer("📭 Пока нет одобренных анкет.")
                return
            
            for profile in profiles:
                name, role, age, city, bio, photo = profile
                bio_preview = bio[:100] + "..." if len(bio) > 100 else bio
                caption = (
                    f"👤 <b>Имя:</b> {name}\n"
                    f"🎭 <b>Роль:</b> {role}\n" 
                    f"🎂 <b>Возраст:</b> {age}\n"
                    f"🏙️ <b>Город:</b> {city}\n"
                    f"📝 <b>О себе:</b> {bio_preview}"
                )
                await message.answer_photo(photo=photo, caption=caption)
                
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ===== СИСТЕМА МОДЕРАЦИИ =====
@dp.callback_query(F.data.startswith(("approve_", "reject_", "ban_", "take_")))
async def handle_moderation(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ У вас нет прав модератора", show_alert=True)
        return
    
    action, user_id = callback.data.split("_")
    user_id = int(user_id)
    
    try:
        async with pool.acquire() as conn:
            
            if action == "take":
                existing = await conn.fetchrow(
                    "SELECT moderator_id FROM active_moderations WHERE user_id = $1",
                    user_id
                )
                
                if existing:
                    await callback.answer(f"❌ Анкету уже взял модератор {existing['moderator_id']}", show_alert=True)
                    return
                
                await conn.execute(
                    "INSERT INTO active_moderations (user_id, moderator_id) VALUES ($1, $2) "
                    "ON CONFLICT (user_id) DO UPDATE SET moderator_id = $2, taken_at = NOW()",
                    user_id, callback.from_user.id
                )
                
                await callback.answer("✅ Вы взяли анкету в работу", show_alert=True)
                
                # Обновляем клавиатуру для всех сообщений
                for moderator_id in Config.MODERATORS:
                    try:
                        # Здесь нужно найти и обновить сообщение у каждого модератора
                        # В реальном боте это сложнее, но для простоты обновим только текущее
                        await callback.message.edit_reply_markup(
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{user_id}"),
                                 InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}"),
                                 InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{user_id}")],
                                [InlineKeyboardButton(text=f"👨‍💻 В работе: {callback.from_user.id}", callback_data="none")]
                            ])
                        )
                    except:
                        pass
                return
            
            moderation_info = await conn.fetchrow(
                "SELECT moderator_id FROM active_moderations WHERE user_id = $1",
                user_id
            )
            
            if moderation_info and moderation_info['moderator_id'] != callback.from_user.id:
                await callback.answer(f"❌ Эту анкету уже взял модератор {moderation_info['moderator_id']}", show_alert=True)
                return
            
            if action == "approve":
                await conn.execute(
                    "UPDATE profiles SET status = 'approved', moderated_by = $1 WHERE user_id = $2",
                    callback.from_user.id, user_id
                )
                try:
                    await bot.send_message(user_id, "🎉 Ваша анкета одобрена модератором!")
                except:
                    pass
                await callback.answer("✅ Анкета одобрена")
                
            elif action == "reject":
                await conn.execute(
                    "UPDATE profiles SET status = 'rejected', moderated_by = $1 WHERE user_id = $2",
                    callback.from_user.id, user_id
                )
                try:
                    await bot.send_message(user_id, "❌ Ваша анкета отклонена модератором.")
                except:
                    pass
                await callback.answer("❌ Анкета отклонена")
                
            elif action == "ban":
                await conn.execute(
                    "INSERT INTO banned_users (user_id, reason, banned_by) VALUES ($1, $2, $3)",
                    user_id, "Нарушение правил", callback.from_user.id
                )
                try:
                    await bot.send_message(user_id, "🚫 Ваш аккаунт заблокирован модератором.")
                except:
                    pass
                await callback.answer("✅ Пользователь забанен")
            
            await conn.execute("DELETE FROM active_moderations WHERE user_id = $1", user_id)
            await callback.message.edit_reply_markup(reply_markup=None)
            
    except Exception as e:
        print(f"❌ Ошибка модерации: {e}")
        await callback.answer("❌ Ошибка при обработке", show_alert=True)

# ===== СТАТИСТИКА =====
@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика")
async def stats_command(message: types.Message):
    try:
        async with pool.acquire() as conn:
            # Базовая статистика для всех пользователей
            total_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles")
            pending_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE status = 'pending'")
            approved_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE status = 'approved'")
            
            # Статистика пользователя
            user_profiles = await conn.fetchval(
                "SELECT COUNT(*) FROM profiles WHERE user_id = $1", 
                message.from_user.id
            )
            
            user_approved = await conn.fetchval(
                "SELECT COUNT(*) FROM profiles WHERE user_id = $1 AND status = 'approved'", 
                message.from_user.id
            )
            
            limits = await check_user_limits(message.from_user.id)
            
            stats_text = (
                f"📊 <b>Статистика бота</b>\n\n"
                f"👤 <b>Общая статистика:</b>\n"
                f"• Всего анкет: {total_profiles}\n"
                f"• На модерации: {pending_profiles}\n"
                f"• Одобрено: {approved_profiles}\n\n"
                f"👤 <b>Ваша статистика:</b>\n"
                f"• Ваших анкет: {user_profiles}\n"
                f"• Одобрено: {user_approved}\n"
                f"• Лимит анкет: {limits['max_profiles']}\n"
                f"• Статус: {'💎 Премиум' if limits['is_premium'] else '🎯 Бесплатно'}\n\n"
                f"🕒 <i>Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
            )
            
            await message.answer(stats_text)
            
    except Exception as e:
        await message.answer(f"❌ Ошибка статистики: {e}")

# Админская статистика
@dp.message(Command("admin_stats"))
async def admin_stats_command(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        async with pool.acquire() as conn:
            today = datetime.now().strftime('%Y-%m-%d')
            today_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'approved' THEN 1 END) as approved,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                    COUNT(CASE WHEN status = 'rejected' THEN 1 END) as rejected
                FROM profiles 
                WHERE DATE(created_at) = $1
            """, today)
            
            total_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_profiles,
                    COUNT(DISTINCT user_id) as unique_users
                FROM profiles
            """)
            
            banned_users = await conn.fetchval("SELECT COUNT(*) FROM banned_users WHERE expires_at > NOW() OR expires_at IS NULL")
            premium_users = await conn.fetchval("SELECT COUNT(*) FROM subscriptions WHERE expires_at > NOW()")
            
            analytics_text = f"""
📈 <b>Админ статистика</b>

<b>Сегодня ({today}):</b>
📝 Новых анкет: {today_stats['total']}
✅ Одобрено: {today_stats['approved']}
⏳ На модерации: {today_stats['pending']}
❌ Отклонено: {today_stats['rejected']}

<b>Всего:</b>
👥 Уникальных пользователей: {total_stats['unique_users']}
📋 Всего анкет: {total_stats['total_profiles']}
🚫 Заблокировано: {banned_users}
💎 Премиум пользователей: {premium_users}

🕒 Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
            """
            
            await message.answer(analytics_text)
            
    except Exception as e:
        await message.answer(f"❌ Ошибка аналитики: {e}")

# ===== ЗАПУСК БОТА =====
async def main():
    await init_db()
    print("🤖 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())