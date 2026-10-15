#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import recognize_face_from_camera
from utils.lock_controller import initialize_lock_controller
from utils.display import initialize_display, DisplayState
from utils.config_loader import load_config
from utils.logger import log_info, log_error, log_warning, log_debug


def safe_display_state(display, state: DisplayState, detail: str = None) -> None:
    """Safely update display state without throwing errors to the main loop."""
    try:
        display.show_state(state, detail)
    except Exception as e:
        log_warning(f"Ошибка обновления TFT дисплея: {e}")


def run_monitoring():
    """
    Запускает непрерывный мониторинг камеры для распознавания лиц
    и управления замком с выводом статуса на TFT-дисплей.
    """
    # Загружаем конфигурацию
    config = load_config()

    lock_controller = initialize_lock_controller(config)
    display = initialize_display(config)

    detection_interval = config.get('detection_interval', 2)
    door_open_time = config.get('door_open_time', 5)

    log_info("Запуск системы непрерывного мониторинга")
    log_info(f"Интервал проверки: {detection_interval} сек.")
    log_info(f"Время открытия двери: {door_open_time} сек.")

    is_door_open = False
    last_success_time = 0

    safe_display_state(display, DisplayState.STANDBY, "Ready")

    try:
        while True:
            current_time = time.time()

            # Проверяем, нужно ли закрыть дверь после открытия
            if is_door_open and (current_time - last_success_time) >= door_open_time:
                log_info("Автоматическое закрытие замка...")
                lock_controller.lock()
                is_door_open = False
                safe_display_state(display, DisplayState.STANDBY)
                log_info("Замок закрыт")

            # Если дверь открыта, пропускаем проверку
            if is_door_open:
                time.sleep(0.5)
                continue

            log_debug("Выполнение проверки распознавания лица...")
            safe_display_state(display, DisplayState.CHECKING, "Scanning face...")

            try:
                is_authenticated, user_id, distance = recognize_face_from_camera()
            except Exception as e:
                log_error(f"Ошибка при захвате или распознавании: {e}")
                safe_display_state(display, DisplayState.ERROR, "Camera / Model err")
                time.sleep(detection_interval)
                safe_display_state(display, DisplayState.STANDBY)
                continue

            if is_authenticated:
                log_info(f"Пользователь распознан! User ID: {user_id}, Distance: {distance:.4f}")

                log_info("Открытие замка...")
                if lock_controller.unlock():
                    log_info("✓ Замок успешно открыт (замок замокан)")
                    is_door_open = True
                    last_success_time = current_time

                    safe_display_state(
                        display,
                        DisplayState.ACCESS_GRANTED,
                        f"User: {user_id}\nDist: {distance:.3f}"
                    )

                    # Логирование события доступа
                    log_info(f"Доступ предоставлен пользователю {user_id}")
                else:
                    log_error("✗ Ошибка при открытии замка")
                    safe_display_state(display, DisplayState.ERROR, "Lock failure")
            else:
                log_debug("Лицо не распознано или не найдено в базе данных")
                safe_display_state(display, DisplayState.ACCESS_DENIED, "Unknown User")
                time.sleep(1)
                safe_display_state(display, DisplayState.STANDBY)

            # Ждем перед следующей проверкой
            time.sleep(detection_interval)

    except KeyboardInterrupt:
        log_info("Остановка мониторинга...")

        # Убеждаемся, что замок закрыт при остановке
        if is_door_open:
            log_info("Закрытие замка перед выходом...")
            lock_controller.lock()

        safe_display_state(display, DisplayState.STANDBY, "Offline")
        log_info("Мониторинг остановлен")

    except Exception as e:
        log_error(f"Критическая ошибка в цикле мониторинга: {e}")
        safe_display_state(display, DisplayState.ERROR, "Critical Fault")
        raise


if __name__ == "__main__":
    run_monitoring()
