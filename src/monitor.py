#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import threading
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import recognize_face_from_camera
from utils.video_capture import wait_for_face
from utils.lock_controller import initialize_lock_controller
from utils.display import initialize_display, DisplayState
from utils.config_loader import load_config
from utils.logger import log_info, log_error, log_warning, log_debug


def safe_display_state(display, state: DisplayState, detail: str = None) -> None:
    """Обновляет экран, не останавливая монитор при ошибке дисплея"""
    try:
        display.show_state(state, detail)
    except Exception as e:
        log_warning(f"Ошибка обновления TFT дисплея: {e}")


def wait_or_stop(stop_event, seconds):
    """Ждёт указанное время и позволяет быстро остановить монитор"""
    return stop_event.wait(seconds)


def run_monitoring(stop_event=None):
    """
    Запускает непрерывный мониторинг камеры для распознавания лиц
    и управления замком с выводом статуса на TFT-дисплей
    """
    if stop_event is None:
        stop_event = threading.Event()

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

    safe_display_state(display, DisplayState.STANDBY, "Готов к работе")

    try:
        while not stop_event.is_set():
            current_time = time.monotonic()

            # Проверяем, нужно ли закрыть дверь после открытия
            if is_door_open and (current_time - last_success_time) >= door_open_time:
                log_info("Автоматическое закрытие замка...")
                lock_controller.lock()
                is_door_open = False
                safe_display_state(display, DisplayState.STANDBY)
                log_info("Замок закрыт")

            # Если дверь открыта, пропускаем проверку
            if is_door_open:
                wait_or_stop(stop_event, 0.5)
                continue

            try:
                safe_display_state(display, DisplayState.STANDBY, "Подойдите\nк камере")
                if not wait_for_face(
                    stop_event,
                    on_wait=lambda: safe_display_state(display, DisplayState.STANDBY),
                ):
                    break

                log_debug("Лицо обнаружено, запускаем распознавание по серии кадров")
                safe_display_state(display, DisplayState.CHECKING, "Распознавание\nлица")
                is_authenticated, user_id, distance = recognize_face_from_camera()
            except Exception as e:
                log_error(f"Ошибка при захвате или распознавании: {e}")
                safe_display_state(display, DisplayState.ERROR, "Ошибка камеры\nили модели")
                wait_or_stop(stop_event, detection_interval)
                safe_display_state(display, DisplayState.STANDBY)
                continue

            if is_authenticated:
                log_info(f"Пользователь распознан! Идентификатор: {user_id}, расстояние: {distance:.4f}")

                log_info("Открытие замка...")
                if lock_controller.unlock():
                    log_info("Замок успешно открыт (программная заглушка)")
                    is_door_open = True
                    last_success_time = time.monotonic()

                    safe_display_state(
                        display,
                        DisplayState.ACCESS_GRANTED,
                        f"Пользователь:\n{user_id}\nРасстояние:\n{distance:.3f}"
                    )

                    # Логирование события доступа
                    log_info(f"Доступ предоставлен пользователю {user_id}")
                else:
                    log_error("Ошибка при открытии замка")
                    safe_display_state(display, DisplayState.ERROR, "Ошибка замка")
            else:
                log_debug("Лицо не распознано или не найдено в базе данных")
                safe_display_state(display, DisplayState.ACCESS_DENIED, "Пользователь\nне распознан")
                wait_or_stop(stop_event, 1)
                safe_display_state(display, DisplayState.STANDBY)

            # Ждем перед следующей проверкой
            wait_or_stop(stop_event, detection_interval)

    except KeyboardInterrupt:
        stop_event.set()
    except Exception as e:
        log_error(f"Критическая ошибка в цикле мониторинга: {e}")
        safe_display_state(display, DisplayState.ERROR, "Критическая\nошибка")
        raise
    finally:
        log_info("Остановка мониторинга...")

        if is_door_open:
            log_info("Закрытие замка перед выходом...")
            lock_controller.lock()

        safe_display_state(display, DisplayState.STANDBY, "Мониторинг\nостановлен")
        log_info("Мониторинг остановлен")


if __name__ == "__main__":
    run_monitoring()
