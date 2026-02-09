# bot/channel_manager.py
"""
Telegram бот для управления каналами клиентов
"""
import os
import sys
import logging
from typing import Optional

# Добавляем пути для импорта
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

logger = logging.getLogger(__name__)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters
)

# Состояния для ConversationHandler
REGISTER_NAME, REGISTER_EMAIL, ADD_CHANNEL_PLATFORM, ADD_CHANNEL_ID, ADD_CHANNEL_NAME = range(5)
MANAGE_CHANNEL, EDIT_SETTINGS, ADD_TOPIC = range(5, 8)

class ChannelManagerBot:
    """Бот для управления каналами клиентов"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Импортируем базу данных каналов
        try:
            from database.channels_db import channels_db
            self.db = channels_db
            self.logger.info("✅ База данных каналов загружена")
        except ImportError as e:
            self.logger.error(f"❌ Не удалось загрузить базу данных: {e}")
            self.db = None
    
    # ===================== ОСНОВНЫЕ КОМАНДЫ =====================
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        
        self.logger.info(f"🔄 Команда /start от {user.username} (ID: {user.id})")
        
        # Проверяем, зарегистрирован ли пользователь как клиент
        if self.db:
            client = self.db.get_client_by_telegram(user.id)
            
            if client:
                # Пользователь уже клиент - показываем меню управления
                await self.show_client_menu(update, context, client)
                return ConversationHandler.END
            else:
                # Новый пользователь - предлагаем регистрацию
                keyboard = [
                    [InlineKeyboardButton("✅ Зарегистрироваться", callback_data="register")],
                    [InlineKeyboardButton("ℹ️ Узнать больше", callback_data="info")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"👋 Привет, {user.first_name}!\n\n"
                    "Я помогу вам автоматизировать публикации в ваших социальных сетях.\n\n"
                    "🔹 *Автоматическая генерация контента*\n"
                    "🔹 *Публикация в Telegram, VK, OK*\n"
                    "🔹 *Статистика и аналитика*\n"
                    "🔹 *Управление из Telegram*\n\n"
                    "Хотите стать клиентом?",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
        
        await update.message.reply_text(
            "👋 Привет! Система управления каналами временно недоступна.",
            parse_mode='Markdown'
        )
    
    async def show_client_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, client):
        """Показывает меню управления для клиента"""
        client_id = client[0]
        client_name = client[1]
        
        # Получаем статистику клиента
        stats = self.db.get_client_statistics(client_id) if self.db else None
        
        # Формируем текст
        text = f"👤 *{client_name}*\n\n"
        
        if stats and stats['overall_stats']:
            total_channels, active_channels, total_posts, total_views, _, _ = stats['overall_stats']
            text += f"📊 *Статистика:*\n"
            text += f"• Каналы: {active_channels}/{total_channels} активны\n"
            text += f"• Публикаций: {total_posts or 0}\n"
            text += f"• Просмотры: {total_views or 0}\n\n"
        
        text += "⚙️ *Управление:*"
        
        # Создаем клавиатуру
        keyboard = [
            [InlineKeyboardButton("📺 Мои каналы", callback_data=f"channels_{client_id}")],
            [InlineKeyboardButton("➕ Добавить канал", callback_data=f"add_channel_{client_id}")],
            [InlineKeyboardButton("📈 Статистика", callback_data=f"stats_{client_id}")],
            [InlineKeyboardButton("⚙️ Настройки", callback_data=f"settings_{client_id}")],
            [InlineKeyboardButton("🚀 Опубликовать сейчас", callback_data=f"publish_now_{client_id}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    # ===================== РЕГИСТРАЦИЯ КЛИЕНТА =====================
    
    async def start_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начинает процесс регистрации клиента"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "📝 *Регистрация нового клиента*\n\n"
            "Пожалуйста, введите ваше имя (или название компании):",
            parse_mode='Markdown'
        )
        
        return REGISTER_NAME
    
    async def register_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает ввод имени"""
        name = update.message.text
        context.user_data['client_name'] = name
        
        await update.message.reply_text(
            f"✅ Имя: {name}\n\n"
            "Введите ваш email (опционально):\n"
            "(или отправьте '-' чтобы пропустить)",
            parse_mode='Markdown'
        )
        
        return REGISTER_EMAIL
    
    async def register_email(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает ввод email"""
        email = update.message.text
        if email != '-':
            context.user_data['client_email'] = email
        
        # Регистрируем клиента в БД
        if self.db:
            client_id = self.db.add_client(
                name=context.user_data['client_name'],
                email=context.user_data.get('client_email'),
                telegram_id=update.effective_user.id,
                plan='basic'
            )
            
            if client_id:
                context.user_data['client_id'] = client_id
                
                await update.message.reply_text(
                    "🎉 *Регистрация успешна!*\n\n"
                    f"Добро пожаловать, {context.user_data['client_name']}!\n\n"
                    "Теперь вы можете добавлять свои каналы и настраивать автоматические публикации.",
                    parse_mode='Markdown'
                )
                
                # Показываем меню клиента
                client = (client_id, context.user_data['client_name'], 
                         context.user_data.get('client_email'), update.effective_user.id,
                         None, 'active', 'basic', 1, None)
                await self.show_client_menu(update, context, client)
                
                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    "❌ *Ошибка регистрации*\n\n"
                    "Не удалось зарегистрировать вас как клиента. Пожалуйста, попробуйте позже.",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
        
        await update.message.reply_text(
            "❌ *Ошибка регистрации*\n\n"
            "База данных недоступна. Пожалуйста, попробуйте позже.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    # ===================== УПРАВЛЕНИЕ КАНАЛАМИ =====================
    
    async def show_client_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает каналы клиента"""
        query = update.callback_query
        await query.answer()
        
        # Извлекаем client_id из callback_data
        client_id = int(query.data.split('_')[1])
        
        # Получаем каналы клиента
        channels = self.db.get_client_channels(client_id) if self.db else []
        
        if not channels:
            keyboard = [[InlineKeyboardButton("➕ Добавить канал", callback_data=f"add_channel_{client_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📺 *Ваши каналы*\n\n"
                "У вас еще нет добавленных каналов.\n"
                "Добавьте первый канал чтобы начать автоматические публикации.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Формируем список каналов
        text = "📺 *Ваши каналы:*\n\n"
        keyboard = []
        
        for channel in channels:
            channel_id, _, platform, channel_platform_id, channel_name, _, _, is_active, _ = channel
            status = "✅" if is_active else "⏸️"
            
            text += f"{status} *{channel_name}*\n"
            text += f"   Платформа: {platform}\n"
            text += f"   ID: {channel_platform_id}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(f"⚙️ {channel_name}", callback_data=f"manage_channel_{channel_id}")
            ])
        
        keyboard.append([InlineKeyboardButton("➕ Добавить канал", callback_data=f"add_channel_{client_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"menu_{client_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def start_add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начинает процесс добавления канала"""
        query = update.callback_query
        await query.answer()
        
        client_id = int(query.data.split('_')[2])
        context.user_data['client_id'] = client_id
        
        keyboard = [
            [InlineKeyboardButton("📱 Telegram", callback_data=f"platform_telegram_{client_id}")],
            [InlineKeyboardButton("🔵 VK (ВКонтакте)", callback_data=f"platform_vk_{client_id}")],
            [InlineKeyboardButton("🟠 OK (Одноклассники)", callback_data=f"platform_ok_{client_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data=f"channels_{client_id}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "➕ *Добавление канала*\n\n"
            "Выберите платформу для нового канала:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def select_platform(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает выбор платформы"""
        query = update.callback_query
        await query.answer()
        
        parts = query.data.split('_')
        platform = parts[1]
        client_id = int(parts[2])
        
        context.user_data['platform'] = platform
        context.user_data['client_id'] = client_id
        
        platform_names = {
            'telegram': 'Telegram',
            'vk': 'ВКонтакте',
            'ok': 'Одноклассники'
        }
        
        instructions = {
            'telegram': "Введите @username канала (например, @mychannel) или ID канала (например, -1001234567890):",
            'vk': "Введите ID группы ВКонтакте (например, -12345678):",
            'ok': "Введите ID группы Одноклассники:"
        }
        
        await query.edit_message_text(
            f"➕ *Добавление канала {platform_names.get(platform, platform)}*\n\n"
            f"{instructions.get(platform, 'Введите ID канала:')}\n\n"
            "ℹ️ _Для публикаций боту нужны права администратора в канале/группе_",
            parse_mode='Markdown'
        )
        
        return ADD_CHANNEL_ID
    
    async def add_channel_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает ввод ID канала"""
        channel_id = update.message.text
        context.user_data['channel_id'] = channel_id
        
        await update.message.reply_text(
            f"✅ ID канала: {channel_id}\n\n"
            "Введите название канала (для отображения в системе):",
            parse_mode='Markdown'
        )
        
        return ADD_CHANNEL_NAME
    
    async def add_channel_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает ввод названия канала"""
        channel_name = update.message.text
        context.user_data['channel_name'] = channel_name
        
        # Добавляем канал в БД
        if self.db:
            platform = context.user_data['platform']
            channel_id = context.user_data['channel_id']
            client_id = context.user_data['client_id']
            
            db_channel_id = self.db.add_channel(
                client_id=client_id,
                platform=platform,
                channel_id=channel_id,
                channel_name=channel_name
            )
            
            if db_channel_id:
                # Настраиваем канал по умолчанию
                self.db.update_channel_settings(
                    channel_id=db_channel_id,
                    publish_hour=10,
                    publish_frequency='daily',
                    max_posts_per_day=1
                )
                
                # Добавляем темы по умолчанию
                if platform == 'telegram':
                    self.db.add_topic_to_channel(
                        channel_id=db_channel_id,
                        topic="Новости и интересное",
                        keywords=["новости", "интересное", "полезное"]
                    )
                elif platform == 'vk':
                    self.db.add_topic_to_channel(
                        channel_id=db_channel_id,
                        topic="Тематика группы",
                        keywords=["сообщество", "общение", "интересное"]
                    )
                
                await update.message.reply_text(
                    f"🎉 *Канал добавлен успешно!*\n\n"
                    f"📺 *{channel_name}*\n"
                    f"🔧 Платформа: {platform}\n"
                    f"🆔 ID: {channel_id}\n\n"
                    f"Теперь вы можете настроить:\n"
                    f"• Время публикаций\n"
                    f"• Темы контента\n"
                    f"• Хештеги\n"
                    f"• И другие параметры\n\n"
                    f"Используйте меню управления каналом для настройки.",
                    parse_mode='Markdown'
                )
                
                # Возвращаемся к списку каналов
                query = update.message
                await self.show_client_channels(update, context)
                
            else:
                await update.message.reply_text(
                    "❌ *Ошибка добавления канала*\n\n"
                    "Не удалось добавить канал. Пожалуйста, проверьте данные и попробуйте еще раз.",
                    parse_mode='Markdown'
                )
        
        return ConversationHandler.END
    
    async def manage_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает меню управления каналом"""
        query = update.callback_query
        await query.answer()
        
        channel_id = int(query.data.split('_')[2])
        
        # Получаем информацию о канале
        if self.db:
            cursor = self.db.conn.cursor()
            cursor.execute('SELECT * FROM client_channels WHERE id = ?', (channel_id,))
            channel = cursor.fetchone()
            
            if channel:
                _, client_id, platform, channel_platform_id, channel_name, _, _, is_active, _ = channel
                
                # Получаем настройки
                settings = self.db.get_channel_settings(channel_id)
                
                # Получаем статистику
                stats = self.db.get_channel_stats(channel_id, days=7)
                total_posts = sum(day[1] for day in stats) if stats else 0
                
                # Формируем текст
                text = f"⚙️ *Управление каналом: {channel_name}*\n\n"
                text += f"🔧 Платформа: {platform}\n"
                text += f"🆔 ID: {channel_platform_id}\n"
                text += f"📊 Публикаций за неделю: {total_posts}\n\n"
                
                if settings:
                    text += f"⏰ Время публикации: {settings.get('publish_hour', 10)}:00\n"
                    text += f"📅 Частота: {settings.get('publish_frequency', 'daily')}\n"
                    text += f"🔢 Максимум в день: {settings.get('max_posts_per_day', 1)}\n\n"
                
                text += "*Действия:*"
                
                # Создаем клавиатуру
                keyboard = [
                    [InlineKeyboardButton("⏰ Настроить время", callback_data=f"edit_time_{channel_id}")],
                    [InlineKeyboardButton("📝 Темы контента", callback_data=f"topics_{channel_id}")],
                    [InlineKeyboardButton("#️⃣ Хештеги", callback_data=f"hashtags_{channel_id}")],
                    [InlineKeyboardButton("📊 Статистика", callback_data=f"channel_stats_{channel_id}")],
                    [InlineKeyboardButton("🔧 Другие настройки", callback_data=f"other_settings_{channel_id}")],
                    [InlineKeyboardButton("🔄 Тестировать подключение", callback_data=f"test_connection_{channel_id}")],
                    [
                        InlineKeyboardButton("✅ Включен" if is_active else "⏸️ Выключен", 
                                           callback_data=f"toggle_active_{channel_id}"),
                        InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_channel_{channel_id}")
                    ],
                    [InlineKeyboardButton("🔙 Назад к каналам", callback_data=f"channels_{client_id}")]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def show_channel_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает статистику канала"""
        query = update.callback_query
        await query.answer()
        
        channel_id = int(query.data.split('_')[2])
        
        if self.db:
            # Получаем статистику за 30 дней
            stats = self.db.get_channel_stats(channel_id, days=30)
            
            if not stats:
                await query.answer("Статистики пока нет", show_alert=True)
                return
            
            # Формируем текст
            text = "📊 *Статистика канала за 30 дней*\n\n"
            
            total_posts = 0
            total_views = 0
            total_likes = 0
            
            for day_stats in stats[-10:]:  # Последние 10 дней
                date, posts, views, likes, shares, comments = day_stats
                text += f"📅 {date}:\n"
                text += f"   📝 Посты: {posts}\n"
                if views > 0:
                    text += f"   👁️ Просмотры: {views}\n"
                if likes > 0:
                    text += f"   👍 Лайки: {likes}\n"
                if shares > 0:
                    text += f"   🔄 Репосты: {shares}\n"
                if comments > 0:
                    text += f"   💬 Комментарии: {comments}\n"
                text += "\n"
                
                total_posts += posts
                total_views += views
                total_likes += likes
            
            text += f"📈 *Итого за 30 дней:*\n"
            text += f"• Публикаций: {total_posts}\n"
            text += f"• Просмотров: {total_views}\n"
            text += f"• Лайков: {total_likes}\n"
            
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f"manage_channel_{channel_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    # ===================== CALLBACK ОБРАБОТЧИКИ =====================
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает все callback-запросы"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith('register'):
            await self.start_registration(update, context)
        
        elif data.startswith('channels_'):
            await self.show_client_channels(update, context)
        
        elif data.startswith('add_channel_'):
            await self.start_add_channel(update, context)
        
        elif data.startswith('platform_'):
            await self.select_platform(update, context)
        
        elif data.startswith('manage_channel_'):
            await self.manage_channel(update, context)
        
        elif data.startswith('menu_'):
            client_id = int(data.split('_')[1])
            if self.db:
                client = self.db.get_client_by_telegram(update.effective_user.id)
                if client:
                    await self.show_client_menu(update, context, client)
        
        elif data.startswith('channel_stats_'):
            await self.show_channel_stats(update, context)
        
        elif data.startswith('test_connection_'):
            channel_id = int(data.split('_')[2])
            await self.test_channel_connection(update, context, channel_id)
        
        elif data.startswith('toggle_active_'):
            channel_id = int(data.split('_')[2])
            await self.toggle_channel_active(update, context, channel_id)
        
        elif data.startswith('publish_now_'):
            client_id = int(data.split('_')[2])
            await self.publish_now(update, context, client_id)
        
        else:
            await query.answer("Команда не распознана", show_alert=True)
    
    async def test_channel_connection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int):
        """Тестирует подключение к каналу"""
        query = update.callback_query
        
        try:
            from posting.multi_publisher import MultiPlatformPublisher
            
            # Получаем информацию о канале
            if self.db:
                cursor = self.db.conn.cursor()
                cursor.execute('SELECT * FROM client_channels WHERE id = ?', (channel_id,))
                channel = cursor.fetchone()
                
                if channel:
                    _, _, platform, channel_platform_id, channel_name, access_token, _, _, _ = channel
                    
                    channel_info = {
                        'platform': platform,
                        'platform_channel_id': channel_platform_id,
                        'channel_name': channel_name,
                        'access_token': access_token
                    }
                    
                    publisher = MultiPlatformPublisher()
                    result = publisher.test_channel_connection(channel_info)
                    
                    if result.get('connected'):
                        await query.answer(f"✅ Подключение к {channel_name} успешно!", show_alert=True)
                    else:
                        await query.answer(f"❌ Ошибка подключения: {result.get('error', 'Неизвестная ошибка')}", show_alert=True)
                else:
                    await query.answer("❌ Канал не найден", show_alert=True)
        
        except Exception as e:
            await query.answer(f"❌ Ошибка тестирования: {str(e)[:100]}", show_alert=True)
    
    async def toggle_channel_active(self, update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int):
        """Включает/выключает канал"""
        query = update.callback_query
        
        if self.db:
            cursor = self.db.conn.cursor()
            
            # Получаем текущий статус
            cursor.execute('SELECT is_active FROM client_channels WHERE id = ?', (channel_id,))
            result = cursor.fetchone()
            
            if result:
                new_status = not result[0]
                
                # Обновляем статус
                cursor.execute('UPDATE client_channels SET is_active = ? WHERE id = ?', 
                             (new_status, channel_id))
                self.db.conn.commit()
                
                status_text = "включен" if new_status else "выключен"
                await query.answer(f"✅ Канал {status_text}", show_alert=True)
                
                # Обновляем сообщение
                await self.manage_channel(update, context)
            else:
                await query.answer("❌ Канал не найден", show_alert=True)
    
    async def publish_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE, client_id: int):
        """Запускает публикацию сейчас"""
        query = update.callback_query
        
        try:
            from posting.multi_publisher import publish_to_client_channels
            
            await query.answer("🔄 Запускаю публикацию...", show_alert=False)
            
            # Получаем темы для публикации
            if self.db:
                # Получаем первый активный канал клиента
                channels = self.db.get_client_channels(client_id, active_only=True)
                if channels:
                    channel_id = channels[0][0]
                    topics = self.db.get_channel_topics(channel_id)
                    
                    if topics:
                        topic = topics[0]['topic']
                        keywords = topics[0].get('keywords', [])
                        
                        result = publish_to_client_channels(client_id, topic, keywords)
                        
                        if result.get('success'):
                            await query.answer(
                                f"✅ Опубликовано в {result['successful_posts']} каналов!\n"
                                f"Тема: {topic[:50]}...",
                                show_alert=True
                            )
                        else:
                            await query.answer(
                                f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}",
                                show_alert=True
                            )
                    else:
                        await query.answer("❌ Нет тем для публикации", show_alert=True)
                else:
                    await query.answer("❌ Нет активных каналов", show_alert=True)
        
        except Exception as e:
            await query.answer(f"❌ Ошибка: {str(e)[:100]}", show_alert=True)
    
    # ===================== ДОБАВЛЕНИЕ В APPLICATION =====================
    
    def add_to_application(self, application):
        """Добавляет обработчики ChannelManagerBot к приложению"""
        
        # Проверяем, что база данных доступна
        if not self.db:
            self.logger.error("❌ ChannelManagerBot: База данных недоступна")
            return
        
        # Регистрация клиента (ConversationHandler)
        registration_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_registration, pattern='^register$')],
            states={
                REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.register_name)],
                REGISTER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.register_email)],
            },
            fallbacks=[],
        )
        
        # Добавление канала (ConversationHandler)
        add_channel_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.select_platform, pattern='^platform_')],
            states={
                ADD_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_channel_id)],
                ADD_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_channel_name)],
            },
            fallbacks=[],
        )
        
        # Добавляем обработчики к приложению
        application.add_handler(CommandHandler("mychannels", self.start_command))
        application.add_handler(registration_handler)
        application.add_handler(add_channel_handler)
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        self.logger.info("✅ ChannelManagerBot добавлен к приложению")


# Создаем глобальный экземпляр
channel_manager = ChannelManagerBot()

# Тест
if __name__ == "__main__":
    print("🧪 Тест Channel Manager Bot")
    print("=" * 60)
    
    # Простой тест без запуска бота
    manager = ChannelManagerBot()
    
    if manager.db:
        print("✅ База данных загружена")
        
        # Тест получения клиента
        test_client = manager.db.get_client_by_telegram(123456789)
        if test_client:
            print(f"✅ Найден тестовый клиент: {test_client[1]}")
        else:
            print("ℹ️ Тестовый клиент не найден (это нормально)")
    else:
        print("❌ База данных не загружена")
    
    print("\n" + "=" * 60)
    print("✅ Тест завершен")