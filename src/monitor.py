#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import threading
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.access.authentication import AuthenticationEngine, AuthenticationState
from utils.face.recognition import recognize_face_from_camera
from utils.capture.camera_manager import get_camera_manager, stop_camera_manager
from utils.challenge.challenge_check import (
    UnavailableChallengeCheck, build_challenge_check,
)
from utils.face.face_observations import FaceObservationSource, ObservationRejected
from utils.access.lock_controller import initialize_lock_controller
from utils.device.display import initialize_display, DisplayState
from utils.common.config_loader import load_config
from utils.common.logger import log_info, log_error, log_warning
from utils.common.maintenance import maintenance
from utils.stereo.stereo_liveness import (
    StereoDiagnosticsCollector, StereoLivenessDiagnostics, liveness_settings,
)
from utils.stereo.two_view_pad import measurement_limits


def safe_display_state(display, state: DisplayState, detail: str = None) -> None:
    """Обновляет экран, не останавливая монитор при ошибке дисплея"""
    if maintenance.challenge_running.is_set():
        return
    try:
        display.show_state(state, detail)
    except Exception as e:
        log_warning(f"Ошибка обновления TFT дисплея: {e}")


def wait_or_stop(stop_event, seconds):
    """Ждёт указанное время и позволяет быстро остановить монитор"""
    return stop_event.wait(seconds)


def should_collect_stereo(state, session):
    """Замер нужен для любого оценённого кадра, включая отказ

    Отказ — это и есть отрицательный пример для калибровки PAD; выборка только
    из допусков смещена и не покажет, как проверка ведёт себя на атаках.
    Прерванные попытки без результата распознавания пропускаются: оценивать
    геометрию по кадру, где лицо уже потеряно, бессмысленно.
    """
    return (session is not None
            and state in (AuthenticationState.GRANTED, AuthenticationState.DENIED)
            and 'recognition' in session.checks)


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
    maintenance.display = display

    detection_interval = config.get('detection_interval', 2)
    door_open_time = config.get('door_open_time', 5)

    log_info("Запуск системы непрерывного мониторинга")
    log_info(f"Интервал проверки: {detection_interval} сек.")
    log_info(f"Время открытия двери: {door_open_time} сек.")

    def show_authentication_state(state):
        states = {
            AuthenticationState.IDLE: DisplayState.STANDBY,
            AuthenticationState.TRACKING: DisplayState.CHECKING,
            AuthenticationState.EVALUATING: DisplayState.CHECKING,
            AuthenticationState.CHALLENGE: DisplayState.CHECKING,
            AuthenticationState.GRANTED: DisplayState.ACCESS_GRANTED,
            AuthenticationState.DENIED: DisplayState.ACCESS_DENIED,
            AuthenticationState.ERROR: DisplayState.ERROR,
        }
        if state in states:
            safe_display_state(display, states[state])
        session = engine.session
        reason = session.reason if session else ''
        log_info(f"Аутентификация: {state.value}, причина: {reason or '-'}")

    liveness = None
    stereo_diagnostics = None
    try:
        liveness = liveness_settings(config)
        if liveness['enabled']:
            stereo_diagnostics = StereoLivenessDiagnostics(
                get_camera_manager(), liveness,
                config.get('stereo_calibration', {}).get(
                    'output_dir', 'data/calibration',
                ),
                measurement_limits(config.get('stereo_pad', {})),
            )
    except ValueError as error:
        # Диагностика не должна мешать работе монитора
        log_error(f"Стерео-диагностика отключена: {error}")

    challenge_check = None
    try:
        challenge_check = build_challenge_check(
            config, display, stereo_diagnostics,
        )
    except Exception as error:
        # Ошибка конфигурации не отключает обязательную проверку: запрещаем допуск
        log_error(f'Задания недоступны из-за ошибки конфигурации: {error}')
        challenge_check = UnavailableChallengeCheck('challenge_config_error')

    stereo_collector = None
    if stereo_diagnostics is not None:
        stereo_collector = StereoDiagnosticsCollector(stereo_diagnostics)

    settings = config.get('authentication', {})
    engine = AuthenticationEngine(
        lock_controller, maintenance, stop_event,
        session_timeout=settings.get('session_timeout_seconds', 20.0),
        cooldown_seconds=detection_interval,
        door_open_seconds=door_open_time,
        challenge_check=challenge_check,
        on_state=show_authentication_state,
    )

    safe_display_state(display, DisplayState.STANDBY, "Готов к работе")

    try:
        while not stop_event.is_set():
            engine.tick()
            if engine.state != AuthenticationState.IDLE:
                wait_or_stop(stop_event, 0.1)
                continue

            if maintenance.requested.is_set():
                state = DisplayState.CALIBRATING
                if maintenance.stereo_measuring.is_set():
                    state = DisplayState.STEREO_MEASURING
                if maintenance.timing_measuring.is_set():
                    state = DisplayState.TIMING_TEST
                safe_display_state(display, state)
                wait_or_stop(stop_event, 0.5)
                continue

            try:
                with maintenance.recognition():
                    safe_display_state(display, DisplayState.STANDBY, "Подойдите\nк камере")
                    source = FaceObservationSource(
                        get_camera_manager(), stop_event, maintenance.requested,
                        settings.get('capture', {}),
                    )
                    observation = source.wait_for_face(
                        on_wait=lambda: safe_display_state(display, DisplayState.STANDBY),
                    )
                    session_id = engine.begin(observation.track_id)
                    if session_id is not None:
                        def recognize_current_track():
                            try:
                                return recognize_face_from_camera(
                                    observation_source=source,
                                    deadline=engine.session.deadline,
                                )
                            except ObservationRejected as error:
                                engine.cancel(str(error))
                                return False, None, None

                        if challenge_check is not None:
                            challenge_check.bind(source)
                        try:
                            engine.evaluate(session_id, recognize_current_track)
                        finally:
                            if challenge_check is not None:
                                challenge_check.release()
                        # Пара снята во время сопровождения этого лица, до
                        # допуска; вычисление уходит в поток, чтобы tick()
                        # не ждал геометрию и не продлевал открытие замка
                        session_after = engine.session
                        if (stereo_collector is not None and session_after is not None
                                and should_collect_stereo(engine.state, session_after)
                                and 'stereo' not in session_after.diagnostics):
                            # Замер уже выполнен политикой заданий — второй не нужен
                            stereo_collector.submit(session_after, source.current)
            except ObservationRejected:
                continue
            except Exception as error:
                if maintenance.requested.is_set():
                    engine.cancel('maintenance')
                    continue
                log_error(f"Ошибка при захвате или распознавании: {error}")
                engine.fail('camera_or_processing_error')

    except KeyboardInterrupt:
        stop_event.set()
    finally:
        log_info("Остановка мониторинга...")
        # Замок закрывается первым: ожидание диагностики не должно его задерживать
        if not engine.close():
            log_error("Не удалось подтвердить закрытие замка при остановке")
            safe_display_state(display, DisplayState.ERROR, "Ошибка закрытия\nзамка")
        else:
            safe_display_state(display, DisplayState.STANDBY, "Мониторинг\nостановлен")
        if stereo_collector is not None:
            stereo_collector.close()
        log_info("Мониторинг остановлен")


if __name__ == "__main__":
    try:
        run_monitoring()
    finally:
        stop_camera_manager()
