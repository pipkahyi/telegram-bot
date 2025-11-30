import asyncpg
import asyncio
import re
import time
import logging
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
from datetime import datetime, timedelta

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

# ===== КОНФИГУРАЦИЯ =====
class Config:
    DATABASE_URL = "postgresql://neondb_owner:npg_g9V7oqFCiZwY@ep-bold-sunset-ahlhp31q-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    BOT_TOKEN = "8240552495:AAF-g-RGQKzxIGuXs5PQZwf1Asp6hIJ93U4"
    
    ADMIN_ID = 7788088499
    MODERATORS = [7788088499]
    
    MODERATION_GROUP_ID = -5069006369 
    
    SPAM_LIMIT = 5
    SPAM_WINDOW = 10
    BAN_DURATION = 3600
    
    BAD_WORDS = ['Котакбас', 'Секс', 'Порно', 'Дошан', 'Тошан', 'Котак', 'Еблан']
    
    FREE_MAX_PROFILES = 1
    FREE_DAILY_SEARCHES = 5
    PREMIUM_MAX_PROFILES = 10
    
    PRICES = {
        'basic_month': 2000,
        'pro_month': 5000,
        'premium_month': 12000,
    }
    
    PAYMENT_DETAILS = {
        'kaspi': '+7 702 473 8282',
        'halyk': '4400 4301 1234 5678',
        'jusan': '1234 5678 9012 3456',
    }
    
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

# ===== РОУТЕРЫ ДЛЯ ОРГАНИЗАЦИИ КОДА =====
payment_router = Router()
profile_router = Router()
dp.include_router(payment_router)
dp.include_router(profile_router)

# ===== СИСТЕМА ЗАЩИТЫ =====
user_cooldowns = defaultdict(dict)

def contains_bad_words(text):
    if not text:
        return False
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

def get_cancel_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def get_premium_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Базовый - 2,000₸/мес", callback_data="buy_basic_month")],
        [InlineKeyboardButton(text="💎 Профи - 5,000₸/мес", callback_data="buy_pro_month")],
        [InlineKeyboardButton(text="👑 Премиум - 12,000₸/мес", callback_data="buy_premium_month")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
    ])

def get_bank_menu(plan):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 Kaspi Bank", callback_data=f"bank_kaspi_{plan}")],
        [InlineKeyboardButton(text="🏦 Halyk Bank", callback_data=f"bank_halyk_{plan}")],
        [InlineKeyboardButton(text="🏦 Jusan Bank", callback_data=f"bank_jusan_{plan}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
    ])

def get_payment_moderation_buttons(user_id, plan):
    """Создает кнопки для модерации платежа"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Подтвердить", 
                callback_data=f"confirm_payment_{user_id}_{plan}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить", 
                callback_data=f"reject_payment_{user_id}"
            )
        ]
    ])

# ===== БАЗА ДАННЫХ =====
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(Config.DATABASE_URL)
        logger.info("✅ Подключение к PostgreSQL установлено")
        
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
                    bank TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    processed_at TIMESTAMP
                )
            """)
            
            logger.info("✅ Таблицы созданы/проверены")
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        raise

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

async def check_user_limits(user_id):
    try:
        async with pool.acquire() as conn:
            subscription = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE user_id = $1 AND expires_at > NOW()",
                user_id
            )
            
            is_premium = subscription is not None
            
            profile_count = await conn.fetchval(
                "SELECT COUNT(*) FROM profiles WHERE user_id = $1 AND is_active = TRUE",
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
        logger.error(f"❌ Ошибка проверки лимитов: {e}")
        return {'can_create': False, 'profiles_left': 0, 'is_premium': False, 'max_profiles': 0}

async def check_search_limit(user_id):
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
        logger.error(f"❌ Ошибка проверки лимита поиска: {e}")
        return False, 0

async def increment_search_count(user_id):
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
        logger.error(f"❌ Ошибка увеличения счетчика поиска: {e}")

async def save_profile(user_id, username, name, role, age, city, bio, photo):
    try:
        async with pool.acquire() as conn:
            existing_profile = await conn.fetchrow(
                "SELECT id FROM profiles WHERE user_id = $1 AND is_active = TRUE", 
                user_id
            )
            
            if existing_profile:
                await conn.execute("""
                    UPDATE profiles SET 
                    username = $1, name = $2, role = $3, age = $4, city = $5, 
                    bio = $6, photo = $7, updated_at = NOW(), status = 'pending'
                    WHERE id = $8
                """, username, name, role, age, city, bio, photo, existing_profile['id'])
                profile_id = existing_profile['id']
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
        logger.error(f"❌ Ошибка сохранения профиля для user_id {user_id}: {e}")
        return False, str(e), None

async def create_subscription(user_id, plan):
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
        logger.error(f"❌ Ошибка создания подписки: {e}")
        return False, "Ошибка активации подписки"

async def generate_payment_instructions(plan, bank):
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

# ===== ОСНОВНЫЕ КОМАНДЫ =====
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
        "/list - список одобренных анкет\n"
        "/stats - статистика\n"
        "/buy - купить премиум подписку"
    )
    await message.answer(help_text, reply_markup=get_main_menu())

# ===== СИСТЕМА ПОДПИСОК И ПЛАТЕЖЕЙ =====
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
    
    await message.answer(pricing_text, reply_markup=get_premium_menu())

# Обработка выбора тарифа
@payment_router.callback_query(F.data.startswith("buy_"))
async def handle_payment_selection(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    plan = callback.data.replace("buy_", "")
    
    try:
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
        
    except Exception as e:
        logger.error(f"❌ Ошибка выбора тарифа: {e}")
        await callback.answer("❌ Ошибка при выборе тарифа", show_alert=True)

# Обработка выбора банка
@payment_router.callback_query(F.data.startswith("bank_"))
async def handle_bank_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = callback.data.replace("bank_", "")
        bank, plan = data.split("_", 1)
        
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
        
        await state.update_data(
            bank=bank,
            plan=plan,
            amount=Config.PRICES[plan]
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
        
    except Exception as e:
        logger.error(f"❌ Ошибка выбора банка: {e}")
        await callback.answer("❌ Ошибка при выборе банка", show_alert=True)

# Обработка кнопки отправки скриншота
@payment_router.callback_query(F.data == "send_screenshot")
async def handle_send_screenshot(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📎 <b>Отправьте скриншот перевода</b>\n\n"
        "Пожалуйста, отправьте скриншот или фото чека перевода для подтверждения оплаты.",
        reply_markup=get_cancel_menu()
    )
    await state.set_state(PaymentStates.waiting_screenshot)
    await callback.answer()

# Обработка скриншота оплаты
@dp.message(PaymentStates.waiting_screenshot, F.photo)
async def process_payment_screenshot(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        photo_file_id = message.photo[-1].file_id
        
        if not all(key in user_data for key in ['bank', 'plan', 'amount']):
            await message.answer(
                "❌ Ошибка: не все данные платежа сохранены. Начните процесс заново.",
                reply_markup=get_main_menu()
            )
            await state.clear()
            return
        
        async with pool.acquire() as conn:
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
            
            await conn.execute(
                "INSERT INTO payments (user_id, amount, plan, status, screenshot_file_id, bank) VALUES ($1, $2, $3, 'pending', $4, $5)",
                message.from_user.id, user_data['amount'], user_data['plan'], photo_file_id, user_data['bank']
            )
        
        payment_text = (
            f"🆕 <b>НОВЫЙ ПЛАТЕЖ</b>\n\n"
            f"👤 <b>Пользователь:</b> {message.from_user.first_name} (ID: {message.from_user.id})\n"
            f"🔗 <b>Username:</b> @{message.from_user.username if message.from_user.username else 'нет'}\n"
            f"🏦 <b>Банк:</b> {user_data['bank']}\n"
            f"📋 <b>Тариф:</b> {user_data['plan']}\n"
            f"💵 <b>Сумма:</b> {user_data['amount']}₸\n\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        
        # Отправляем уведомление всем модераторам
        sent_count = 0
        for admin_id in [Config.ADMIN_ID] + Config.MODERATORS:
            try:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file_id,
                    caption=payment_text,
                    reply_markup=get_payment_moderation_buttons(message.from_user.id, user_data['plan'])
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"❌ Не удалось отправить уведомление админу {admin_id}: {e}")
        
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
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки скриншота: {e}")
        await message.answer("❌ Ошибка при обработке платежа", reply_markup=get_main_menu())
        await state.clear()

# Обработка подтверждения платежа
@payment_router.callback_query(F.data.startswith("confirm_payment_"))
async def confirm_payment(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ Только для модераторов", show_alert=True)
        return
    
    try:
        # Парсим данные из callback_data
        data = callback.data.replace("confirm_payment_", "")
        parts = data.split("_")
        
        if len(parts) < 2:
            await callback.answer("❌ Неверный формат данных", show_alert=True)
            return
            
        user_id = int(parts[0])
        plan = "_".join(parts[1:])  # Объединяем оставшиеся части для плана
        
        logger.info(f"🔧 Подтверждение платежа - user_id: {user_id}, plan: {plan}")
        
        async with pool.acquire() as conn:
            payment = await conn.fetchrow(
                """SELECT id, amount FROM payments 
                WHERE user_id = $1 AND plan = $2 AND status = 'pending' 
                ORDER BY created_at DESC LIMIT 1""",
                user_id, plan
            )
            
            if not payment:
                await callback.answer("❌ Платеж не найден или уже обработан", show_alert=True)
                return
            
            await conn.execute(
                "UPDATE payments SET status = 'completed', processed_at = NOW() WHERE id = $1",
                payment['id']
            )
            
            success, message = await create_subscription(user_id, plan)
            
            if success:
                # Отправляем новое сообщение
                await callback.message.answer(
                    f"✅ <b>ПЛАТЕЖ ПОДТВЕРЖДЕН</b>\n\n"
                    f"👤 <b>Пользователь:</b> {user_id}\n"
                    f"📋 <b>Тариф:</b> {plan}\n"
                    f"💵 <b>Сумма:</b> {payment['amount']}₸\n"
                    f"👨‍💼 <b>Подтвердил:</b> {callback.from_user.first_name}\n"
                    f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                )
                
                # Убираем кнопки у старого сообщения
                await callback.message.edit_reply_markup(reply_markup=None)
                
                try:
                    plan_names = {
                        'basic_month': 'Базовый',
                        'pro_month': 'Профи', 
                        'premium_month': 'Премиум'
                    }
                    await bot.send_message(
                        user_id,
                        f"🎉 <b>ВАШ ПЛАТЕЖ ПОДТВЕРЖДЕН!</b>\n\n"
                        f"💎 <b>Тариф:</b> {plan_names.get(plan, plan)}\n"
                        f"💵 <b>Сумма:</b> {payment['amount']}₸\n"
                        f"⏰ <b>Активировано:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                        f"Теперь вам доступны все возможности премиум-аккаунта! 🚀"
                    )
                except Exception as e:
                    logger.error(f"❌ Не удалось уведомить пользователя: {e}")
                    
                await callback.answer("✅ Платеж подтвержден")
            else:
                await callback.answer(f"❌ Ошибка: {message}", show_alert=True)
        
    except Exception as e:
        logger.error(f"❌ Ошибка подтверждения платежа: {e}")
        await callback.answer("❌ Ошибка при подтверждении платежа", show_alert=True)

# Обработка отклонения платежа
@payment_router.callback_query(F.data.startswith("reject_payment_"))
async def reject_payment(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("❌ Только для модераторов", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.replace("reject_payment_", ""))
        
        logger.info(f"🔧 Отклонение платежа - user_id: {user_id}")
        
        async with pool.acquire() as conn:
            payment = await conn.fetchrow(
                "SELECT id, plan, amount FROM payments WHERE user_id = $1 AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                user_id
            )
            
            if not payment:
                await callback.answer("❌ Платеж не найден или уже обработан", show_alert=True)
                return
            
            await conn.execute(
                "UPDATE payments SET status = 'rejected', processed_at = NOW() WHERE id = $1",
                payment['id']
            )
        
        # Отправляем новое сообщение
        await callback.message.answer(
            f"❌ <b>ПЛАТЕЖ ОТКЛОНЕН</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_id}\n"
            f"📋 <b>Тариф:</b> {payment['plan']}\n"
            f"💵 <b>Сумма:</b> {payment['amount']}₸\n"
            f"👨‍💼 <b>Отклонил:</b> {callback.from_user.first_name}\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        
        # Убираем кнопки у старого сообщения
        await callback.message.edit_reply_markup(reply_markup=None)
        
        try:
            await bot.send_message(
                user_id,
                "❌ <b>ВАШ ПЛАТЕЖ БЫЛ ОТКЛОНЕН</b>\n\n"
                "Возможные причины:\n"
                "• Нечеткий или нечитаемый скриншот\n"
                "• Неправильная сумма перевода\n"
                "• Неверные реквизиты\n"
                "• Подозрительная активность\n\n"
                f"💬 Для уточнения обратитесь в поддержку: {Config.SUPPORT_CONTACT}"
            )
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить пользователя: {e}")
        
        await callback.answer("❌ Платеж отклонен")
        
    except Exception as e:
        logger.error(f"❌ Ошибка отклонения платежа: {e}")
        await callback.answer("❌ Ошибка при отклонении платежа", show_alert=True)

# Отмена покупки
@payment_router.callback_query(F.data == "cancel_buy")
async def cancel_buy(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Покупка отменена")
    await callback.answer()

# ===== СИСТЕМА ПРОФИЛЕЙ =====
@dp.message(F.text == "📝 Создать анкету")
async def start_anketa(message: types.Message, state: FSMContext):
    limits = await check_user_limits(message.from_user.id)
    
    if not limits['can_create']:
        if limits['is_premium']:
            await message.answer(f"❌ Вы достигли лимита анкет для премиум аккаунта ({limits['max_profiles']} анкет).\nУдалите одну из старых анкет чтобы создать новую.")
        else:
            await message.answer(
                f"❌ Вы достигли лимита бесплатных анкет (1 анкета).\n\n"
                "💎 <b>Премиум подписка</b> позволяет создавать до 10 анкет!\n"
                "Нажмите '💰 Тарифы' для получения информации.",
                reply_markup=get_main_menu()
            )
        return

    await message.answer("📝 Давайте создадим вашу анкету!\n\nКак вас зовут? (Имя и фамилия)", reply_markup=get_cancel_menu())
    await state.set_state(ProfileStates.waiting_name)

@dp.message(F.text == "❌ Отмена")
async def cancel_anketa(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Заполнение анкеты отменено", reply_markup=get_main_menu())

@dp.message(ProfileStates.waiting_name)
async def process_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
        
    name = message.text.strip()
    is_valid, error_msg = validate_name(name)
    if not is_valid:
        await message.answer(f"❌ {error_msg} Попробуйте еще раз:")
        return
    await state.update_data(name=name)
    await message.answer("🎭 Напишите вашу роль:", reply_markup=get_cancel_menu())
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
    await state.update_data(role=role)
    await message.answer("🔢 Сколько вам лет?", reply_markup=get_cancel_menu())
    await state.set_state(ProfileStates.waiting_age)

@dp.message(ProfileStates.waiting_age)
async def process_age(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
        
    if not message.text.isdigit():
        await message.answer("❌ Пожалуйста, введите число:")
        return
    age = int(message.text)
    is_valid, error_msg = validate_age(age)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    await state.update_data(age=age)
    await message.answer("🏙️ Из какого вы города?", reply_markup=get_cancel_menu())
    await state.set_state(ProfileStates.waiting_city)

@dp.message(ProfileStates.waiting_city)
async def process_city(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
        
    city = message.text.strip()
    is_valid, error_msg = validate_city(city)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    await state.update_data(city=city)
    await message.answer("📝 Расскажите о себе:", reply_markup=get_cancel_menu())
    await state.set_state(ProfileStates.waiting_bio)

@dp.message(ProfileStates.waiting_bio)
async def process_bio(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await cancel_anketa(message, state)
        return
        
    bio = message.text.strip()
    is_valid, error_msg = validate_bio(bio)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    await state.update_data(bio=bio)
    await message.answer("📸 Отлично! Теперь отправьте ваше фото:", reply_markup=get_cancel_menu())
    await state.set_state(ProfileStates.waiting_photo)

@dp.message(ProfileStates.waiting_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        photo_file_id = message.photo[-1].file_id
        
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
            await message.answer_photo(
                photo=photo_file_id,
                caption=f"✅ Анкета успешно {action} и отправлена на модерацию!\n\n"
                       f"👤 <b>Имя:</b> {user_data['name']}\n"
                       f"🎭 <b>Роль:</b> {user_data['role']}\n"
                       f"🎂 <b>Возраст:</b> {user_data['age']}\n"
                       f"🏙️ <b>Город:</b> {user_data['city']}\n"
                       f"📝 <b>О себе:</b> {user_data['bio']}\n\n"
                       f"⏳ <i>Ожидайте решения модератора.</i>",
                reply_markup=get_main_menu()
            )
            
            await state.clear()
        else:
            await message.answer(f"❌ Ошибка: {action}", reply_markup=get_main_menu())
            await state.clear()
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания анкеты: {e}")
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=get_main_menu())
        await state.clear()

@dp.message(ProfileStates.waiting_photo, ~F.photo)
async def process_photo_invalid(message: types.Message, state: FSMContext):
    await message.answer("❌ Пожалуйста, отправьте фото для анкеты")

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
                await message.answer("❌ У вас нет активной анкеты. Создайте её!", reply_markup=get_main_menu())
                
    except Exception as e:
        logger.error(f"❌ Ошибка показа профиля: {e}")
        await message.answer("❌ Ошибка при загрузке анкеты")

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
                    await message.answer_photo(
                        photo=profile['photo'],
                        caption=f"🔍 <b>Найдена анкета:</b>\n\n"
                               f"👤 <b>Имя:</b> {profile['name']}\n"
                               f"🎭 <b>Роль:</b> {profile['role']}\n" 
                               f"🎂 <b>Возраст:</b> {profile['age']}\n"
                               f"🏙️ <b>Город:</b> {profile['city']}\n"
                               f"📝 <b>О себе:</b> {profile['bio'][:100]}..."
                    )
                    
                if searches_left > 0:
                    await message.answer(f"🔍 Осталось поисков сегодня: {searches_left}")
            else:
                await message.answer("😔 Пока нет других анкет.", reply_markup=get_main_menu())
                
    except Exception as e:
        logger.error(f"❌ Ошибка поиска анкет: {e}")
        await message.answer("❌ Ошибка при поиске анкет")

@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика")
async def stats_command(message: types.Message):
    try:
        async with pool.acquire() as conn:
            total_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles")
            pending_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE status = 'pending'")
            approved_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE status = 'approved'")
            
            user_profiles = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE user_id = $1", message.from_user.id)
            user_approved = await conn.fetchval("SELECT COUNT(*) FROM profiles WHERE user_id = $1 AND status = 'approved'", message.from_user.id)
            
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
        logger.error(f"❌ Ошибка статистики: {e}")
        await message.answer("❌ Ошибка при загрузке статистики")

# ===== ЗАПУСК БОТА =====
async def main():
    try:
        await init_db()
        logger.info("🤖 Бот запущен...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())