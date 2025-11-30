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
    # ИСПРАВЛЕННЫЕ НАСТРОЙКИ
    DATABASE_URL = "postgresql://neondb_owner:npg_g9V7oqFCiZwY@ep-bold-sunset-ahlhp31q-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    BOT_TOKEN = "8240552495:AAF-g-RGQKzxIGuXs5PQZwf1Asp6hIJ93U4"
    
    # ID администратора и модераторов
    ADMIN_ID = 7788088499
    MODERATORS = [7788088499]
    
    # Группа для модерации
    MODERATION_GROUP_ID = -5069006369 
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
    
    # Цены в тенге (ежемесячная подписка)
    PRICES = {
        'basic_month': 2000,      # Базовый: 2,000₸/месяц
        'pro_month': 5000,        # Профи: 5,000₸/месяц
        'premium_month': 12000,   # Премиум: 12,000₸/месяц
    }
    
    # Реквизиты для оплаты
    PAYMENT_DETAILS = {
        'kaspi': '+7 702 473 8282',
        'halyk': '4400 4301 1234 5678',
        'jusan': '1234 5678 9012 3456',
    }
    
    # Контакт поддержки
    SUPPORT_CONTACT = "@Baeline"

# ===== СОСТОЯНИЯ FSM =====
class ProfileStates(StatesGroup):
    waiting_name = State()
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
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Создать анкету"), KeyboardButton(text="👤 Моя анкета")],
            [KeyboardButton(text="🔍 Найти анкеты"), KeyboardButton(text="📋 Список анкет")],
            [KeyboardButton(text="💰 Тарифы"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )

cancel_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# Клавиатура для покупки премиума
premium_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💰 Базовый - 2,000₸/мес", callback_data="buy_basic_month")],
    [InlineKeyboardButton(text="💎 Профи - 5,000₸/мес", callback_data="buy_pro_month")],
    [InlineKeyboardButton(text="👑 Премиум - 12,000₸/мес", callback_data="buy_premium_month")],
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
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
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
            
            # Таблица активных модераций
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_moderations (
                    id SERIAL PRIMARY KEY,
                    profile_id INTEGER NOT NULL REFERENCES profiles(id),
                    moderator_id BIGINT NOT NULL,
                    moderator_name TEXT,
                    taken_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(profile_id)
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
                    screenshot_file_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            print("✅ Таблицы созданы/проверены")
            
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def is_admin(user_id):
    return user_id == Config.ADMIN_ID

def is_moderator(user_id):
    return user_id in Config.MODERATORS or user_id == Config.ADMIN_ID

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
            subscription = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE user_id = $1 AND expires_at > NOW()",
                user_id
            )
            
            is_premium = subscription is not None
            
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
            subscription = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE user_id = $1 AND expires_at > NOW()",
                user_id
            )
            
            if subscription:
                return True, 0
                
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

async def save_profile(user_id, username, name, role, age, city, bio, photo):
    try:
        async with pool.acquire() as conn:
            existing_user = await conn.fetchrow(
                "SELECT id FROM profiles WHERE user_id = $1 AND is_active = TRUE", 
                user_id
            )
            
            if existing_user:
                await conn.execute("""
                    UPDATE profiles SET 
                    username = $1, name = $2, role = $3, age = $4, city = $5, 
                    bio = $6, photo = $7, updated_at = NOW(), status = 'pending'
                    WHERE id = $8
                """, username, name, role, age, city, bio, photo, existing_user['id'])
                profile_id = existing_user['id']
                action = "обновлена"
            else:
                result = await conn.fetchrow("""
                    INSERT INTO profiles 
                    (user_id, username, name, role, age, city, bio, photo) 
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                """, user_id, username, name, role, age, city, bio, photo)
                profile_id = result['id']
                action = "создана"
            
            return True, action, profile_id
            
    except Exception as e:
        print(f"❌ Ошибка сохранения для user_id {user_id}: {e}")
        return False, str(e), None

async def take_moderation(callback: types.CallbackQuery, profile_id: int):
    """Берет анкету в работу - система 'кто первый взял'"""
    try:
        async with pool.acquire() as conn:
            # Проверяем, не взял ли уже кто-то
            existing = await conn.fetchrow(
                "SELECT moderator_id, moderator_name FROM active_moderations WHERE profile_id = $1",
                profile_id
            )
            
            if existing:
                await callback.answer(
                    f"❌ Анкету уже взял модератор {existing['moderator_name']}", 
                    show_alert=True
                )
                return False
            
            # Получаем информацию о профиле
            profile = await conn.fetchrow(
                "SELECT user_id, name FROM profiles WHERE id = $1",
                profile_id
            )
            
            if not profile:
                await callback.answer("❌ Анкета не найдена", show_alert=True)
                return False
            
            # Берем в работу
            moderator_name = f"{callback.from_user.first_name}" + (f" {callback.from_user.last_name}" if callback.from_user.last_name else "")
            await conn.execute(
                "INSERT INTO active_moderations (profile_id, moderator_id, moderator_name) VALUES ($1, $2, $3)",
                profile_id, callback.from_user.id, moderator_name
            )
            
            # Обновляем сообщение
            new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Принять анкету", callback_data=f"approve_{profile_id}"),
                 InlineKeyboardButton(text="❌ Отклонить анкету", callback_data=f"reject_{profile_id}")],
                [InlineKeyboardButton(text="🚫 Забанить пользователя", callback_data=f"ban_{profile['user_id']}")],
                [InlineKeyboardButton(text=f"👨‍💻 В работе у: {moderator_name}", callback_data="none")]
            ])
            
            try:
                await callback.message.edit_reply_markup(reply_markup=new_keyboard)
            except Exception as e:
                print(f"⚠️ Не удалось обновить клавиатуру: {e}")
            
            # Уведомляем других модераторов
            notification_text = (
                f"📢 Анкета '{profile['name']}' взята в работу модератором {moderator_name}"
            )
            
            if Config.MODERATION_TYPE == "group":
                try:
                    await bot.send_message(Config.MODERATION_GROUP_ID, notification_text)
                except:
                    pass
            else:
                for moderator_id in Config.MODERATORS:
                    if moderator_id != callback.from_user.id:
                        try:
                            await bot.send_message(moderator_id, notification_text)
                        except:
                            pass
            
            await callback.answer("✅ Вы взяли анкету в работу", show_alert=True)
            return True
            
    except Exception as e:
        print(f"❌ Ошибка взятия анкеты: {e}")
        await callback.answer("❌ Ошибка при взятии анкеты", show_alert=True)
        return False

async def notify_all_moderators(profile_id, user_id, username, name, role, age, city, bio, photo):
    """Уведомляет модераторов о новой анкете с системой 'кто первый взял'"""
    try:
        moderation_text = (
            "🆕 <b>НОВАЯ АНКЕТА НА МОДЕРАЦИЮ</b>\n\n"
            f"👤 <b>Пользователь:</b> {name} (ID: {user_id})\n"
            f"🔗 <b>Username:</b> @{username if username else 'нет'}\n"
            f"🎭 <b>Роль:</b> {role}\n"
            f"🎂 <b>Возраст:</b> {age}\n"
            f"🏙️ <b>Город:</b> {city}\n"
            f"📝 <b>О себе:</b> {bio[:200]}...\n\n"
            f"⏰ <b>Время подачи:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"<i>💡 Кто первый нажмет 'Взять в работу' - тот и проверяет!</i>"
        )
        
        moderation_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨‍💻 Взять в работу", callback_data=f"take_{profile_id}")]
        ])
        
        message_ids = []
        
        if Config.MODERATION_TYPE == "group":
            try:
                if photo:
                    msg = await bot.send_photo(
                        chat_id=Config.MODERATION_GROUP_ID,
                        photo=photo,
                        caption=moderation_text,
                        reply_markup=moderation_keyboard
                    )
                else:
                    msg = await bot.send_message(
                        chat_id=Config.MODERATION_GROUP_ID,
                        text=moderation_text,
                        reply_markup=moderation_keyboard
                    )
                message_ids.append((Config.MODERATION_GROUP_ID, msg.message_id))
            except Exception as e:
                print(f"❌ Ошибка отправки в группу: {e}")
                return False, []
        else:
            for moderator_id in Config.MODERATORS:
                try:
                    if photo:
                        msg = await bot.send_photo(
                            chat_id=moderator_id,
                            photo=photo,
                            caption=moderation_text,
                            reply_markup=moderation_keyboard
                        )
                    else:
                        msg = await bot.send_message(
                            chat_id=moderator_id,
                            text=moderation_text,
                            reply_markup=moderation_keyboard
                        )
                    message_ids.append((moderator_id, msg.message_id))
                except Exception as e:
                    print(f"❌ Не удалось уведомить модератора {moderator_id}: {e}")
        
        return len(message_ids) > 0, message_ids
        
    except Exception as e:
        print(f"❌ Ошибка отправки уведомлений модераторам: {e}")
        return False, []

# ===== СИСТЕМА ПОДПИСОК И ПЛАТЕЖЕЙ =====
async def create_subscription(user_id, plan):
    """Создает подписку для пользователя"""
    try:
        async with pool.acquire() as conn:
            expires_at = datetime.now() + timedelta(days=30)
            
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
        f"📮 <b>Реквизиты:</b> <code>{card_number}</code>\n\n"
        f"📝 <b>Как оплатить:</b>\n"
        f"1. Переведите {amount}₸ на указанные реквизиты\n"
        f"2. Сохраните скриншот чека перевода\n"
        f"3. Вернитесь в этот чат и отправьте скриншот\n"
        f"4. Мы активируем подписку в течение 24 часов\n\n"
        f"💬 <b>Поддержка:</b> {Config.SUPPORT_CONTACT}\n\n"
        f"⚠️ <i>В комментарии к переводу укажите: {plan}</i>"
    )
    
    return instructions

# ===== КРАСИВЫЙ СПИСОК АНКЕТ =====
async def generate_beautiful_profiles_list(profiles, title="📋 СПИСОК АНКЕТ"):
    """Генерирует красивый форматированный список анкет"""
    if not profiles:
        return "📭 Пока нет анкет."
    
    list_text = f"{title}\n\n"
    
    for i, profile in enumerate(profiles, 1):
        name = profile['name']
        role = profile['role']
        age = profile['age']
        city = profile['city']
        bio = profile['bio']
        
        # Обрезаем био для preview
        bio_preview = bio[:80] + "..." if len(bio) > 80 else bio
        
        # Красивое форматирование с рамками
        list_text += f"┌{'─' * 35}┐\n"
        list_text += f"│ <b>#{i}. {name}</b>\n"
        list_text += f"│ 🎭 <b>Роль:</b> {role}\n"
        list_text += f"│ 🎂 <b>Возраст:</b> {age}\n"
        list_text += f"│ 🏙️ <b>Город:</b> {city}\n"
        list_text += f"│ 📝 <b>О себе:</b> {bio_preview}\n"
        list_text += f"└{'─' * 35}┘\n\n"
    
    list_text += f"📊 <b>Всего анкет:</b> {len(profiles)}"
    
    return list_text

# ===== КОМАНДЫ БОТА =====
@dp.message(Command("start"))
async def start_command(message: types.Message):
    welcome_text = (
        "👋 <b>Добро пожаловать в бот для анкет!</b>\n\n"
        "📝 <b>Создать анкету</b> - заполните информацию о себе\n"
        "👤 <b>Моя анкета</b> - посмотреть свою анкету\n"
        "🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей\n"
        "📋 <b>Список анкет</b> - красивый список всех анкет\n"
        "💰 <b>Тарифы</b> - информация о премиум подписке\n"
        "📊 <b>Статистика</b> - статистика бота\n"
        "ℹ️ <b>Помощь</b> - показать это сообщение\n\n"
        "<i>Выберите действие на клавиатуре ниже 👇</i>"
    )
    await message.answer(welcome_text, reply_markup=get_main_menu())

@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Помощь")
async def help_command(message: types.Message):
    help_text = (
        "📋 <b>Доступные команды:</b>\n\n"
        "📝 <b>Создать анкету</b> - заполните информацию о себе\n"
        "👤 <b>Моя анкета</b> - посмотреть свою анкету\n"
        "🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей\n"
        "📋 <b>Список анкет</b> - красивый список всех анкет\n"
        "💰 <b>Тарифы</b> - информация о премиум подписке\n\n"
        "<b>Команды:</b>\n"
        "/start - главное меню\n"
        "/help - эта справка\n" 
        "/delete - удалить свою анкету\n"
        "/report - пожаловаться на пользователя\n"
        "/list - список одобренных анкет\n"
        "/stats - статистика\n"
        "/buy - купить премиум подписку"
    )
    await message.answer(help_text, reply_markup=get_main_menu())

# ===== КРАСИВЫЙ СПИСОК АНКЕТ =====
@dp.message(Command("list"))
@dp.message(F.text == "📋 Список анкет")
async def list_profiles(message: types.Message):
    try:
        async with pool.acquire() as conn:
            profiles = await conn.fetch(
                "SELECT name, role, age, city, bio FROM profiles WHERE status = 'approved' AND is_active = true ORDER BY created_at DESC LIMIT 50"
            )
            
            list_text = await generate_beautiful_profiles_list(profiles)
            
            if len(list_text) > 4000:
                chunks = [list_text[i:i+4000] for i in range(0, len(list_text), 4000)]
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(list_text)
                
            await message.answer(
                "👀 <b>Используйте поиск для просмотра фото анкет</b>",
                reply_markup=get_main_menu()
            )
                
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

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

<b>Базовый - {Config.PRICES['basic_month']}₸/месяц</b>
• До 3 анкет
• 15 поисков в день
• Приоритетная модерация (24 часа)
• Поддержка 24/7

<b>Профи - {Config.PRICES['pro_month']}₸/месяц</b>
• До 10 анкет
• 30 поисков в день  
• Срочная модерация (12 часов)
• Приоритет в поиске
• Поддержка 24/7

<b>Премиум - {Config.PRICES['premium_month']}₸/месяц</b>
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
    
    async with pool.acquire() as conn:
        # ПРОВЕРКА: есть ли уже активный pending платеж
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
    
    async with pool.acquire() as conn:
        # ДВОЙНАЯ ПРОВЕРКА: есть ли уже активный pending платеж
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
    
    await state.update_data(
        bank=bank,
        plan=plan,
        amount=Config.PRICES[plan],
        user_id=callback.from_user.id
    )
    
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
    
    try:
        async with pool.acquire() as conn:
            # ТРОЙНАЯ ПРОВЕРКА: есть ли уже активный pending платеж
            active_payment = await conn.fetchrow(
                "SELECT id FROM payments WHERE user_id = $1 AND status = 'pending'",
                message.from_user.id
            )
            
            if active_payment:
                await message.answer(
                    "❌ У вас уже есть платеж на проверке. Дождитесь его обработки.",
                    reply_markup=get_main_menu()
                )
                await state.clear()
                return
            
            # Сохраняем платеж
            await conn.execute(
                "INSERT INTO payments (user_id, amount, plan, status, screenshot_file_id) VALUES ($1, $2, $3, 'pending', $4)",
                message.from_user.id, user_data['amount'], user_data['plan'], photo
            )
    except Exception as e:
        print(f"❌ Ошибка сохранения платежа: {e}")
        await message.answer("❌ Ошибка при сохранении платежа", reply_markup=get_main_menu())
        await state.clear()
        return
    
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
    sent_count = 0
    for admin_id in [Config.ADMIN_ID] + Config.MODERATORS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=photo,
                caption=payment_text,
                reply_markup=payment_keyboard
            )
            sent_count += 1
        except Exception as e:
            print(f"❌ Не удалось отправить уведомление админу {admin_id}: {e}")
    
    if sent_count == 0:
        await message.answer("❌ Не удалось уведомить администраторов", reply_markup=get_main_menu())
    else:
        await message.answer(
            "✅ Скриншот отправлен на проверку!\n\n"
            "Мы активируем вашу подписку в течение 24 часов после проверки платежа.\n"
            "Спасибо за покупку! ❤️",
            reply_markup=get_main_menu()
        )
    
    await state.clear()

# ===== ИСПРАВЛЕННЫЕ ОБРАБОТЧИКИ ПЛАТЕЖЕЙ =====
@dp.callback_query(F.data.startswith("confirm_payment_"))
async def confirm_payment(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ Только для модераторов", show_alert=True)
        return
    
    try:
        data_parts = callback.data.replace("confirm_payment_", "").split("_")
        user_id = int(data_parts[0])
        plan = data_parts[1]
        
        print(f"🔧 DEBUG: Подтверждение платежа - user_id: {user_id}, plan: {plan}")
        
        async with pool.acquire() as conn:
            # Находим pending платеж
            payment = await conn.fetchrow(
                "SELECT id, amount FROM payments WHERE user_id = $1 AND plan = $2 AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                user_id, plan
            )
            
            if not payment:
                await callback.answer("❌ Платеж не найден или уже обработан", show_alert=True)
                return
            
            # Обновляем статус платежа
            await conn.execute(
                "UPDATE payments SET status = 'completed' WHERE id = $1",
                payment['id']
            )
            
            # Активируем подписку
            success, message = await create_subscription(user_id, plan)
            
            if success:
                # Обновляем сообщение
                await callback.message.edit_text(
                    f"✅ <b>Платеж подтвержден!</b>\n\n"
                    f"👤 <b>Пользователь:</b> {user_id}\n"
                    f"📋 <b>Тариф:</b> {plan}\n"
                    f"💵 <b>Сумма:</b> {payment['amount']}₸\n"
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
        
        async with pool.acquire() as conn:
            # Находим pending платеж
            payment = await conn.fetchrow(
                "SELECT id FROM payments WHERE user_id = $1 AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                user_id
            )
            
            if not payment:
                await callback.answer("❌ Платеж не найден или уже обработан", show_alert=True)
                return
            
            # Обновляем статус платежа
            await conn.execute(
                "UPDATE payments SET status = 'rejected' WHERE id = $1",
                payment['id']
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

# ===== СИСТЕМА "КТО ПЕРВЫЙ ВЗЯЛ" - МОДЕРАЦИЯ =====
@dp.callback_query(F.data.startswith("take_"))
async def handle_take_moderation(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ У вас нет прав модератора", show_alert=True)
        return
    
    profile_id = int(callback.data.replace("take_", ""))
    await take_moderation(callback, profile_id)

@dp.callback_query(F.data.startswith(("approve_", "reject_", "ban_")))
async def handle_moderation(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ У вас нет прав модератора", show_alert=True)
        return
    
    action, target_id = callback.data.split("_")
    target_id = int(target_id)
    
    try:
        async with pool.acquire() as conn:
            
            if action in ["approve", "reject"]:
                # Для действий с анкетами
                profile_id = target_id
                
                # Проверяем, взял ли текущий модератор эту анкету
                moderation_info = await conn.fetchrow(
                    "SELECT moderator_id FROM active_moderations WHERE profile_id = $1",
                    profile_id
                )
                
                if moderation_info and moderation_info['moderator_id'] != callback.from_user.id and not is_admin(callback.from_user.id):
                    await callback.answer(
                        f"❌ Эту анкету взял другой модератор", 
                        show_alert=True
                    )
                    return
                
                profile = await conn.fetchrow(
                    "SELECT user_id, name FROM profiles WHERE id = $1",
                    profile_id
                )
                
                if not profile:
                    await callback.answer("❌ Анкета не найдена", show_alert=True)
                    return
                
                user_id = profile['user_id']
                
                if action == "approve":
                    await conn.execute(
                        "UPDATE profiles SET status = 'approved', moderated_by = $1 WHERE id = $2",
                        callback.from_user.id, profile_id
                    )
                    try:
                        await bot.send_message(
                            user_id, 
                            f"🎉 Ваша анкета '{profile['name']}' одобрена модератором!"
                        )
                    except:
                        pass
                    await callback.answer("✅ Анкета одобрена")
                    
                elif action == "reject":
                    await conn.execute(
                        "UPDATE profiles SET status = 'rejected', moderated_by = $1 WHERE id = $2",
                        callback.from_user.id, profile_id
                    )
                    try:
                        await bot.send_message(
                            user_id,
                            f"❌ Ваша анкета '{profile['name']}' отклонена модератором."
                        )
                    except:
                        pass
                    await callback.answer("❌ Анкета отклонена")
                
                # Удаляем из активных модераций
                await conn.execute("DELETE FROM active_moderations WHERE profile_id = $1", profile_id)
                
            elif action == "ban":
                # Для бана пользователя
                user_id = target_id
                
                await conn.execute(
                    "INSERT INTO banned_users (user_id, reason, banned_by) VALUES ($1, $2, $3)",
                    user_id, "Нарушение правил", callback.from_user.id
                )
                
                # Деактивируем все анкеты пользователя
                await conn.execute(
                    "UPDATE profiles SET is_active = FALSE WHERE user_id = $1",
                    user_id
                )
                
                try:
                    await bot.send_message(user_id, "🚫 Ваш аккаунт заблокирован модератором.")
                except:
                    pass
                await callback.answer("✅ Пользователь забанен")
            
            # Убираем клавиатуру у сообщения
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.edit_text(
                    f"{callback.message.text}\n\n"
                    f"✅ <b>Обработано модератором: {callback.from_user.first_name}</b>\n"
                    f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                )
            except:
                pass
            
    except Exception as e:
        print(f"❌ Ошибка модерации: {e}")
        await callback.answer("❌ Ошибка при обработке", show_alert=True)

# ===== СОЗДАНИЕ АНКЕТЫ =====
@dp.message(F.text == "📝 Создать анкету")
async def start_anketa(message: types.Message, state: FSMContext):
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
                reply_markup=get_main_menu()
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
    await message.answer("Заполнение анкеты отменено", reply_markup=get_main_menu())

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
    await message.answer("Расскажите о себе:")
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
        
        success, action, profile_id = await save_profile(
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
            moderation_sent, message_ids = await notify_all_moderators(
                profile_id,
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
                           f"⏳ <i>Ожидайте решения модератора. Кто первый возьмет - тот и проверит!</i>",
                    reply_markup=get_main_menu()
                )
            else:
                await message.answer("❌ Ошибка отправки на модерацию", reply_markup=get_main_menu())
            
            await state.clear()
        else:
            await message.answer(f"❌ Ошибка: {action}", reply_markup=get_main_menu())
            await state.clear()
        
    except Exception as e:
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=get_main_menu())
        await state.clear()

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
                "SELECT * FROM profiles WHERE user_id = $1 AND is_active = TRUE", 
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
                    reply_markup=get_main_menu()
                )
            else:
                await message.answer("У вас нет активной анкеты. Создайте её!", reply_markup=get_main_menu())
                
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(F.text == "🔍 Найти анкеты")
@dp.message(Command("search"))
async def search_profiles(message: types.Message):
    can_search, searches_left = await check_search_limit(message.from_user.id)
    
    if not can_search:
        await message.answer(
            f"❌ Вы исчерпали лимит поисков на сегодня ({Config.FREE_DAILY_SEARCHES} в день).\n\n"
            "💎 <b>Премиум подписка</b> снимает все ограничения!\n"
            "Нажмите '💰 Тарифы' для получения информации.",
            reply_markup=get_main_menu()
        )
        return
    
    try:
        async with pool.acquire() as conn:
            profiles = await conn.fetch(
                "SELECT name, role, age, city, bio, photo FROM profiles WHERE user_id != $1 AND status = 'approved' AND is_active = true ORDER BY RANDOM() LIMIT 3",
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
                        f"⚠️ <i>Чтобы пожаловаться на анкету, используйте команду /report</i>"
                    )
                    await message.answer_photo(photo=photo, caption=caption)
                    
                if searches_left > 0:
                    await message.answer(f"🔍 Осталось поисков сегодня: {searches_left}")
            else:
                await message.answer("Пока нет других анкет.", reply_markup=get_main_menu())
                
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# ===== СТАТИСТИКА =====
@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика")
async def stats_command(message: types.Message):
    try:
        async with pool.acquire() as conn:
            total_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles")
            pending_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE status = 'pending'")
            approved_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE status = 'approved'")
            
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

# ===== ЗАПУСК БОТА =====
async def main():
    await init_db()
    print("🤖 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())