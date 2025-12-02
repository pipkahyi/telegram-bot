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
    DATABASE_URL = "postgresql://neondb_owner:npg_g9V7oqFCiZwY@ep-bold-sunset-ahlhp31q-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

    # Токен бота
    BOT_TOKEN = "8240552495:AAF-g-RGQKzxIGuXs5PQZwf1Asp6hIJ93U4"
    
    # ID администратора и модераторов
    ADMIN_ID = 7788088499
    MODERATORS = [7788088499]  # список ID модераторов
    
    # Группа для модерации
    MODERATION_GROUP_ID = -5069006369 
    
    # Тип модерации: "group" или "private"
    MODERATION_TYPE = "group"
    
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
    
    # ОБНОВЛЕННЫЕ ЦЕНЫ (доступные)
    PRICES = {
        'basic_month': 500,      # Базовый: 500₸/месяц
        'pro_month': 1000,       # Профи: 1,000₸/месяц
        'premium_month': 2000,   # Премиум: 2,000₸/месяц
    }
    
    # Поддерживаемые языки
    SUPPORTED_LANGUAGES = ['ru', 'kz']
    
    # Реквизиты для оплаты (замените на реальные)
    PAYMENT_DETAILS = {
        'kaspi': '4400 4301 1234 5678',  # Номер карты Kaspi
        'halyk': '1234 5678 9012 3456',  # Номер карты Halyk
        'jusan': '9876 5432 1098 7654',  # Номер карты Jusan
    }
    
    # Контакт поддержки
    SUPPORT_CONTACT = "@ваша_поддержка"

# ===== СОСТОЯНИЯ FSM =====
class ProfileStates(StatesGroup):
    waiting_role = State()
    waiting_age = State()
    waiting_city = State()
    waiting_bio = State()
    waiting_photo = State()

class PaymentStates(StatesGroup):
    waiting_screenshot = State()

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
pool = None

# ===== СИСТЕМА ЗАЩИТЫ =====
user_cooldowns = defaultdict(dict)
user_languages = defaultdict(lambda: 'ru')  # По умолчанию русский

def contains_bad_words(text):
    text_lower = text.lower()
    return any(bad_word.lower() in text_lower for bad_word in Config.BAD_WORDS)

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
def validate_role(role):
    if len(role) < 2 or len(role) > 50:
        return False, "Роль должна быть от 2 до 50 символов"
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
def get_main_menu(user_id):
    lang = user_languages[user_id]
    if lang == 'kz':
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📝 Анкета жасау"), KeyboardButton(text="👤 Менің анкетам")],
                [KeyboardButton(text="🔍 Анкета іздеу"), KeyboardButton(text="ℹ️ Анықтама")],
                [KeyboardButton(text="💰 Бағалар"), KeyboardButton(text="📊 Статистика")],
                [KeyboardButton(text="🌐 Тілді өзгерту")]
            ],
            resize_keyboard=True
        )
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📝 Создать анкету"), KeyboardButton(text="👤 Моя анкета")],
                [KeyboardButton(text="🔍 Найти анкеты"), KeyboardButton(text="ℹ️ Помощь")],
                [KeyboardButton(text="💰 Тарифы"), KeyboardButton(text="📊 Статистика")],
                [KeyboardButton(text="🌐 Сменить язык")]
            ],
            resize_keyboard=True
        )

cancel_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# Клавиатура для покупки премиума
premium_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💰 Базовый - 500₸/мес", callback_data="buy_basic_month")],
    [InlineKeyboardButton(text="💎 Профи - 1,000₸/мес", callback_data="buy_pro_month")],
    [InlineKeyboardButton(text="👑 Премиум - 2,000₸/мес", callback_data="buy_premium_month")],
    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
])

# Клавиатура выбора банка
def get_bank_menu(plan):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 Kaspi Bank", callback_data=f"bank_kaspi_{plan}")],
        [InlineKeyboardButton(text="🏦 Halyk Bank", callback_data=f"bank_halyk_{plan}")],
        [InlineKeyboardButton(text="🏦 Jusan Bank", callback_data=f"bank_jusan_{plan}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
    ])

# Клавиатура выбора языка
language_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
    [InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="lang_kz")]
])

# ===== БАЗА ДАННЫХ =====
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(Config.DATABASE_URL)
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
                    reported_profile_id BIGINT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
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
            
            # Таблица активных модераций (кто взял анкету)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_moderations (
                    user_id BIGINT PRIMARY KEY,
                    moderator_id BIGINT NOT NULL,
                    moderator_name TEXT,
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
            
            # Таблица платежей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    plan TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица языков пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_languages (
                    user_id BIGINT PRIMARY KEY,
                    language_code TEXT NOT NULL DEFAULT 'ru',
                    updated_at TIMESTAMP DEFAULT NOW()
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
                return True, Config.FREE_DAILY_SEARCHES
                
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

async def save_profile(user_id, username, role, age, city, bio, photo):
    try:
        # Используем username как имя, если он есть, иначе "Пользователь"
        name = username if username else f"Пользователь {user_id}"
        
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
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, user_id, username, name, role, age, city, bio, photo)
                action = "создана"
            
            return True, action
            
    except Exception as e:
        print(f"❌ Ошибка сохранения для user_id {user_id}: {e}")
        return False, str(e)

async def take_moderation(callback: types.CallbackQuery, user_id: int):
    """Берет анкету в работу"""
    try:
        async with pool.acquire() as conn:
            # Проверяем, не взял ли уже кто-то
            existing = await conn.fetchrow(
                "SELECT moderator_id, moderator_name FROM active_moderations WHERE user_id = $1",
                user_id
            )
            
            if existing:
                await callback.answer(
                    f"❌ Анкету уже взял модератор {existing['moderator_name'] or existing['moderator_id']}", 
                    show_alert=True
                )
                return False
            
            # Берем в работу
            moderator_name = f"{callback.from_user.first_name}" + (f" {callback.from_user.last_name}" if callback.from_user.last_name else "")
            await conn.execute(
                "INSERT INTO active_moderations (user_id, moderator_id, moderator_name) VALUES ($1, $2, $3)",
                user_id, callback.from_user.id, moderator_name
            )
            
            # Обновляем сообщение
            new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{user_id}"),
                 InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}"),
                 InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{user_id}")],
                [InlineKeyboardButton(text=f"👨‍💻 В работе у: {moderator_name}", callback_data="none")]
            ])
            
            try:
                await callback.message.edit_reply_markup(reply_markup=new_keyboard)
            except:
                pass  # Если не удалось обновить клавиатуру
            
            await callback.answer("✅ Вы взяли анкету в работу", show_alert=True)
            return True
            
    except Exception as e:
        print(f"❌ Ошибка взятия анкеты: {e}")
        await callback.answer("❌ Ошибка при взятии анкеты", show_alert=True)
        return False

async def notify_all_moderators(user_id, username, role, age, city, bio, photo):
    """Уведомляет модераторов о новой анкете"""
    try:
        name = username if username else f"Пользователь {user_id}"
        
        moderation_text = (
            "🆕 <b>НОВАЯ АНКЕТА НА МОДЕРАЦИЮ</b>\n\n"
            f"👤 <b>ID:</b> <code>{user_id}</code>\n"
            f"🔗 <b>Username:</b> @{username if username else 'нет'}\n"
            f"🎭 <b>Роль:</b> {role}\n"
            f"🎂 <b>Возраст:</b> {age}\n"
            f"🏙️ <b>Город:</b> {city}\n"
            f"📝 <b>О себе:</b> {bio[:200]}...\n\n"
            f"⏰ <b>Время подачи:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        
        moderation_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{user_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}"),
             InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{user_id}")],
            [InlineKeyboardButton(text="👨‍💻 Взять в работу", callback_data=f"take_{user_id}")]
        ])
        
        if Config.MODERATION_TYPE == "group":
            # Отправляем в группу
            try:
                if photo:
                    await bot.send_photo(
                        chat_id=Config.MODERATION_GROUP_ID,
                        photo=photo,
                        caption=moderation_text,
                        reply_markup=moderation_keyboard
                    )
                else:
                    await bot.send_message(
                        chat_id=Config.MODERATION_GROUP_ID,
                        text=moderation_text,
                        reply_markup=moderation_keyboard
                    )
                return True
            except Exception as e:
                print(f"❌ Ошибка отправки в группу: {e}")
                return False
        else:
            # Отправляем каждому модератору лично
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

# ===== СИСТЕМА ПОДПИСОК И ПЛАТЕЖЕЙ =====
async def create_subscription(user_id, plan):
    """Создает подписку для пользователя"""
    try:
        async with pool.acquire() as conn:
            # Определяем срок подписки
            if plan == 'basic_month':
                expires_at = datetime.now() + timedelta(days=30)
            elif plan == 'pro_month':
                expires_at = datetime.now() + timedelta(days=30)
            elif plan == 'premium_month':
                expires_at = datetime.now() + timedelta(days=30)
            else:
                return False, "Неизвестный план"
            
            # Сохраняем подписку
            await conn.execute("""
                INSERT INTO subscriptions (user_id, plan, expires_at) 
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) 
                DO UPDATE SET plan = $2, expires_at = $3, starts_at = NOW()
            """, user_id, plan, expires_at)
            
            return True, "Подписка активирована!"
            
    except Exception as e:
        print(f"❌ Ошибка создания подписки: {e}")
        return False, "Ошибка активации подписки"

async def process_payment(user_id, plan):
    """Обрабатывает платеж"""
    try:
        async with pool.acquire() as conn:
            # Сохраняем информацию о платеже
            amount = Config.PRICES[plan]
            await conn.execute(
                "INSERT INTO payments (user_id, amount, plan, status) VALUES ($1, $2, $3, 'completed')",
                user_id, amount, plan
            )
            
            # Активируем подписку
            success, message = await create_subscription(user_id, plan)
            return success, message
            
    except Exception as e:
        print(f"❌ Ошибка обработки платежа: {e}")
        return False, "Ошибка обработки платежа"

async def generate_payment_instructions(plan, bank):
    """Генерирует инструкции для оплаты"""
    plan_names = {
        'basic_month': 'Базовый (1 месяц)',
        'pro_month': 'Профи (1 месяц)', 
        'premium_month': 'Премиум (1 месяц)'
    }
    
    bank_names = {
        'kaspi': 'Kaspi Bank',
        'halyk': 'Halyk Bank',
        'jusan': 'Jusan Bank'
    }
    
    amount = Config.PRICES[plan]
    card_number = Config.PAYMENT_DETAILS[bank]
    
    instructions = (
        f"💳 <b>Инструкция по оплате</b>\n\n"
        f"📋 <b>Тариф:</b> {plan_names.get(plan, plan)}\n"
        f"🏦 <b>Банк:</b> {bank_names.get(bank, bank)}\n"
        f"💵 <b>Сумма:</b> {amount}₸\n"
        f"📮 <b>Номер карты:</b> <code>{card_number}</code>\n\n"
        f"📝 <b>Как оплатить:</b>\n"
        f"1. Переведите {amount}₸ на указанный номер карты\n"
        f"2. Сохраните скриншот чека перевода\n"
        f"3. Вернитесь в этот чат и отправьте скриншот\n"
        f"4. Мы активируем подписку в течение 24 часов\n\n"
        f"💬 <b>Поддержка:</b> {Config.SUPPORT_CONTACT}\n\n"
        f"⚠️ <i>В комментарии к переводу укажите: {plan}</i>"
    )
    
    return instructions

# ===== КОМАНДЫ БОТА =====
@dp.message(Command("start"))
async def start_command(message: types.Message):
    # Загружаем язык пользователя из БД
    try:
        async with pool.acquire() as conn:
            lang_row = await conn.fetchrow(
                "SELECT language_code FROM user_languages WHERE user_id = $1",
                message.from_user.id
            )
            if lang_row:
                user_languages[message.from_user.id] = lang_row['language_code']
    except:
        pass
    
    welcome_text = (
        "👋 Привет! Я бот для создания и поиска анкет.\n\n"
        "📝 <b>Создать анкету</b> - заполните информацию о себе\n"
        "👤 <b>Моя анкета</b> - посмотреть свою анкету\n"
        "🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей\n"
        "💰 <b>Тарифы</b> - информация о премиум подписке\n"
        "📊 <b>Статистика</b> - статистика бота\n"
        "ℹ️ <b>Помощь</b> - показать это сообщение\n"
        "🌐 <b>Сменить язык</b> - изменить язык интерфейса\n\n"
        "Выберите действие на клавиатуре ниже 👇"
    )
    await message.answer(welcome_text, reply_markup=get_main_menu(message.from_user.id))

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
        "/buy - купить премиум подписку"
    )
    await message.answer(help_text, reply_markup=get_main_menu(message.from_user.id))

# ===== ИСПРАВЛЕНИЕ: ОБРАБОТЧИКИ КАЗАХСКИХ КОМАНД =====
@dp.message(F.text == "📝 Анкета жасау")
async def start_anketa_kz(message: types.Message, state: FSMContext):
    await start_anketa(message, state)

@dp.message(F.text == "👤 Менің анкетам")
async def my_profile_kz(message: types.Message):
    await show_profile(message)

@dp.message(F.text == "🔍 Анкета іздеу")
async def search_profiles_kz(message: types.Message):
    await search_profiles(message)

@dp.message(F.text == "ℹ️ Анықтама")
async def help_kz(message: types.Message):
    await help_command(message)

@dp.message(F.text == "💰 Бағалар")
async def buy_premium_kz(message: types.Message):
    await buy_premium(message)

@dp.message(F.text == "📊 Статистика")
async def stats_kz(message: types.Message):
    await stats_command(message)

@dp.message(Command("language"))
@dp.message(F.text == "🌐 Сменить язык")
@dp.message(F.text == "🌐 Тілді өзгерту")
async def language_command(message: types.Message):
    await message.answer(
        "🌐 <b>Выберите язык / Тілді таңдаңыз</b>\n\n"
        "🇷🇺 Русский\n"
        "🇰🇿 Қазақша",
        reply_markup=language_menu
    )

@dp.callback_query(F.data.startswith("lang_"))
async def set_language(callback: types.CallbackQuery):
    language = callback.data.replace("lang_", "")
    user_id = callback.from_user.id
    user_languages[user_id] = language
    
    # Сохраняем в БД
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_languages (user_id, language_code) 
                VALUES ($1, $2)
                ON CONFLICT (user_id) 
                DO UPDATE SET language_code = $2, updated_at = NOW()
            """, user_id, language)
    except Exception as e:
        print(f"❌ Ошибка сохранения языка: {e}")
    
    if language == 'kz':
        text = "🌐 Тіл қазақ тіліне өзгертілді!"
    else:
        text = "🌐 Язык изменен на русский!"
    
    await callback.message.edit_text(text)
    await callback.answer()

@dp.message(Command("get_chat_id"))
async def get_chat_id(message: types.Message):
    chat_id = message.chat.id
    await message.answer(f"ID этого чата: <code>{chat_id}</code>")

# ===== СИСТЕМА ПОДПИСОК =====
@dp.message(Command("buy"))
@dp.message(F.text == "💰 Тарифы")
async def buy_premium(message: types.Message):
    pricing_text = f"""
💰 <b>Тарифы бота</b>

🎯 <b>Бесплатный тариф:</b>
• 1 анкета
• 5 поисков в день  
• Базовая функциональность
• Ожидание модерации 1-3 дня

💎 <b>Премиум подписка:</b>

<b>Базовый - 500₸/месяц</b>
• До 3 анкет
• 15 поисков в день
• Приоритетная модерация (24 часа)
• Поддержка 24/7

<b>Профи - 1,000₸/месяц</b>
• До 10 анкет
• 30 поисков в день  
• Срочная модерация (12 часов)
• Приоритет в поиске
• Поддержка 24/7

<b>Премиум - 2,000₸/месяц</b>
• Неограниченное количество анкет
• Неограниченный поиск
• Мгновенная модерация (1-6 часов)
• Максимальный приоритет в поиске
• Расширенная статистика
• Поддержка 24/7

👇 <b>Выберите тариф:</b>
    """
    
    await message.answer(pricing_text, reply_markup=premium_menu)

# Обработка выбора тарифа
@dp.callback_query(F.data.startswith("buy_"))
async def handle_payment_selection(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    plan = callback.data.replace("buy_", "")
    
    # ПРОВЕРКА НА ДУБЛИРОВАНИЕ ПЛАТЕЖЕЙ
    async with pool.acquire() as conn:
        active_payment = await conn.fetchrow(
            "SELECT id FROM payments WHERE user_id = $1 AND status = 'pending'",
            user_id
        )
        
        if active_payment:
            await callback.answer(
                "⏳ У вас уже есть платеж на проверке. Дождитесь его обработки.",
                show_alert=True
            )
            return
    
    bank_selection_text = f"""
💳 <b>Выбор способа оплаты</b>

📋 <b>Тариф:</b> {plan}
💵 <b>Сумма:</b> {Config.PRICES[plan]}₸

👇 <b>Выберите банк для оплаты:</b>
    """
    
    await callback.message.edit_text(
        bank_selection_text,
        reply_markup=get_bank_menu(plan)
    )
    await callback.answer()

# Обработка выбора банка
@dp.callback_query(F.data.startswith("bank_"))
async def handle_bank_selection(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data.replace("bank_", "")
    bank, plan = data.split("_", 1)
    
    # ПРОВЕРКА НА ДУБЛИРОВАНИЕ ПЛАТЕЖЕЙ
    async with pool.acquire() as conn:
        active_payment = await conn.fetchrow(
            "SELECT id FROM payments WHERE user_id = $1 AND status = 'pending'",
            callback.from_user.id
        )
        
        if active_payment:
            await callback.answer(
                "⏳ У вас уже есть платеж на проверке. Дождитесь его обработки.",
                show_alert=True
            )
            return
    
    # Сохраняем данные в состоянии
    await state.update_data(
        bank=bank,
        plan=plan,
        amount=Config.PRICES[plan],
        user_id=callback.from_user.id
    )
    
    # Генерируем инструкции
    instructions = await generate_payment_instructions(plan, bank)
    
    await callback.message.edit_text(
        instructions,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📎 Отправить скриншот", callback_data="send_screenshot")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
        ])
    )
    await callback.answer()

# Обработка кнопки отправки скриншота
@dp.callback_query(F.data == "send_screenshot")
async def handle_send_screenshot(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📎 <b>Отправьте скриншот перевода</b>\n\n"
        "Пожалуйста, отправьте скриншот или фото чека перевода для подтверждения оплаты.",
        reply_markup=cancel_menu
    )
    await state.set_state(PaymentStates.waiting_screenshot)
    await callback.answer()

# Обработка скриншота оплаты
@dp.message(PaymentStates.waiting_screenshot, F.photo)
async def process_payment_screenshot(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    photo = message.photo[-1].file_id
    
    # Сохраняем платеж в БД со статусом pending
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO payments (user_id, amount, plan, status) VALUES ($1, $2, $3, 'pending')",
                message.from_user.id, user_data['amount'], user_data['plan']
            )
    except Exception as e:
        print(f"❌ Ошибка сохранения платежа: {e}")
    
    # Уведомляем админов о новом платеже
    payment_text = (
        f"🆕 <b>НОВЫЙ ПЛАТЕЖ</b>\n\n"
        f"👤 <b>Пользователь:</b> {message.from_user.first_name} (ID: {message.from_user.id})\n"
        f"🔗 <b>Username:</b> @{message.from_user.username if message.from_user.username else 'нет'}\n"
        f"🏦 <b>Банк:</b> {user_data['bank']}\n"
        f"📋 <b>Тариф:</b> {user_data['plan']}\n"
        f"💵 <b>Сумма:</b> {user_data['amount']}₸\n\n"
        f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    payment_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_payment_{message.from_user.id}_{user_data['plan']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_payment_{message.from_user.id}")
        ]
    ])
    
    # Отправляем админам
    for admin_id in [Config.ADMIN_ID] + Config.MODERATORS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=photo,
                caption=payment_text,
                reply_markup=payment_keyboard
            )
        except Exception as e:
            print(f"❌ Не удалось отправить уведомление админу {admin_id}: {e}")
    
    await message.answer(
        "✅ Скриншот отправлен на проверку!\n\n"
        "Мы активируем вашу подписку в течение 24 часов после проверки платежа.\n"
        "Спасибо за покупку! ❤️",
        reply_markup=get_main_menu(message.from_user.id)
    )
    
    await state.clear()

# ===== ИСПРАВЛЕННЫЕ ОБРАБОТЧИКИ ПЛАТЕЖЕЙ =====
@dp.callback_query(F.data.startswith("confirm_payment_"))
async def confirm_payment(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ Только для модераторов", show_alert=True)
        return
    
    try:
        # Извлекаем данные из callback
        data_parts = callback.data.replace("confirm_payment_", "").split("_")
        user_id = int(data_parts[0])
        plan = data_parts[1]
        
        print(f"🔧 DEBUG: Подтверждение платежа - user_id: {user_id}, plan: {plan}")
        
        success, message = await process_payment(user_id, plan)
        
        if success:
            # Обновляем сообщение
            await callback.message.edit_text(
                f"✅ <b>Платеж подтвержден!</b>\n\n"
                f"👤 <b>Пользователь:</b> {user_id}\n"
                f"📋 <b>Тариф:</b> {plan}\n"
                f"💵 <b>Сумма:</b> {Config.PRICES[plan]}₸\n"
                f"⏰ <b>Активировано:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                reply_markup=None
            )
            
            # Уведомляем пользователя
            try:
                plan_names = {
                    'basic_month': 'Базовый',
                    'pro_month': 'Профи', 
                    'premium_month': 'Премиум'
                }
                await bot.send_message(
                    user_id,
                    f"🎉 <b>Ваш платеж подтвержден!</b>\n\n"
                    f"💎 <b>Тариф:</b> {plan_names.get(plan, plan)}\n"
                    f"⏰ <b>Активировано:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"Спасибо за покупку! ❤️"
                )
            except Exception as e:
                print(f"❌ Не удалось уведомить пользователя: {e}")
        else:
            await callback.message.edit_text(f"❌ Ошибка: {message}")
        
        await callback.answer()
        
    except Exception as e:
        print(f"❌ Ошибка подтверждения платежа: {e}")
        await callback.answer("❌ Ошибка при подтверждении платежа", show_alert=True)

@dp.callback_query(F.data.startswith("reject_payment_"))
async def reject_payment(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ Только для модераторов", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.replace("reject_payment_", ""))
        
        print(f"🔧 DEBUG: Отклонение платежа - user_id: {user_id}")
        
        # Обновляем статус платежа в БД
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE payments SET status = 'rejected' WHERE user_id = $1 AND status = 'pending'",
                user_id
            )
        
        await callback.message.edit_text(
            f"❌ <b>Платеж отклонен</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_id}\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            reply_markup=None
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                "❌ <b>Ваш платеж был отклонен</b>\n\n"
                "Возможные причины:\n"
                "• Нечеткий скриншот\n"
                "• Неправильная сумма\n"
                "• Подозрительная активность\n\n"
                f"💬 Для уточнения обратитесь в поддержку: {Config.SUPPORT_CONTACT}"
            )
        except Exception as e:
            print(f"❌ Не удалось уведомить пользователя: {e}")
        
        await callback.answer()
        
    except Exception as e:
        print(f"❌ Ошибка отклонения платежа: {e}")
        await callback.answer("❌ Ошибка при отклонении платежа", show_alert=True)

@dp.callback_query(F.data == "cancel_buy")
async def cancel_buy(callback: types.CallbackQuery):
    await callback.message.edit_text("Покупка отменена", reply_markup=None)
    await callback.answer()

# ===== КРАСИВЫЙ СПИСОК АНКЕТ =====
@dp.message(Command("list"))
async def list_profiles(message: types.Message):
    try:
        async with pool.acquire() as conn:
            profiles = await conn.fetch(
                "SELECT name, role, age, city, bio FROM profiles WHERE status = 'approved' AND is_active = true ORDER BY created_at DESC LIMIT 50"
            )
            
            if not profiles:
                await message.answer("📭 Пока нет одобренных анкет.")
                return
            
            # Создаем красивый список
            list_text = "📋 <b>СПИСОК АНКЕТ</b>\n\n"
            
            for i, profile in enumerate(profiles, 1):
                name, role, age, city, bio = profile
                bio_preview = bio[:100] + "..." if len(bio) > 100 else bio
                
                list_text += f"┌{'─' * 35}┐\n"
                list_text += f"│ <b>{i}. {name}</b>\n"
                list_text += f"│    🎭 <b>Роль:</b> {role}\n"
                list_text += f"│    🎂 <b>Возраст:</b> {age}\n"
                list_text += f"│    🏙️ <b>Город:</b> {city}\n"
                list_text += f"│    📝 <b>О себе:</b> {bio_preview}\n"
                list_text += f"└{'─' * 35}┘\n\n"
            
            list_text += f"📊 <b>Всего анкет:</b> {len(profiles)}"
            
            # Разбиваем на части если текст слишком длинный
            if len(list_text) > 4000:
                chunks = [list_text[i:i+4000] for i in range(0, len(list_text), 4000)]
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(list_text)
                
            await message.answer(
                "👀 <b>Используйте поиск для просмотра фото анкет</b>",
                reply_markup=get_main_menu(message.from_user.id)
            )
                
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ===== ИСПРАВЛЕННАЯ СИСТЕМА ЖАЛОБ =====
@dp.message(Command("report"))
async def report_command(message: types.Message):
    """Обработчик жалоб с аргументами"""
    try:
        # Если команда без аргументов - показываем помощь
        if len(message.text.split()) < 3:
            await message.answer(
                "📢 <b>Пожаловаться на анкету</b>\n\n"
                "Чтобы пожаловаться на анкету:\n"
                "1. Найдите анкету через поиск\n"
                "2. Отправьте команду: <code>/report ID_пользователя причина</code>\n\n"
                "📝 <b>Пример:</b>\n"
                "<code>/report 123456789 Спам</code>\n"
                "<code>/report 7927307806 Неприемлемый контент</code>"
            )
            return
        
        parts = message.text.split()
        reported_user_id = int(parts[1])
        reason = ' '.join(parts[2:])
        
        # Проверяем существование пользователя
        async with pool.acquire() as conn:
            profile = await conn.fetchrow(
                "SELECT name FROM profiles WHERE user_id = $1", 
                reported_user_id
            )
            
            if not profile:
                await message.answer("❌ Пользователь с таким ID не найден.")
                return
            
            # Сохраняем жалобу в БД
            await conn.execute(
                "INSERT INTO reports (reporter_id, reported_user_id, reported_profile_id, reason) VALUES ($1, $2, $3, $4)",
                message.from_user.id, reported_user_id, reported_user_id, reason
            )
        
        # Уведомляем модераторов
        report_text = (
            "🚨 <b>НОВАЯ ЖАЛОБА</b>\n\n"
            f"👤 <b>Жалоба от:</b> {message.from_user.first_name} (ID: {message.from_user.id})\n"
            f"👥 <b>На пользователя:</b> {reported_user_id} ({profile['name']})\n"
            f"📝 <b>Причина:</b> {reason}\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        
        report_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="👀 Посмотреть анкету", callback_data=f"view_{reported_user_id}"),
                InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{reported_user_id}")
            ]
        ])
        
        if Config.MODERATION_TYPE == "group":
            await bot.send_message(Config.MODERATION_GROUP_ID, report_text, reply_markup=report_keyboard)
        else:
            for moderator_id in Config.MODERATORS:
                try:
                    await bot.send_message(moderator_id, report_text, reply_markup=report_keyboard)
                except:
                    pass
        
        await message.answer("✅ Жалоба отправлена модераторам. Спасибо за бдительность!")
        
    except ValueError:
        await message.answer("❌ Неверный формат ID пользователя. ID должен быть числом.")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки жалобы: {e}")

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
                reply_markup=get_main_menu(message.from_user.id)
            )
        return

    await message.answer(
        "📝 Давайте создадим вашу анкету!\n\n"
        "🎭 Напишите вашу роль (например: Модератор, Админ, Участник):",
        reply_markup=cancel_menu
    )
    await state.set_state(ProfileStates.waiting_role)

@dp.message(F.text == "❌ Отмена")
async def cancel_anketa(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Заполнение анкеты отменено", reply_markup=get_main_menu(message.from_user.id))

@dp.message(ProfileStates.waiting_role)
async def process_role(message: types.Message, state: FSMContext):
    role = message.text.strip()
    if role == "❌ Отмена":
        await cancel_anketa(message, state)
        return
    
    is_valid, error_msg = validate_role(role)
    if not is_valid:
        await message.answer(f"❌ {error_msg} Попробуйте еще раз:")
        return
    
    await state.update_data(role=role)
    await message.answer("🎂 Сколько вам лет?", reply_markup=cancel_menu)
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
    await message.answer("🏙️ Из какого вы города?")
    await state.set_state(ProfileStates.waiting_city)

@dp.message(ProfileStates.waiting_city)
async def process_city(message: types.Message, state: FSMContext):
    city = message.text.strip()
    is_valid, error_msg = validate_city(city)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    await state.update_data(city=city)
    await message.answer("📝 Расскажите о себе (интересы, хобби, увлечения и т.д.):")
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
                           f"🎭 <b>Роль:</b> {user_data['role']}\n"
                           f"🎂 <b>Возраст:</b> {user_data['age']}\n"
                           f"🏙️ <b>Город:</b> {user_data['city']}\n"
                           f"📝 <b>О себе:</b> {user_data['bio']}\n\n"
                           f"⏳ <i>Ожидайте решения модератора</i>",
                    reply_markup=get_main_menu(message.from_user.id)
                )
            else:
                await message.answer("❌ Ошибка отправки на модерацию", reply_markup=get_main_menu(message.from_user.id))
            
            await state.clear()
        else:
            await message.answer(f"❌ Ошибка: {action}", reply_markup=get_main_menu(message.from_user.id))
            await state.clear()
        
    except Exception as e:
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=get_main_menu(message.from_user.id))
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
                           f"🎭 <b>Роль:</b> {profile['role']}\n"
                           f"🎂 <b>Возраст:</b> {profile['age']}\n"
                           f"🏙️ <b>Город:</b> {profile['city']}\n"
                           f"📝 <b>О себе:</b> {profile['bio']}\n\n"
                           f"📊 <b>Статус:</b> {status_text}",
                    reply_markup=get_main_menu(message.from_user.id)
                )
            else:
                await message.answer("У вас нет анкеты. Создайте её!", reply_markup=get_main_menu(message.from_user.id))
                
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
            reply_markup=get_main_menu(message.from_user.id)
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
                        f"📝 <b>О себе:</b> {bio_preview}\n\n"
                        f"📢 Чтобы пожаловаться: /report {message.from_user.id} причина"
                    )
                    await message.answer_photo(photo=photo, caption=caption)
                    
                if searches_left > 0:
                    await message.answer(f"🔍 Осталось поисков сегодня: {searches_left}")
            else:
                await message.answer("Пока нет других анкет.", reply_markup=get_main_menu(message.from_user.id))
                
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# ===== СИСТЕМА МОДЕРАЦИИ =====
@dp.callback_query(F.data.startswith("take_"))
async def handle_take_moderation(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ У вас нет прав модератора", show_alert=True)
        return
    
    user_id = int(callback.data.replace("take_", ""))
    await take_moderation(callback, user_id)

@dp.callback_query(F.data.startswith(("approve_", "reject_", "ban_")))
async def handle_moderation(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ У вас нет прав модератора", show_alert=True)
        return
    
    action, user_id = callback.data.split("_")
    user_id = int(user_id)
    
    try:
        async with pool.acquire() as conn:
            
            # Проверяем, взял ли текущий модератор эту анкету
            moderation_info = await conn.fetchrow(
                "SELECT moderator_id FROM active_moderations WHERE user_id = $1",
                user_id
            )
            
            if moderation_info and moderation_info['moderator_id'] != callback.from_user.id:
                await callback.answer(
                    f"❌ Эту анкету уже взял модаратор {moderation_info['moderator_id']}", 
                    show_alert=True
                )
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
            
            # Удаляем из активных модераций
            await conn.execute("DELETE FROM active_moderations WHERE user_id = $1", user_id)
            
            # Убираем клавиатуру у сообщения
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except:
                pass
            
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
            
            # Статистика по модераторам
            moderator_stats = await conn.fetch("""
                SELECT moderated_by, COUNT(*) as count 
                FROM profiles 
                WHERE moderated_by IS NOT NULL 
                GROUP BY moderated_by
            """)
            
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

<b>Активность модераторов:</b>
"""
            for stat in moderator_stats:
                analytics_text += f"• {stat['moderated_by']}: {stat['count']} анкет\n"
            
            analytics_text += f"\n🕒 Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            
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