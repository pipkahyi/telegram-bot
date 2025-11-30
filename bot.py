import asyncpg
import asyncio
import re
import time
import logging
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
import json

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== УЛУЧШЕННАЯ КОНФИГУРАЦИЯ =====
class Config:
    DATABASE_URL = "postgresql://neondb_owner:npg_g9V7oqFCiZwY@ep-bold-sunset-ahlhp31q-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    BOT_TOKEN = "8240552495:AAF-g-RGQKzxIGuXs5PQZwf1Asp6hIJ93U4"
    
    ADMIN_ID = 7788088499
    MODERATORS = [7788088499]
    
    MODERATION_GROUP_ID = -5069006369 
    MODERATION_TYPE = "group"
    
    # Защита от спама
    SPAM_LIMIT = 8
    SPAM_WINDOW = 15
    BAN_DURATION = 7200
    
    # Фильтр плохих слов
    BAD_WORDS = ['котакбас', 'секс', 'порно', 'дошан', 'тошан', 'котак', 'еблан', 'hui', 'pizda']
    
    # Лимиты
    FREE_MAX_PROFILES = 1
    FREE_DAILY_SEARCHES = 8
    PREMIUM_MAX_PROFILES = 10
    VIP_MAX_PROFILES = 50
    
    # Тарифы (в тенге)
    PRICES = {
        'basic_month': 2000,
        'pro_month': 5000, 
        'premium_month': 12000,
        'vip_month': 25000,
    }
    
    # Реквизиты
    PAYMENT_DETAILS = {
        'kaspi': '+7 702 473 8282',
        'halyk': '4400 4301 1234 5678',
        'jusan': '1234 5678 9012 3456',
    }
    
    # Поддержка
    SUPPORT_CONTACT = "@Baeline"
    
    # Настройки групп
    GROUP_SETTINGS = {
        'auto_approval': False,
        'max_profiles_per_user': 3,
        'moderation_timeout': 24,  # часов
    }

# ===== УЛУЧШЕННЫЕ СОСТОЯНИЯ =====
class ProfileStates(StatesGroup):
    waiting_name = State()
    waiting_role = State()
    waiting_age = State()
    waiting_city = State()
    waiting_bio = State()
    waiting_photo = State()
    editing_profile = State()

class PaymentStates(StatesGroup):
    waiting_screenshot = State()
    selecting_plan = State()
    selecting_bank = State()

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_ban_reason = State()

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
pool = None

# ===== УЛУЧШЕННАЯ СИСТЕМА ЗАЩИТЫ =====
class ProtectionSystem:
    def __init__(self):
        self.user_cooldowns = defaultdict(dict)
        self.login_attempts = defaultdict(int)
    
    def is_spamming(self, user_id):
        now = time.time()
        if user_id not in self.user_cooldowns:
            self.user_cooldowns[user_id] = {'messages': [], 'banned_until': 0}
        
        user_data = self.user_cooldowns[user_id]
        
        if user_data['banned_until'] > now:
            return True
        
        user_data['messages'] = [msg_time for msg_time in user_data['messages'] 
                               if now - msg_time < Config.SPAM_WINDOW]
        
        if len(user_data['messages']) >= Config.SPAM_LIMIT:
            user_data['banned_until'] = now + Config.BAN_DURATION
            logger.warning(f"🚫 Пользователь {user_id} заблокирован за спам")
            return True
        
        user_data['messages'].append(now)
        return False
    
    def reset_cooldown(self, user_id):
        if user_id in self.user_cooldowns:
            del self.user_cooldowns[user_id]

protection = ProtectionSystem()

# ===== УЛУЧШЕННАЯ ВАЛИДАЦИЯ =====
class Validator:
    @staticmethod
    def validate_name(name):
        name = name.strip()
        if len(name) < 2 or len(name) > 50:
            return False, "❌ Имя должно быть от 2 до 50 символов"
        if not re.match(r'^[a-zA-Zа-яА-ЯёЁ\s\-]+$', name):
            return False, "❌ Имя может содержать только буквы, пробелы и дефисы"
        if any(bad_word in name.lower() for bad_word in Config.BAD_WORDS):
            return False, "❌ Имя содержит запрещенные слова"
        return True, ""

    @staticmethod
    def validate_age(age_text):
        if not age_text.isdigit():
            return False, "❌ Пожалуйста, введите число"
        
        age = int(age_text)
        if age < 12 or age > 100:
            return False, "❌ Возраст должен быть от 12 до 100 лет"
        return True, age

    @staticmethod
    def validate_city(city):
        city = city.strip()
        if len(city) < 2 or len(city) > 50:
            return False, "❌ Название города должно быть от 2 до 50 символов"
        return True, city

    @staticmethod
    def validate_bio(bio):
        bio = bio.strip()
        if len(bio) < 10:
            return False, "❌ Расскажите о себе подробнее (минимум 10 символов)"
        if len(bio) > 1000:
            return False, "❌ Слишком длинный текст (максимум 1000 символов)"
        if any(bad_word in bio.lower() for bad_word in Config.BAD_WORDS):
            return False, "❌ Текст содержит запрещенные слова"
        return True, bio

validator = Validator()

# ===== УЛУЧШЕННАЯ БАЗА ДАННЫХ =====
class Database:
    def __init__(self, pool):
        self.pool = pool
    
    async def init_tables(self):
        """Инициализация всех таблиц"""
        tables = [
            # Таблица профилей
            """
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
                updated_at TIMESTAMP DEFAULT NOW(),
                views_count INTEGER DEFAULT 0
            )
            """,
            # Таблица банов
            """
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY,
                reason TEXT NOT NULL,
                banned_by BIGINT NOT NULL,
                banned_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP
            )
            """,
            # Таблица активных модераций
            """
            CREATE TABLE IF NOT EXISTS active_moderations (
                id SERIAL PRIMARY KEY,
                profile_id INTEGER NOT NULL REFERENCES profiles(id),
                moderator_id BIGINT NOT NULL,
                moderator_name TEXT,
                taken_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(profile_id)
            )
            """,
            # Таблица подписок
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id BIGINT PRIMARY KEY,
                plan TEXT NOT NULL,
                starts_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
            # Таблица поисковых запросов
            """
            CREATE TABLE IF NOT EXISTS search_usage (
                user_id BIGINT,
                search_date DATE DEFAULT CURRENT_DATE,
                search_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, search_date)
            )
            """,
            # Таблица платежей
            """
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                plan TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                screenshot_file_id TEXT,
                bank TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                processed_at TIMESTAMP
            )
            """,
            # Таблица статистики
            """
            CREATE TABLE IF NOT EXISTS bot_stats (
                date DATE PRIMARY KEY,
                users_count INTEGER DEFAULT 0,
                profiles_count INTEGER DEFAULT 0,
                payments_count INTEGER DEFAULT 0,
                revenue INTEGER DEFAULT 0
            )
            """
        ]
        
        async with self.pool.acquire() as conn:
            for table in tables:
                await conn.execute(table)
            logger.info("✅ Все таблицы инициализированы")

    async def get_user_profile(self, user_id):
        """Получить профиль пользователя"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM profiles WHERE user_id = $1 AND is_active = TRUE ORDER BY created_at DESC LIMIT 1",
                user_id
            )
    
    async def get_active_subscription(self, user_id):
        """Получить активную подписку"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE user_id = $1 AND expires_at > NOW()",
                user_id
            )
    
    async def create_payment(self, user_id, amount, plan, bank, screenshot_file_id=None):
        """Создать запись о платеже"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """INSERT INTO payments (user_id, amount, plan, bank, screenshot_file_id, status) 
                VALUES ($1, $2, $3, $4, $5, 'pending') RETURNING id""",
                user_id, amount, plan, bank, screenshot_file_id
            )
    
    async def get_pending_payments(self):
        """Получить ожидающие платежи"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM payments WHERE status = 'pending' ORDER BY created_at DESC"
            )

# ===== КЛАВИАТУРЫ =====
class Keyboards:
    @staticmethod
    def get_main_menu():
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📝 Создать анкету"), KeyboardButton(text="👤 Моя анкета")],
                [KeyboardButton(text="🔍 Найти анкеты"), KeyboardButton(text="📋 Список анкет")],
                [KeyboardButton(text="💎 Тарифы"), KeyboardButton(text="📊 Статистика")],
                [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="⭐ Премиум")]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    def get_cancel_menu():
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True
        )
    
    @staticmethod
    def get_premium_menu():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Базовый - 2,000₸/мес", callback_data="buy_basic_month")],
            [InlineKeyboardButton(text="💎 Профи - 5,000₸/мес", callback_data="buy_pro_month")],
            [InlineKeyboardButton(text="👑 Премиум - 12,000₸/мес", callback_data="buy_premium_month")],
            [InlineKeyboardButton(text="⚡ VIP - 25,000₸/мес", callback_data="buy_vip_month")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
        ])
    
    @staticmethod
    def get_bank_menu(plan):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏦 Kaspi Bank", callback_data=f"bank_kaspi_{plan}")],
            [InlineKeyboardButton(text="🏦 Halyk Bank", callback_data=f"bank_halyk_{plan}")],
            [InlineKeyboardButton(text="🏦 Jusan Bank", callback_data=f"bank_jusan_{plan}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_plans")]
        ])
    
    @staticmethod
    def get_profile_actions(profile_id):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_profile_{profile_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_profile_{profile_id}")]
        ])
    
    @staticmethod
    def get_moderation_keyboard(profile_id):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨‍💻 Взять в работу", callback_data=f"take_{profile_id}")]
        ])
    
    @staticmethod
    def get_moderation_actions(profile_id, user_id):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{profile_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{profile_id}")],
            [InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{user_id}")],
            [InlineKeyboardButton(text="⏱️ Отложить", callback_data=f"delay_{profile_id}")]
        ])

# ===== ТЕКСТЫ СООБЩЕНИЙ =====
class Messages:
    WELCOME = """
👋 <b>Добро пожаловать в бот для анкет!</b>

📝 <b>Создать анкету</b> - заполните информацию о себе
👤 <b>Моя анкета</b> - посмотреть свою анкету  
🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей
📋 <b>Список анкет</b> - красивый список всех анкет
💎 <b>Тарифы</b> - информация о премиум подписке
📊 <b>Статистика</b> - статистика бота
⭐ <b>Премиум</b> - купить подписку

<i>Выберите действие на клавиатуре ниже 👇</i>
    """
    
    HELP = """
📋 <b>Доступные команды:</b>

📝 <b>Создать анкету</b> - заполните информацию о себе
👤 <b>Моя анкета</b> - посмотреть свою анкету
🔍 <b>Найти анкеты</b> - посмотреть анкеты других пользователей
📋 <b>Список анкет</b> - красивый список всех анкет
💎 <b>Тарифы</b> - информация о премиум подписке

<b>Команды:</b>
/start - главное меню
/help - эта справка
/delete - удалить свою анкету
/list - список одобренных анкет
/stats - статистика
/buy - купить премиум подписку
    """
    
    PRICING = """
💎 <b>Тарифы бота</b>

🎯 <b>Бесплатный тариф:</b>
• 1 анкета
• 8 поисков в день  
• Базовая функциональность
• Ожидание модерации 1-3 дня

💎 <b>Премиум подписка:</b>

<b>💰 Базовый - 2,000₸/месяц</b>
• До 3 анкет
• 20 поисков в день
• Приоритетная модерация (24 часа)
• Поддержка 24/7

<b>💎 Профи - 5,000₸/месяц</b>
• До 10 анкет
• 50 поисков в день  
• Срочная модерация (12 часов)
• Приоритет в поиске
• Поддержка 24/7

<b>👑 Премиум - 12,000₸/месяц</b>
• До 25 анкет
• Неограниченный поиск
• Мгновенная модерация (1-6 часов)
• Максимальный приоритет в поиске
• Расширенная статистика
• Поддержка 24/7

<b>⚡ VIP - 25,000₸/месяц</b>
• Неограниченное количество анкет
• Неограниченный поиск
• Мгновенная модерация (до 1 часа)
• Высший приоритет
• Персональная поддержка
• Доступ к beta-функциям

👇 <b>Выберите тариф:</b>
    """

# ===== СИСТЕМА ПОДПИСОК =====
class SubscriptionService:
    def __init__(self, db):
        self.db = db
    
    async def create_subscription(self, user_id, plan):
        """Создать подписку"""
        plan_durations = {
            'basic_month': 30,
            'pro_month': 30,
            'premium_month': 30,
            'vip_month': 30
        }
        
        duration_days = plan_durations.get(plan, 30)
        expires_at = datetime.now() + timedelta(days=duration_days)
        
        async with self.db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO subscriptions (user_id, plan, expires_at) 
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) 
                DO UPDATE SET plan = $2, expires_at = $3, starts_at = NOW()
            """, user_id, plan, expires_at)
            
            return True, f"✅ Подписка активирована на {duration_days} дней!"
    
    async def get_user_limits(self, user_id):
        """Получить лимиты пользователя"""
        subscription = await self.db.get_active_subscription(user_id)
        
        if subscription:
            plan = subscription['plan']
            if plan == 'vip_month':
                return {'max_profiles': Config.VIP_MAX_PROFILES, 'daily_searches': None, 'is_premium': True}
            elif plan == 'premium_month':
                return {'max_profiles': 25, 'daily_searches': None, 'is_premium': True}
            elif plan == 'pro_month':
                return {'max_profiles': 10, 'daily_searches': 50, 'is_premium': True}
            elif plan == 'basic_month':
                return {'max_profiles': 3, 'daily_searches': 20, 'is_premium': True}
        
        return {'max_profiles': Config.FREE_MAX_PROFILES, 'daily_searches': Config.FREE_DAILY_SEARCHES, 'is_premium': False}
    
    async def check_search_limit(self, user_id):
        """Проверить лимит поисков"""
        limits = await self.get_user_limits(user_id)
        
        if limits['daily_searches'] is None:  # Безлимит
            return True, 0
        
        async with self.db.pool.acquire() as conn:
            today = datetime.now().date()
            usage = await conn.fetchrow(
                "SELECT search_count FROM search_usage WHERE user_id = $1 AND search_date = $2",
                user_id, today
            )
            
            if not usage:
                return True, limits['daily_searches']
            
            searches_left = limits['daily_searches'] - usage['search_count']
            return searches_left > 0, searches_left

# ===== ИНИЦИАЛИЗАЦИЯ СЕРВИСОВ =====
async def init_services():
    global pool, db, subscription_service
    try:
        pool = await asyncpg.create_pool(Config.DATABASE_URL)
        logger.info("✅ Подключение к PostgreSQL установлено")
        
        db = Database(pool)
        await db.init_tables()
        
        subscription_service = SubscriptionService(db)
        
        logger.info("✅ Все сервисы инициализированы")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации сервисов: {e}")
        return False

# ===== MIDDLEWARE ЗАЩИТЫ =====
@dp.message.middleware
async def protection_middleware(handler, event: types.Message, data):
    user_id = event.from_user.id
    
    if protection.is_spamming(user_id):
        await event.answer("🚫 Слишком много запросов. Попробуйте позже.")
        return
    
    if await is_user_banned(user_id):
        await event.answer("🚫 Ваш аккаунт заблокирован.")
        return
    
    return await handler(event, data)

# ===== ОСНОВНЫЕ КОМАНДЫ =====
@dp.message(Command("start"))
async def start_command(message: types.Message):
    await message.answer(Messages.WELCOME, reply_markup=Keyboards.get_main_menu())

@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Помощь")
async def help_command(message: types.Message):
    await message.answer(Messages.HELP, reply_markup=Keyboards.get_main_menu())

# ===== СИСТЕМА АНКЕТ =====
@dp.message(F.text == "📝 Создать анкету")
async def start_anketa(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверяем лимиты
    limits = await subscription_service.get_user_limits(user_id)
    async with pool.acquire() as conn:
        profile_count = await conn.fetchval(
            "SELECT COUNT(*) FROM profiles WHERE user_id = $1 AND is_active = TRUE",
            user_id
        )
    
    if profile_count >= limits['max_profiles']:
        if limits['is_premium']:
            await message.answer(
                f"❌ Вы достигли лимита анкет для вашего тарифа ({limits['max_profiles']} анкет).\n"
                f"Удалите одну из старых анкет чтобы создать новую.",
                reply_markup=Keyboards.get_main_menu()
            )
        else:
            await message.answer(
                f"❌ Вы достигли лимита бесплатных анкет (1 анкета).\n\n"
                "💎 <b>Премиум подписка</b> позволяет создавать до 25 анкет!\n"
                "Нажмите '💎 Тарифы' для получения информации.",
                reply_markup=Keyboards.get_main_menu()
            )
        return

    await message.answer(
        "📝 <b>Давайте создадим вашу анкету!</b>\n\n"
        "Как вас зовут? (Имя и фамилия)\n\n"
        "<i>💡 Пример: Айдар Касенов</i>",
        reply_markup=Keyboards.get_cancel_menu()
    )
    await state.set_state(ProfileStates.waiting_name)

@dp.message(ProfileStates.waiting_name)
async def process_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
    
    is_valid, error_msg = validator.validate_name(message.text)
    if not is_valid:
        await message.answer(f"{error_msg}\n\nПопробуйте еще раз:")
        return
    
    await state.update_data(name=message.text.strip())
    await message.answer(
        "🎭 <b>Напишите вашу роль:</b>\n\n"
        "<i>💡 Пример: Администратор, Модератор, Дизайнер, HR</i>",
        reply_markup=Keyboards.get_cancel_menu()
    )
    await state.set_state(ProfileStates.waiting_role)

@dp.message(ProfileStates.waiting_role)
async def process_role(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
    
    role = message.text.strip()
    if len(role) < 2:
        await message.answer("❌ Роль должна содержать минимум 2 символа. Попробуйте еще раз:")
        return
    if len(role) > 50:
        await message.answer("❌ Роль должна быть не длиннее 50 символов. Попробуйте еще раз:")
        return
    
    await state.update_data(role=role)
    await message.answer(
        "🎂 <b>Сколько вам лет?</b>\n\n"
        "<i>💡 Введите число от 12 до 100</i>",
        reply_markup=Keyboards.get_cancel_menu()
    )
    await state.set_state(ProfileStates.waiting_age)

@dp.message(ProfileStates.waiting_age)
async def process_age(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
    
    is_valid, result = validator.validate_age(message.text)
    if not is_valid:
        await message.answer(f"{result}\n\nПопробуйте еще раз:")
        return
    
    await state.update_data(age=result)
    await message.answer(
        "🏙️ <b>Из какого вы города?</b>\n\n"
        "<i>💡 Пример: Алматы, Астана, Шымкент</i>",
        reply_markup=Keyboards.get_cancel_menu()
    )
    await state.set_state(ProfileStates.waiting_city)

@dp.message(ProfileStates.waiting_city)
async def process_city(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
    
    is_valid, result = validator.validate_city(message.text)
    if not is_valid:
        await message.answer(f"{result}\n\nПопробуйте еще раз:")
        return
    
    await state.update_data(city=result)
    await message.answer(
        "📝 <b>Расскажите о себе:</b>\n\n"
        "<i>💡 Опишите ваши навыки, опыт, интересы\n"
        "Минимум 10 символов, максимум 1000</i>",
        reply_markup=Keyboards.get_cancel_menu()
    )
    await state.set_state(ProfileStates.waiting_bio)

@dp.message(ProfileStates.waiting_bio)
async def process_bio(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
    
    is_valid, result = validator.validate_bio(message.text)
    if not is_valid:
        await message.answer(f"{result}\n\nПопробуйте еще раз:")
        return
    
    await state.update_data(bio=result)
    await message.answer(
        "📸 <b>Отлично! Теперь отправьте ваше фото:</b>\n\n"
        "<i>💡 Лучше всего подойдет четкое фото лица</i>",
        reply_markup=Keyboards.get_cancel_menu()
    )
    await state.set_state(ProfileStates.waiting_photo)

@dp.message(ProfileStates.waiting_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        photo_file_id = message.photo[-1].file_id
        
        # Сохраняем анкету в базу
        async with pool.acquire() as conn:
            # Проверяем существующую анкету
            existing_profile = await conn.fetchrow(
                "SELECT id FROM profiles WHERE user_id = $1 AND is_active = TRUE",
                message.from_user.id
            )
            
            if existing_profile:
                # Обновляем существующую
                await conn.execute("""
                    UPDATE profiles SET 
                    username = $1, name = $2, role = $3, age = $4, city = $5, 
                    bio = $6, photo = $7, updated_at = NOW(), status = 'pending'
                    WHERE id = $8
                """, message.from_user.username, user_data['name'], user_data['role'], 
                   user_data['age'], user_data['city'], user_data['bio'], photo_file_id, 
                   existing_profile['id'])
                profile_id = existing_profile['id']
                action = "обновлена"
            else:
                # Создаем новую
                result = await conn.fetchrow("""
                    INSERT INTO profiles 
                    (user_id, username, name, role, age, city, bio, photo) 
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                """, message.from_user.id, message.from_user.username, user_data['name'], 
                   user_data['role'], user_data['age'], user_data['city'], user_data['bio'], 
                   photo_file_id)
                profile_id = result['id']
                action = "создана"
        
        # Отправляем на модерацию
        moderation_sent = await send_to_moderation(profile_id, message.from_user.id, 
                                                 message.from_user.username, user_data, 
                                                 photo_file_id)
        
        if moderation_sent:
            await message.answer_photo(
                photo=photo_file_id,
                caption=f"✅ <b>Анкета успешно {action} и отправлена на модерацию!</b>\n\n"
                       f"👤 <b>Имя:</b> {user_data['name']}\n"
                       f"🎭 <b>Роль:</b> {user_data['role']}\n"
                       f"🎂 <b>Возраст:</b> {user_data['age']}\n"
                       f"🏙️ <b>Город:</b> {user_data['city']}\n"
                       f"📝 <b>О себе:</b> {user_data['bio'][:100]}...\n\n"
                       f"⏳ <i>Ожидайте решения модератора. Обычно это занимает 1-24 часа.</i>",
                reply_markup=Keyboards.get_main_menu()
            )
        else:
            await message.answer(
                "❌ Не удалось отправить анкету на модерацию. Попробуйте позже.",
                reply_markup=Keyboards.get_main_menu()
            )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания анкеты: {e}")
        await message.answer(
            "❌ Произошла ошибка при создании анкеты. Попробуйте снова.",
            reply_markup=Keyboards.get_main_menu()
        )
        await state.clear()

@dp.message(ProfileStates.waiting_photo, ~F.photo)
async def process_photo_invalid(message: types.Message, state: FSMContext):
    await message.answer("❌ Пожалуйста, отправьте фото для анкеты")

async def send_to_moderation(profile_id, user_id, username, user_data, photo_file_id):
    """Отправка анкеты на модерацию"""
    try:
        moderation_text = (
            "🆕 <b>НОВАЯ АНКЕТА НА МОДЕРАЦИЮ</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_data['name']} (ID: {user_id})\n"
            f"🔗 <b>Username:</b> @{username if username else 'нет'}\n"
            f"🎭 <b>Роль:</b> {user_data['role']}\n"
            f"🎂 <b>Возраст:</b> {user_data['age']}\n"
            f"🏙️ <b>Город:</b> {user_data['city']}\n"
            f"📝 <b>О себе:</b> {user_data['bio'][:200]}...\n\n"
            f"⏰ <b>Время подачи:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"<i>💡 Кто первый нажмет 'Взять в работу' - тот и проверяет!</i>"
        )
        
        if Config.MODERATION_TYPE == "group":
            try:
                await bot.send_photo(
                    chat_id=Config.MODERATION_GROUP_ID,
                    photo=photo_file_id,
                    caption=moderation_text,
                    reply_markup=Keyboards.get_moderation_keyboard(profile_id)
                )
                return True
            except Exception as e:
                logger.error(f"❌ Ошибка отправки в группу модерации: {e}")
                return False
        else:
            # Отправка каждому модератору
            sent_count = 0
            for moderator_id in [Config.ADMIN_ID] + Config.MODERATORS:
                try:
                    await bot.send_photo(
                        chat_id=moderator_id,
                        photo=photo_file_id,
                        caption=moderation_text,
                        reply_markup=Keyboards.get_moderation_keyboard(profile_id)
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"❌ Не удалось отправить модератору {moderator_id}: {e}")
            
            return sent_count > 0
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки на модерацию: {e}")
        return False

# ===== СИСТЕМА ПЛАТЕЖЕЙ =====
@dp.message(Command("buy"))
@dp.message(F.text == "⭐ Премиум")
@dp.message(F.text == "💎 Тарифы")
async def show_pricing(message: types.Message):
    await message.answer(Messages.PRICING, reply_markup=Keyboards.get_premium_menu())

@dp.callback_query(F.data.startswith("buy_"))
async def handle_plan_selection(callback: types.CallbackQuery):
    plan = callback.data.replace("buy_", "")
    
    if plan not in Config.PRICES:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    
    # Проверяем активные платежи
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
    
    bank_selection_text = f"""
💳 <b>Выбор способа оплаты</b>

📋 <b>Тариф:</b> {plan}
💵 <b>Сумма:</b> {Config.PRICES[plan]}₸

👇 <b>Выберите банк для оплаты:</b>
    """
    
    await callback.message.edit_text(
        bank_selection_text,
        reply_markup=Keyboards.get_bank_menu(plan)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("bank_"))
async def handle_bank_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = callback.data.replace("bank_", "")
        bank, plan = data.split("_", 1)
        
        # Проверяем активные платежи
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
        
        # Сохраняем данные
        await state.update_data(
            bank=bank,
            plan=plan,
            amount=Config.PRICES[plan]
        )
        
        # Генерируем инструкции
        plan_names = {
            'basic_month': 'Базовый (1 месяц)',
            'pro_month': 'Профи (1 месяц)', 
            'premium_month': 'Премиум (1 месяц)',
            'vip_month': 'VIP (1 месяц)'
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
        
        await callback.message.edit_text(
            instructions,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📎 Отправить скриншот", callback_data="send_screenshot")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_banks")]
            ])
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"❌ Ошибка выбора банка: {e}")
        await callback.answer("❌ Ошибка при выборе банка", show_alert=True)

@dp.callback_query(F.data == "send_screenshot")
async def handle_send_screenshot(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📎 <b>Отправьте скриншот перевода</b>\n\n"
        "Пожалуйста, отправьте скриншот или фото чека перевода для подтверждения оплаты.\n\n"
        "<i>💡 Убедитесь, что на скриншоте видна сумма, дата и реквизиты</i>",
        reply_markup=Keyboards.get_cancel_menu()
    )
    await state.set_state(PaymentStates.waiting_screenshot)
    await callback.answer()

@dp.message(PaymentStates.waiting_screenshot, F.photo)
async def process_payment_screenshot(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        photo_file_id = message.photo[-1].file_id
        
        # Проверяем наличие всех данных
        if not all(key in user_data for key in ['bank', 'plan', 'amount']):
            await message.answer(
                "❌ Ошибка: данные платежа не найдены. Начните процесс заново.",
                reply_markup=Keyboards.get_main_menu()
            )
            await state.clear()
            return
        
        # Проверяем активные платежи
        async with pool.acquire() as conn:
            active_payment = await conn.fetchrow(
                "SELECT id FROM payments WHERE user_id = $1 AND status = 'pending'",
                message.from_user.id
            )
            
            if active_payment:
                await message.answer(
                    "❌ У вас уже есть платеж на проверке. Дождитесь его обработки.",
                    reply_markup=Keyboards.get_main_menu()
                )
                await state.clear()
                return
            
            # Сохраняем платеж
            payment = await db.create_payment(
                message.from_user.id,
                user_data['amount'],
                user_data['plan'],
                user_data['bank'],
                photo_file_id
            )
        
        # Уведомляем администраторов
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
                InlineKeyboardButton(text="✅ Подтвердить", 
                                   callback_data=f"confirm_payment_{message.from_user.id}_{user_data['plan']}"),
                InlineKeyboardButton(text="❌ Отклонить", 
                                   callback_data=f"reject_payment_{message.from_user.id}")
            ]
        ])
        
        # Отправляем администраторам
        sent_count = 0
        for admin_id in [Config.ADMIN_ID] + Config.MODERATORS:
            try:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file_id,
                    caption=payment_text,
                    reply_markup=payment_keyboard
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"❌ Не удалось отправить уведомление админу {admin_id}: {e}")
        
        if sent_count == 0:
            await message.answer(
                "❌ Не удалось уведомить администраторов. Обратитесь в поддержку.",
                reply_markup=Keyboards.get_main_menu()
            )
        else:
            await message.answer(
                "✅ <b>Скриншот отправлен на проверку!</b>\n\n"
                "Мы активируем вашу подписку в течение 24 часов после проверки платежа.\n\n"
                "💬 По вопросам обращайтесь: {Config.SUPPORT_CONTACT}\n\n"
                "<i>Спасибо за покупку! ❤️</i>",
                reply_markup=Keyboards.get_main_menu()
            )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки скриншота: {e}")
        await message.answer(
            "❌ Произошла ошибка при обработке платежа. Попробуйте снова.",
            reply_markup=Keyboards.get_main_menu()
        )
        await state.clear()

# ===== ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ДЛЯ АДМИНОВ =====
@dp.callback_query(F.data.startswith("confirm_payment_"))
async def confirm_payment(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ Только для модераторов", show_alert=True)
        return
    
    try:
        data_parts = callback.data.replace("confirm_payment_", "").split("_")
        user_id = int(data_parts[0])
        plan = "_".join(data_parts[1:])
        
        logger.info(f"🔧 Подтверждение платежа - user_id: {user_id}, plan: {plan}")
        
        async with pool.acquire() as conn:
            # Находим платеж
            payment = await conn.fetchrow(
                """SELECT id, amount FROM payments 
                WHERE user_id = $1 AND plan = $2 AND status = 'pending' 
                ORDER BY created_at DESC LIMIT 1""",
                user_id, plan
            )
            
            if not payment:
                await callback.answer("❌ Платеж не найден или уже обработан", show_alert=True)
                return
            
            # Обновляем статус платежа
            await conn.execute(
                "UPDATE payments SET status = 'completed', processed_at = NOW() WHERE id = $1",
                payment['id']
            )
            
            # Активируем подписку
            success, message = await subscription_service.create_subscription(user_id, plan)
            
            if success:
                # Обновляем сообщение
                await callback.message.edit_text(
                    f"✅ <b>ПЛАТЕЖ ПОДТВЕРЖДЕН</b>\n\n"
                    f"👤 <b>Пользователь:</b> {user_id}\n"
                    f"📋 <b>Тариф:</b> {plan}\n"
                    f"💵 <b>Сумма:</b> {payment['amount']}₸\n"
                    f"👨‍💼 <b>Подтвердил:</b> {callback.from_user.first_name}\n"
                    f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                    reply_markup=None
                )
                
                # Уведомляем пользователя
                try:
                    plan_names = {
                        'basic_month': 'Базовый',
                        'pro_month': 'Профи', 
                        'premium_month': 'Премиум',
                        'vip_month': 'VIP'
                    }
                    await bot.send_message(
                        user_id,
                        f"🎉 <b>ВАШ ПЛАТЕЖ ПОДТВЕРЖДЕН!</b>\n\n"
                        f"💎 <b>Тариф:</b> {plan_names.get(plan, plan)}\n"
                        f"💵 <b>Сумма:</b> {payment['amount']}₸\n"
                        f"⏰ <b>Активировано:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                        f"Теперь вам доступны все возможности премиум-аккаунта! 🚀\n\n"
                        f"<i>Спасибо за покупку! ❤️</i>"
                    )
                except Exception as e:
                    logger.error(f"❌ Не удалось уведомить пользователя: {e}")
            else:
                await callback.message.edit_text(f"❌ Ошибка: {message}")
        
        await callback.answer("✅ Платеж подтвержден")
        
    except Exception as e:
        logger.error(f"❌ Ошибка подтверждения платежа: {e}")
        await callback.answer("❌ Ошибка при подтверждении платежа", show_alert=True)

@dp.callback_query(F.data.startswith("reject_payment_"))
async def reject_payment(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ Только для модераторов", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.replace("reject_payment_", ""))
        
        logger.info(f"🔧 Отклонение платежа - user_id: {user_id}")
        
        async with pool.acquire() as conn:
            payment = await conn.fetchrow(
                "SELECT id FROM payments WHERE user_id = $1 AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                user_id
            )
            
            if not payment:
                await callback.answer("❌ Платеж не найден или уже обработан", show_alert=True)
                return
            
            await conn.execute(
                "UPDATE payments SET status = 'rejected', processed_at = NOW() WHERE id = $1",
                payment['id']
            )
        
        await callback.message.edit_text(
            f"❌ <b>ПЛАТЕЖ ОТКЛОНЕН</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_id}\n"
            f"👨‍💼 <b>Отклонил:</b> {callback.from_user.first_name}\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            reply_markup=None
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                "❌ <b>ВАШ ПЛАТЕЖ БЫЛ ОТКЛОНЕН</b>\n\n"
                "Возможные причины:\n"
                "• Нечеткий или нечитаемый скриншот\n"
                "• Неправильная сумма перевода\n"
                "• Неверные реквизиты\n"
                "• Подозрительная активность\n\n"
                f"💬 Для уточнения обратитесь в поддержку: {Config.SUPPORT_CONTACT}\n\n"
                "Вы можете отправить платеж заново, исправив указанные ошибки."
            )
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить пользователя: {e}")
        
        await callback.answer("❌ Платеж отклонен")
        
    except Exception as e:
        logger.error(f"❌ Ошибка отклонения платежа: {e}")
        await callback.answer("❌ Ошибка при отклонении платежа", show_alert=True)

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
        logger.error(f"❌ Ошибка проверки бана: {e}")
        return False

async def cancel_anketa(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Заполнение анкеты отменено", reply_markup=Keyboards.get_main_menu())

# ===== ЗАПУСК БОТА =====
async def main():
    try:
        if await init_services():
            logger.info("🤖 Бот запущен и готов к работе!")
            await dp.start_polling(bot)
        else:
            logger.error("❌ Не удалось инициализировать сервисы")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске бота: {e}")
    finally:
        if pool:
            await pool.close()

if __name__ == "__main__":
    asyncio.run(main())