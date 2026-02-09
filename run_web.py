"""
Отдельный запуск веб-панели монетизации.
"""
from run import setup_environment, run_web_safe


def main():
    if not setup_environment():
        return
    run_web_safe()


if __name__ == "__main__":
    main()
