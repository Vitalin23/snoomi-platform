# cli/interface.py
import curses
from datetime import datetime

def draw_menu(stdscr):
    """Рисуем текстовый интерфейс"""
    curses.curs_set(0)
    stdscr.clear()
    
    while True:
        height, width = stdscr.getmaxyx()
        
        # Заголовок
        title = " SNOOMI PLATFORM MANAGEMENT CONSOLE "
        stdscr.addstr(1, (width - len(title)) // 2, title, curses.A_BOLD)
        
        # Меню
        menu_items = [
            "1. 📊 Показать статистику",
            "2. ⚙️  Настройки системы",
            "3. 📅 Управление расписанием",
            "4. 📝 Создать пост сейчас",
            "5. 🚀 Запустить планировщик",
            "6. 🛑 Остановить систему",
            "7. 📄 Просмотреть логи",
            "8. 🚪 Выход"
        ]
        
        for idx, item in enumerate(menu_items, start=3):
            stdscr.addstr(idx, 2, item)
        
        # Статус бар
        status = f"Статус: 🟢 Работает | Последняя проверка: {datetime.now().strftime('%H:%M:%S')}"
        stdscr.addstr(height-2, 2, status)
        
        stdscr.refresh()
        
        # Обработка ввода
        key = stdscr.getch()
        if key == ord('1'):
            show_stats(stdscr)
        elif key == ord('8'):
            break

def main():
    curses.wrapper(draw_menu)