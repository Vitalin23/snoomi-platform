# bot/main.py - исправленная версия
import os
import sys
import logging

# 🔥 КРИТИЧЕСКИ ВАЖНО: Добавляем пути ДО импортов
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Теперь импортируем pytz
import pytz

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

# ===================== КОНСТАНТЫ =====================
ASK_WIDTH, ASK_LENGTH, ASK_WEIGHT, ASK_TYPE, ASK_HARDNESS = range(5)

URL_SEGMENTS = {
    "80 см": "shirina-matrasa-sm/80/",
    "90 см": "shirina-matrasa-sm/90/",
    "120 см": "shirina-matrasa-sm/120/",
    "140 см": "shirina-matrasa-sm/140/",
    "160 см": "shirina-matrasa-sm/160/",
    "180 см": "shirina-matrasa-sm/180/",
    "200 см": "shirina-matrasa-sm/200/",
    "190 см": "dlina-matrasa-sm/190/",
    "200 см": "dlina-matrasa-sm/200/",
    "До 85 кг": "ves-cheloveka-kg/do-85/",
    "85-115 кг": "ves-cheloveka-kg/85-115/",
    "Более 115 кг": "ves-cheloveka-kg/115-i-bolee/",
    "Ортопедический пружинный": "pruzhinnyj-blok/nezavisimye-pruzhiny/s1000/tfk/",
    "Беспружинный": "pruzhinnyj-blok/bespruzhinnyj/",
    "Мягкий": "zhestkost/mjagkij/",
    "Средний": "zhestkost/srednij/",
    "Жесткий": "zhestkost/zhestkij/"
}

VALID_ANSWERS = {
    ASK_WIDTH: ["80 см", "90 см", "120 см", "140 см", "160 см", "180 см", "200 см"],
    ASK_LENGTH: ["190 см", "200 см"],
    ASK_WEIGHT: ["До 85 кг", "85-115 кг", "Более 115 кг"],
    ASK_TYPE: ["Ортопедический пружинный", "Беспружинный"],
    ASK_HARDNESS: ["Мягкий", "Средний", "Жесткий"]
}

# ===================== ФУНКЦИИ =====================
def generate_final_url(user_data):
    base_url = "https://snoomi.ru/mattress/"
    try:
        url_parts = [
            URL_SEGMENTS[user_data['width']],
            URL_SEGMENTS[user_data['length']],
            URL_SEGMENTS[user_data['type']],
            URL_SEGMENTS[user_data['hardness']],
            URL_SEGMENTS[user_data['weight']]
        ]
        return base_url + "".join(url_parts)
    except:
        return "https://snoomi.ru/catalog/matrasy/"

def is_valid_answer(state, text):
    return text in VALID_ANSWERS[state]

# ===================== ОБРАБОТЧИКИ =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    
    try:
        from database.database import Database
        db = Database("snoomi_bot.db")  # Используем то же имя файла
        
        user = update.effective_user
        
        success = db.add_bot_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        if success:
            logger.info(f"✅ Пользователь {user.id} записан в БД")
        else:
            logger.warning(f"⚠️ Не удалось записать пользователя {user.id} в БД")
        db.close()
        
    except Exception as e:
        logger.error(f"❌ Ошибка записи пользователя в БД: {e}")
    
    await update.message.reply_text(
        "👋 <b>Привет! Я бот-консультант Snoomi</b>\n\n"
        "Помогу подобрать идеальный матрас за 5 вопросов!\n\n"
        "<i>Используйте ТОЛЬКО кнопки для ответа ↓</i>",
        parse_mode='HTML'
    )
    
    keyboard = [["80 см", "90 см"], ["120 см", "140 см"], ["160 см", "180 см"], ["200 см"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "📏 <b>Вопрос 1 из 5:</b> Выберите ширину матраса",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    return ASK_WIDTH

async def ask_width(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if not is_valid_answer(ASK_WIDTH, text):
        keyboard = [["80 см", "90 см"], ["120 см", "140 см"], ["160 см", "180 см"], ["200 см"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            "❌ <b>Пожалуйста, выберите ответ из предложенных кнопок!</b>\n\n"
            "📏 <b>Вопрос 1 из 5:</b> Выберите ширину матраса",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return ASK_WIDTH
    
    context.user_data['width'] = text
    
    keyboard = [["190 см", "200 см"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ <b>Ширина:</b> {text}\n\n"
        "📏 <b>Вопрос 2 из 5:</b> Выберите длину матраса",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    return ASK_LENGTH

async def ask_length(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if not is_valid_answer(ASK_LENGTH, text):
        keyboard = [["190 см", "200 см"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            "❌ <b>Пожалуйста, выберите ответ из предложенных кнопок!</b>\n\n"
            f"✅ <b>Ширина:</b> {context.user_data['width']}\n\n"
            "📏 <b>Вопрос 2 из 5:</b> Выберите длину матраса",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return ASK_LENGTH
    
    context.user_data['length'] = text
    
    width_num = context.user_data['width'].split()[0]
    length_num = text.split()[0]
    full_size = f"{width_num}x{length_num} см"
    context.user_data['full_size'] = full_size
    
    keyboard = [["До 85 кг"], ["85-115 кг"], ["Более 115 кг"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ <b>Размер:</b> {full_size}\n\n"
        "⚖️ <b>Вопрос 3 из 5:</b> Максимальная нагрузка на спальное место?",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    return ASK_WEIGHT

async def ask_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if not is_valid_answer(ASK_WEIGHT, text):
        keyboard = [["До 85 кг"], ["85-115 кг"], ["Более 115 кг"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            "❌ <b>Пожалуйста, выберите ответ из предложенных кнопок!</b>\n\n"
            f"✅ <b>Размер:</b> {context.user_data['full_size']}\n\n"
            "⚖️ <b>Вопрос 3 из 5:</b> Максимальная нагрузка на спальное место?",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return ASK_WEIGHT
    
    context.user_data['weight'] = text
    
    keyboard = [["Ортопедический пружинный"], ["Беспружинный"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ <b>Нагрузка:</b> {text}\n\n"
        "🛏️ <b>Вопрос 4 из 5:</b> Выберите тип матраса",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    return ASK_TYPE

async def ask_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if not is_valid_answer(ASK_TYPE, text):
        keyboard = [["Ортопедический пружинный"], ["Беспружинный"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            "❌ <b>Пожалуйста, выберите ответ из предложенных кнопок!</b>\n\n"
            f"✅ <b>Нагрузка:</b> {context.user_data['weight']}\n\n"
            "🛏️ <b>Вопрос 4 из 5:</b> Выберите тип матраса",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return ASK_TYPE
    
    context.user_data['type'] = text
    
    keyboard = [["Мягкий"], ["Средний"], ["Жесткий"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ <b>Тип:</b> {text}\n\n"
        "💪 <b>Вопрос 5 из 5:</b> Выберите жесткость матраса",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    return ASK_HARDNESS

async def ask_hardness(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if not is_valid_answer(ASK_HARDNESS, text):
        keyboard = [["Мягкий"], ["Средний"], ["Жесткий"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            "❌ <b>Пожалуйста, выберите ответ из предложенных кнопок!</b>\n\n"
            f"✅ <b>Тип:</b> {context.user_data['type']}\n\n"
            "💪 <b>Вопрос 5 из 5:</b> Выберите жесткость матраса",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return ASK_HARDNESS
    
    context.user_data['hardness'] = text
    
    final_url = generate_final_url(context.user_data)
    
    result_text = (
        "🎉 <b>Отлично! Подбор завершен!</b>\n\n"
        "══════════════════════════\n"
        f"<b>📋 Ваши параметры:</b>\n"
        f"• <b>Размер:</b> {context.user_data['full_size']}\n"
        f"• <b>Нагрузка:</b> {context.user_data['weight']}\n"
        f"• <b>Тип:</b> {context.user_data['type']}\n"
        f"• <b>Жесткость:</b> {text}\n"
        "══════════════════════════\n\n"
        "🔗 <b>Ваша персональная подборка готова!</b>\n"
        "Нажмите на кнопку ниже, чтобы посмотреть матрасы 👇"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Посмотреть подборку", url=final_url)],
        [InlineKeyboardButton("📞 Связаться с менеджером", url="https://t.me/vitalin23")],
        [InlineKeyboardButton("🔄 Новый подбор", callback_data="new_search")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        from database.database import Database
        db = Database()
        user = update.effective_user
        db.increment_completed_conversations(user.id)
        db.close()
        logger.info(f"✅ Диалог завершен для пользователя {user.id}")
    except Exception as e:
        logger.error(f"❌ Ошибка записи завершенного диалога: {e}")
    
    await update.message.reply_text(
        result_text,
        parse_mode='HTML',
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Диалог завершен. Отправьте /start для нового подбора.",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "new_search":
        await query.edit_message_text(
            text="🔄 <b>Начинаем новый подбор!</b>\n\nОтправьте /start чтобы начать.",
            parse_mode='HTML'
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Бот-консультант Snoomi</b>\n\n"
        "📍 <b>Как это работает:</b>\n"
        "1. Отправьте /start\n"
        "2. Выбирайте ответы ТОЛЬКО кнопками\n"
        "3. Получите персональную подборку\n\n"
        "📍 <b>Основные команды:</b>\n"
        "• /start - начать подбор\n"
        "• /help - эта справка\n"
        "• /cancel - отменить диалог\n"
        "• /admin - панель администратора",
        parse_mode='HTML'
    )

# ===================== УЛУЧШЕННАЯ ЗАГРУЗКА АДМИН-ПАНЕЛИ =====================
def load_admin_panel(application):
    """Загружает админ-панель - УЛУЧШЕННАЯ ВЕРСИЯ"""
    print("🔄 Загрузка админ-панели...")
    
    try:
        # Способ 1: Прямой импорт из той же директории
        import importlib.util
        
        # Определяем путь к admin.py
        admin_path = os.path.join(os.path.dirname(__file__), "admin.py")
        
        if os.path.exists(admin_path):
            print(f"✅ Найден файл admin.py: {admin_path}")
            
            # Динамически импортируем модуль
            spec = importlib.util.spec_from_file_location("admin_module", admin_path)
            admin_module = importlib.util.module_from_spec(spec)
            
            try:
                spec.loader.exec_module(admin_module)
                print("✅ Модуль admin.py загружен")
                
                # Добавляем обработчики
                if hasattr(admin_module, 'add_admin_to_main_bot'):
                    admin_module.add_admin_to_main_bot(application)
                    print("✅ Админ-обработчики добавлены")
                    return True
                else:
                    print("❌ Функция add_admin_to_main_bot не найдена")
                    
            except Exception as e:
                print(f"❌ Ошибка загрузки модуля: {e}")
                import traceback
                traceback.print_exc()
                
        else:
            print(f"❌ Файл admin.py не найден по пути: {admin_path}")
            
    except Exception as e:
        print(f"❌ Критическая ошибка загрузки админ-панели: {e}")
        import traceback
        traceback.print_exc()
    
    return False

# ===================== ПРОМЕЖУТОЧНЫЕ АДМИН-ФУНКЦИИ =====================
# Добавляем базовые функции прямо в main.py на случай, если админ-панель не загрузится
async def admin_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Базовая админ-функция если админ-панель не загрузилась"""
    user_id = update.effective_user.id
    
    # Проверяем ID администратора (упрощенно)
    ADMIN_IDS = [390456492]  # Добавьте сюда ID администраторов
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "🚫 *Доступ запрещен*\n\n"
            f"*Ваш ID:* `{user_id}`\n"
            f"*Разрешенные ID:* `{ADMIN_IDS}`",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(
        "👑 *Панель управления Snoomi Platform*\n\n"
        "⚠️ *Внимание:* Основная админ-панель не загрузилась\n\n"
        "Доступные команды:\n"
        "• /status - проверка системы\n"
        "• /test - тест публикации\n"
        "• /publish - ручная публикация",
        parse_mode='Markdown'
    )

async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса системы"""
    await update.message.reply_text(
        "📊 *Статус системы Snoomi*\n\n"
        "✅ Бот-консультант: Работает\n"
        "⚠️ Админ-панель: Частично загружена\n"
        "🔧 Для полного доступа проверьте загрузку модулей",
        parse_mode='Markdown'
    )

# ===================== ЗАПУСК =====================
def main():
    TOKEN = "8487257181:AAGUKolhnJ8y1XaQq_TFzhxTRKEh9x2KC-U"
    
    print("=" * 50)
    print("🚀 БОТ SNOMI - С АДМИН-ПАНЕЛЬЮ")
    print("=" * 50)
    
    try:
        application = Application.builder().token(TOKEN).build()
        
        print("✅ Application создана успешно!")
        
        # Создаем ConversationHandler для основного бота
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                ASK_WIDTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_width)],
                ASK_LENGTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_length)],
                ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
                ASK_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_type)],
                ASK_HARDNESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_hardness)],
            },
            fallbacks=[
                CommandHandler('cancel', cancel),
                CommandHandler('help', help_command),
                CommandHandler('start', start)
            ],
            allow_reentry=True
        )
        
        # 🔥 ВАЖНО: Добавляем ConversationHandler ПЕРВЫМ
        # Это предотвращает конфликты с другими обработчиками
        application.add_handler(conv_handler)
        
        # Затем добавляем остальные обработчики
        application.add_handler(CommandHandler('help', help_command))
        
        # Обработчик для callback кнопок внутри ConversationHandler
        application.add_handler(CallbackQueryHandler(button_callback, pattern="^new_search$"))
        
        # 🔥 Пытаемся загрузить полную админ-панель
        admin_loaded = load_admin_panel(application)
        
        if not admin_loaded:
            print("⚠️ Админ-панель не загрузилась, добавляем базовые функции")
            # Добавляем базовые админ-команды
            application.add_handler(CommandHandler("admin", admin_fallback))
            application.add_handler(CommandHandler("status", admin_status))
        
        print("\n" + "=" * 50)
        print("✅ Бот запущен!")
        print("🤖 Основные команды: /start, /help")
        print("👑 Админ-панель: /admin")
        print("=" * 50 + "\n")
        
        # Запускаем бота
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()