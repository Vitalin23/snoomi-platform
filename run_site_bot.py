"""
Отдельный запуск сайтового Telegram-бота.
Не запускает монетизационный планировщик и веб-панель.
"""
from run import setup_environment, run_bot_safe


def main():
    if not setup_environment():
        return
    run_bot_safe()


if __name__ == "__main__":
    main()
