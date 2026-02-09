# bot/admin.py
"""
Админ-панель для управления Snoomi Platform через Telegram
Использует ID администратора из .env файла
"""
import logging
import os
import sys

# Добавляем пути для импорта
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Импортируем Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Получаем ID администратора из config
def get_admin_ids():
    """Получает ID администраторов из config.py"""
    try:
        # Импортируем config
        try:
            from config import Config
        except ImportError:
            # Пробуем альтернативный путь
            import config
            Config = config.Config
        
        # Проверяем, есть ли TG_ADMIN
        if hasattr(Config, 'TG_ADMIN') and Config.TG_ADMIN:
            admin_ids = []
            admin_str = str(Config.TG_ADMIN)
            admin_str = admin_str.replace(' ', '')
            
            # Разделяем по запятой если несколько ID
            if ',' in admin_str:
                ids = admin_str.split(',')
                for id_str in ids:
                    if id_str.strip().isdigit():
                        admin_ids.append(int(id_str.strip()))
            else:
                # Один ID
                if admin_str.isdigit():
                    admin_ids.append(int(admin_str))
            
            logger.info(f"📋 Загружены ID администраторов: {admin_ids}")
            return admin_ids
        else:
            logger.warning("⚠️ TG_ADMIN не настроен")
            # Возвращаем ваш ID для теста
            return [390456492]
            
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки ID: {e}")
        # Возвращаем ваш ID для теста
        return [390456492]

def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    admin_ids = get_admin_ids()
    is_admin_user = user_id in admin_ids
    
    logger.info(f"🔍 Проверка доступа: ID {user_id} в {admin_ids} = {is_admin_user}")
    return is_admin_user

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin"""
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name
    
    logger.info(f"🔄 Команда /admin от {user_name} (ID: {user_id})")
    
    # Проверяем доступ
    if not is_admin(user_id):
        admin_ids = get_admin_ids()
        await update.message.reply_text(
            f"🚫 *Доступ запрещен*\n\n"
            f"*Ваш ID:* `{user_id}`\n"
            f"*Разрешенные ID:* `{admin_ids}`\n\n"
            "Добавьте ваш ID в .env файл:\n"
            "`TG_ADMIN=390456492`",
            parse_mode='Markdown'
        )
        return
    
    logger.info(f"✅ Доступ разрешен для {user_name}")
    
    # Создаем клавиатуру
    keyboard = [
        [InlineKeyboardButton("📊 Статус системы", callback_data="status")],
        [InlineKeyboardButton("🧪 Тест публикации", callback_data="test")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("📝 Ручная публикация", callback_data="manual")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👑 *Панель управления Snoomi Platform*\n\n"
        f"*Пользователь:* {user_name}\n"
        "*Статус:* ✅ Администратор\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статус системы"""
    query = update.callback_query
    await query.answer()
    
    logger.info("🔄 Запрос статуса системы")
    
    try:
        # Импортируем планировщик
        from posting.scheduler import ContentScheduler
        
        scheduler = ContentScheduler()
        
        # Формируем текст
        text = "📊 *Статус системы*\n\n"
        
        # Компоненты
        text += "*🤖 Компоненты:*\n"
        text += f"• Yandex GPT: {'✅' if scheduler.writer else '❌'}\n"
        text += f"• Yandex Art: {'✅' if scheduler.artist else '⚠️'}\n"
        text += f"• VK Publisher: {'✅' if scheduler.vk_publisher else '⚠️'}\n"
        text += f"• TG Poster: {'✅' if scheduler.tg_poster else '⚠️'}\n\n"
        
        # Настройки
        try:
            from config import Config
            text += "*⚙️ Настройки:*\n"
            text += f"• Время: {Config.PUBLISH_HOUR}:00\n"
            text += f"• VK: {'✅' if Config.PUBLISH_TO_VK else '❌'}\n"
            text += f"• TG: {'✅' if Config.PUBLISH_TO_TG else '❌'}\n"
        except:
            text += "*Настройки:* Не загружены\n"
        
        # Кнопка назад
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка статуса: {e}")
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)[:100]}",
            parse_mode='Markdown'
        )

async def test_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запустить тестовую публикацию"""
    query = update.callback_query
    await query.answer()
    
    logger.info("🧪 Запуск тестовой публикации")
    
    await query.edit_message_text(
        "🧪 *Запускаю тест...*\nПожалуйста, подождите.",
        parse_mode='Markdown'
    )
    
    try:
        from posting.scheduler import ContentScheduler
        
        scheduler = ContentScheduler()
        success = scheduler.run_test_publication()
        
        if success:
            result = "✅ *Тест успешен!*"
        else:
            result = "❌ *Тест не удался*"
        
    except Exception as e:
        result = f"❌ *Ошибка:* {str(e)[:100]}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        result,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать настройки"""
    query = update.callback_query
    await query.answer()
    
    logger.info("⚙️  Запрос настроек")
    
    try:
        from config import Config
        
        text = "⚙️ *Настройки*\n\n"
        text += f"• Yandex API: {'✅' if Config.YANDEX_API_KEY else '❌'}\n"
        text += f"• Yandex Folder: {'✅' if Config.YANDEX_FOLDER_ID else '❌'}\n"
        text += f"• Yandex Art: {'✅' if Config.YANDEX_ART_KEY else '❌'}\n"
        text += f"• VK Токен: {'✅' if Config.VK_ACCESS_TOKEN else '❌'}\n"
        text += f"• TG Токен: {'✅' if Config.TELEGRAM_CHANNEL_TOKEN else '❌'}\n"
        text += f"• TG Канал: {'✅' if Config.TELEGRAM_CHANNEL_ID else '❌'}\n"
        
    except Exception as e:
        text = f"❌ *Ошибка:* {str(e)[:100]}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def manual_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручная публикация"""
    query = update.callback_query
    await query.answer()
    
    logger.info("📝 Запуск ручной публикации")
    
    await query.edit_message_text(
        "📝 *Запуск публикации...*",
        parse_mode='Markdown'
    )
    
    try:
        from posting.scheduler import ContentScheduler
        
        scheduler = ContentScheduler()
        success = scheduler.run_single_publication()
        
        if success:
            result = "✅ *Публикация успешна!*"
        else:
            result = "❌ *Ошибка публикации*"
        
    except Exception as e:
        result = f"❌ *Ошибка:* {str(e)[:100]}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        result,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вернуться в главное меню"""
    query = update.callback_query
    await query.answer()
    
    user_name = update.effective_user.username or update.effective_user.first_name
    
    keyboard = [
        [InlineKeyboardButton("📊 Статус системы", callback_data="status")],
        [InlineKeyboardButton("🧪 Тест публикации", callback_data="test")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("📝 Ручная публикация", callback_data="manual")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👑 *Панель управления Snoomi Platform*\n\n"
        f"*Пользователь:* {user_name}\n"
        "*Статус:* ✅ Администратор\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный обработчик callback"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    logger.info(f"🔄 Callback получен: {data}")
    
    # Проверяем доступ администратора для callback
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.answer("🚫 Доступ запрещен", show_alert=True)
        return
    
    # Обрабатываем разные callback_data
    if data == "status":
        await status_callback(update, context)
    elif data == "test":
        await test_callback(update, context)
    elif data == "settings":
        await settings_callback(update, context)
    elif data == "manual":
        await manual_callback(update, context)
    elif data == "back":
        await back_callback(update, context)
    else:
        logger.warning(f"⚠️  Неизвестный callback: {data}")
        await query.edit_message_text(
            "❌ Неизвестная команда",
            parse_mode='Markdown'
        )

def add_admin_to_main_bot(application):
    """Добавить админ-обработчики к приложению"""
    # Команда /admin
    application.add_handler(CommandHandler("admin", admin_command))
    
    # Один универсальный обработчик для всех callback
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    logger.info("✅ Админ-панель добавлена")

# Тест
if __name__ == "__main__":
    print("🧪 Тест админ-панели")
    print("=" * 50)
    
    # Проверяем пути
    print(f"📁 Текущая директория: {current_dir}")
    print(f"📁 Родительская директория: {parent_dir}")
    
    # Проверяем config
    try:
        from config import Config
        print(f"✅ Config загружен")
        print(f"🔑 TG_ADMIN: {getattr(Config, 'TG_ADMIN', 'Не найден')}")
    except Exception as e:
        print(f"❌ Ошибка config: {e}")
    
    # Проверяем ID администраторов
    admin_ids = get_admin_ids()
    print(f"📋 ID администраторов: {admin_ids}")
    
    # Проверяем импорты
    try:
        from posting.scheduler import ContentScheduler
        print("✅ Scheduler загружен")
    except Exception as e:
        print(f"❌ Ошибка scheduler: {e}")