"""
Отдельный запуск монетизационного контура (автопостинг).
По умолчанию запускает боевой планировщик, --test запускает тестовый прогон.
"""
import argparse

from run import setup_environment, run_multi_scheduler_safe


def main():
    parser = argparse.ArgumentParser(description="Snoomi monetization scheduler launcher")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Запустить только тестовую публикацию вместо постоянного планировщика",
    )
    args = parser.parse_args()

    if not setup_environment():
        return

    run_multi_scheduler_safe(test_mode=args.test)


if __name__ == "__main__":
    main()
