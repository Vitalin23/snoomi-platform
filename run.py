# run.py - ОБНОВЛЕННЫЙ С МУЛЬТИКАНАЛЬНОСТЬЮ
"""
Главный запускающий файл с поддержкой мультиканальной системы
"""
import sys
import os
import threading
import time
import importlib

# Добавляем пути
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _resolve_bot_entrypoint():
    """
    Находит точку входа Telegram-бота для разных вариантов имени папки:
    Bot/main.py (текущее) или bot/main.py (legacy).
    """
    for module_name in ("Bot.main", "bot.main"):
        try:
            module = importlib.import_module(module_name)
            return module.main
        except ModuleNotFoundError as e:
            # Игнорируем только ошибку отсутствия самого пакета Bot/bot.
            package_name = module_name.split(".")[0]
            if e.name == package_name:
                continue
            raise

    raise ImportError("Не найден модуль бота: ожидается Bot/main.py или bot/main.py")

def setup_environment():
    """Настройка окружения"""
    print("="*60)
    print("🚀 SNOOMI PLATFORM - МУЛЬТИКАНАЛЬНАЯ СИСТЕМА")
    print("="*60)
    
    # Проверяем структуру
    folder_groups = [
        ("Bot", "bot"),  # исторически встречаются оба варианта
        ("posting",),
        ("ai",),
        ("database",),
    ]
    for group in folder_groups:
        existing = next((folder for folder in group if os.path.exists(folder)), None)
        folder = existing or group[0]
        if existing:
            print(f"✅ Папка {folder}/")
        else:
            print(f"❌ Папка {folder}/ отсутствует")
            os.makedirs(folder, exist_ok=True)
    
    # Проверяем конфиг
    try:
        from config import Config
        print("✅ config.py импортирован")
        
        if not hasattr(Config, 'YANDEX_API_KEY') or not Config.YANDEX_API_KEY:
            print("\n⚠️  YANDEX_API_KEY не настроен (генерация контента не будет работать)")
        else:
            print("✅ Yandex API настроен")
            
        return True
            
    except ImportError:
        print("❌ Не удалось импортировать config.py")
        return False

def run_bot_safe():
    """Безопасный запуск бота"""
    try:
        from config import Config
        if not Config.TELEGRAM_BOT_TOKEN:
            print("❌ TELEGRAM_BOT_TOKEN не настроен, бот не запускается")
            return
        
        bot_main = _resolve_bot_entrypoint()
        
        print("🤖 Telegram-бот запущен")
        bot_main()
        
    except ImportError as e:
        print(f"❌ Не удалось импортировать бота: {e}")
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")
        import traceback
        traceback.print_exc()

def run_multi_scheduler_safe():
    """Безопасный запуск мультиканального планировщика"""
    try:
        from posting.multi_scheduler import MultiChannelScheduler
        print("📢 Запуск мультиканального планировщика...")
        
        scheduler = MultiChannelScheduler()
        scheduler.run_test_publication()  # Тестовый запуск
        
    except ImportError as e:
        print(f"❌ Не удалось импортировать планировщик: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"❌ Ошибка планировщика: {e}")
        import traceback
        traceback.print_exc()

def run_channel_manager_test():
    """Тест системы управления каналами"""
    try:
        from database.channels_db import ChannelsDatabase
        
        print("🧪 Тест системы управления каналами")
        print("=" * 50)
        
        # Создаем тестовую БД
        db = ChannelsDatabase("test_channels_system.db")
        
        # Добавляем тестового клиента
        client_id = db.add_client(
            name="Тестовый Клиент для Монетизации",
            email="monetization@test.com",
            telegram_id=390456492,
            plan="premium"
        )
        
        if client_id:
            print(f"✅ Клиент добавлен: ID {client_id}")
            
            # Добавляем тестовые каналы
            tg_id = db.add_channel(
                client_id=client_id,
                platform="telegram",
                channel_id="@test_monetization_channel",
                channel_name="Канал для монетизации"
            )
            
            vk_id = db.add_channel(
                client_id=client_id,
                platform="vk",
                channel_id="-123456789",
                channel_name="Группа ВК для монетизации"
            )
            
            print(f"✅ Каналы добавлены: TG ID {tg_id}, VK ID {vk_id}")
            
            # Настраиваем каналы
            db.update_channel_settings(
                channel_id=tg_id,
                publish_hour=10,
                publish_frequency="daily",
                topics=["монетизация", "бизнес", "автоматизация"],
                hashtags=["#монетизация", "#автопостинг", "#snoomi"],
                max_posts_per_day=2
            )
            
            # Добавляем темы
            db.add_topic_to_channel(
                channel_id=tg_id,
                topic="Как монетизировать социальные сети",
                keywords=["монетизация", "соцсети", "доход", "автоматизация"],
                priority=10
            )
            
            # Получаем статистику
            stats = db.get_client_statistics(client_id)
            if stats and stats['overall_stats']:
                total_channels = stats['overall_stats'][0]
                print(f"📊 Статистика: {total_channels} каналов у клиента")
            
            db.close()
            print("\n✅ Система управления каналами работает!")
            
            # Показываем путь к файлу БД
            import os
            if os.path.exists("test_channels_system.db"):
                size = os.path.getsize("test_channels_system.db") // 1024
                print(f"📁 Файл БД: test_channels_system.db ({size} KB)")
        
        else:
            print("❌ Не удалось добавить клиента")
            
    except Exception as e:
        print(f"❌ Ошибка теста: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Главное меню"""
    
    if not setup_environment():
        return
    
    print("\n" + "="*60)
    print("🎯 ВЫБЕРИТЕ РЕЖИМ РАБОТЫ")
    print("="*60)
    print("1. 🤖 Только Telegram-бот (консультант)")
    print("2. 📢 Мультиканальный планировщик (тест)")
    print("3. ⚡ Полная система (бот + мультиканальность)")
    print("4. 🧪 Тест системы управления каналами")
    print("5. 🏪 Монетизация: клиентский портал (заглушка)")
    print("6. 📊 Статистика системы")
    print("7. 🚪 Выход")
    
    while True:
        choice = input("\nВаш выбор (1-7): ").strip()
        
        if choice == "1":
            print("\n🤖 ЗАПУСК БОТА-КОНСУЛЬТАНТА...")
            run_bot_safe()
            break
            
        elif choice == "2":
            print("\n📢 ТЕСТ МУЛЬТИКАНАЛЬНОГО ПЛАНИРОВЩИКА...")
            run_multi_scheduler_safe()
            break
            
        elif choice == "3":
            print("\n⚡ ЗАПУСК ПОЛНОЙ СИСТЕМЫ...")
            
            # Запускаем в отдельных потоках
            bot_thread = threading.Thread(target=run_bot_safe, daemon=True)
            scheduler_thread = threading.Thread(target=run_multi_scheduler_safe, daemon=True)
            
            bot_thread.start()
            scheduler_thread.start()
            
            print("✅ Система запущена в фоне")
            print("🤖 Бот-консультант + 📢 Мультиканальный планировщик")
            print("🛑 Нажмите Ctrl+C для остановки")
            
            try:
                bot_thread.join()
                scheduler_thread.join()
            except KeyboardInterrupt:
                print("\n🛑 Остановка...")
                sys.exit(0)
            break
            
        elif choice == "4":
            print("\n🧪 ТЕСТ СИСТЕМЫ УПРАВЛЕНИЯ КАНАЛАМИ...")
            run_channel_manager_test()
            break
            
        elif choice == "5":
            print("\n🏪 КЛИЕНТСКИЙ ПОРТАЛ ДЛЯ МОНЕТИЗАЦИИ")
            print("=" * 50)
            print("🚧 В РАЗРАБОТКЕ")
            print("\nЗапланированные функции:")
            print("• Личный кабинет клиента")
            print("• Управление каналами через веб-интерфейс")
            print("• Просмотр статистики и аналитики")
            print("• Система оплаты и тарифы")
            print("• Поддержка и уведомления")
            print("\n💡 Пока используйте Telegram-бота для управления")
            break
            
        elif choice == "6":
            print("\n📊 СТАТИСТИКА СИСТЕМЫ")
            print("=" * 50)
            
            try:
                # Проверяем основные БД
                import glob
                
                print("📁 Файлы баз данных:")
                db_files = glob.glob("*.db")
                for db_file in db_files:
                    if os.path.exists(db_file):
                        size = os.path.getsize(db_file) // 1024
                        modified = os.path.getmtime(db_file)
                        from datetime import datetime
                        modified_str = datetime.fromtimestamp(modified).strftime('%Y-%m-%d %H:%M')
                        print(f"  • {db_file}: {size} KB, изменен: {modified_str}")
                
                # Проверяем изображения
                print("\n🎨 Сгенерированные изображения:")
                image_files = glob.glob("yandex_art_*.jpg") + glob.glob("simple_*.jpg")
                if image_files:
                    for img_file in image_files[-5:]:  # Последние 5
                        if os.path.exists(img_file):
                            size = os.path.getsize(img_file) // 1024
                            print(f"  • {img_file}: {size} KB")
                else:
                    print("  • Нет сгенерированных изображений")
                
                # Информация о системе
                print("\n⚙️ Информация о системе:")
                import platform
                print(f"  • Python: {platform.python_version()}")
                print(f"  • ОС: {platform.system()} {platform.release()}")
                
            except Exception as e:
                print(f"❌ Ошибка получения статистики: {e}")
            
            break
            
        elif choice == "7":
            print("\n🚪 Выход...")
            break
            
        else:
            print("❌ Неверный выбор")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 Программа остановлена")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)