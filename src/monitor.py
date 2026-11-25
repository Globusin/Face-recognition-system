#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import threading
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.access.authentication import AuthenticationEngine, AuthenticationState
from utils.face.recognition import recognize_face_from_camera
from utils.capture.camera_manager import get_camera_manager, stop_camera_manager
from utils.access.audit import PostgresAudit
from utils.access.decision import AccessPolicy
from utils.access.policy_store import apply_override, load_override, policy_path
from utils.access.status import authentication_service
from utils.challenge.challenge_check import (
    UnavailableChallengeCheck, build_challenge_check,
)
from utils.face.face_observations import (
    ConcurrentFaceObservationSource, FaceObservationSource, ObservationRejected,
)
from utils.access.lock_controller import initialize_lock_controller
from utils.device.display import initialize_display, DisplayState
from utils.common.config_loader import load_config
from utils.common.logger import log_info, log_error, log_warning
from utils.common.maintenance import maintenance
from utils.stereo.stereo_liveness import (
    StereoCheck, StereoLivenessDiagnostics, StereoWorker, liveness_settings,
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


# Короткие причины для TFT 128x160, не больше двух строк
REASON_TEXT = {
    'identity_not_confirmed': 'Лицо не\nраспознано',
    'liveness_spoof': 'Обнаружена\nподделка',
    'stereo_required': 'Нет проверки\nобъёма',
    'stereo_not_passed': 'Проверка\nобъёма',
    'challenge_failed': 'Задание\nне выполнено',
    'challenge_not_passed': 'Задание\nне выполнено',
    'challenge_required': 'Нужно\nзадание',
    'timeout': 'Время\nвышло',
    'face_lost': 'Лицо\nпотеряно',
    'multiple_faces': 'Несколько\nлиц',
    'track_changed': 'Другое\nлицо',
    'track_gap': 'Лицо\nпотеряно',
    'observation_expired': 'Кадр\nустарел',
    'camera_unavailable': 'Камера\nнедоступна',
    'unlock_failed': 'Ошибка\nзамка',
    'lock_failed': 'Ошибка\nзамка',
    'processing_error': 'Ошибка\nобработки',
    'policy_config_error': 'Ошибка\nнастроек',
    'challenge_config_error': 'Ошибка\nзаданий',
}


def run_monitoring(stop_event=None):
    """
    Запускает непрерывный мониторинг камеры для распознавания лиц
    и управления замком с выводом статуса на TFT-дисплей
    """
    if stop_event is None:
        stop_event = threading.Event()

    # Загружаем конфигурацию и применяем политику, сохранённую администратором
    config = load_config()
    if config.get('authentication'):
        config = apply_override(config, load_override(policy_path(config)))
    audit = config.get('audit') or {}
    if audit and audit.get('enabled', True):
        authentication_service.configure_audit(PostgresAudit())

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
        session = engine.session
        reason = session.reason if session else ''
        detail = None
        if (state in (AuthenticationState.DENIED, AuthenticationState.ERROR)
                and reason):
            detail = REASON_TEXT.get(reason)
        if state in states:
            safe_display_state(display, states[state], detail)
        log_info(f"Аутентификация: {state.value}, причина: {reason or '-'}")

    try:
        policy = AccessPolicy.from_config(config)
    except ValueError as error:
        # Ошибка конфигурации политики запрещает допуск, а не отключает проверки
        log_error(f'Политика допуска недоступна: {error}')
        policy = AccessPolicy(config_error='policy_config_error')

    liveness = None
    stereo_diagnostics = None
    stereo_worker = None
    stereo_check = None
    try:
        liveness = liveness_settings(config)
        if liveness['mode'] != 'off':
            if not liveness['calibration_id'] or not liveness['mounting_confirmed']:
                log_warning(
                    'Стереопроверка включена, но калибровка не указана или '
                    'крепление не подтверждено; замер не выполняется'
                )
            else:
                stereo_diagnostics = StereoLivenessDiagnostics(
                    get_camera_manager(), liveness,
                    config.get('stereo_calibration', {}).get(
                        'output_dir', 'data/calibration',
                    ),
                    measurement_limits(config.get('stereo_pad', {})),
                )
                worker = None
                if liveness['parallel']:
                    # Замер идёт одновременно с распознаванием
                    worker = StereoWorker(stereo_diagnostics)
                stereo_worker = worker
                stereo_check = StereoCheck(
                    stereo_diagnostics, liveness['mode'],
                    worker=worker, timeout=liveness['result_timeout'],
                )
    except ValueError as error:
        # Диагностика не должна мешать работе монитора
        log_error(f"Стерео-проверка отключена: {error}")

    challenge_check = None
    try:
        challenge_check = build_challenge_check(
            config, display, policy,
            on_progress=authentication_service.publish_challenge_progress,
        )
    except Exception as error:
        # Ошибка конфигурации не отключает обязательную проверку: запрещаем допуск
        log_error(f'Задания недоступны из-за ошибки конфигурации: {error}')
        challenge_check = UnavailableChallengeCheck('challenge_config_error')

    settings = config.get('authentication', {})
    engine = AuthenticationEngine(
        lock_controller, maintenance, stop_event,
        session_timeout=settings.get('session_timeout_seconds', 20.0),
        cooldown_seconds=detection_interval,
        door_open_seconds=door_open_time,
        stereo_check=stereo_check,
        challenge_check=challenge_check,
        policy=policy,
        on_state=show_authentication_state,
        on_finish=authentication_service.record_session,
    )
    authentication_service.attach(engine)
    authentication_service.set_running_policy(policy)

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
                        with ConcurrentFaceObservationSource(
                            source, engine.session.deadline,
                            lambda reason: engine.cancel_session(session_id, reason),
                            interval=settings.get('capture', {}).get(
                                'tracking_interval_seconds', 0.15,
                            ),
                        ) as tracked_source:
                            def recognize_current_track():
                                on_pair = None
                                if stereo_worker is not None:
                                    # Первая пара трека уходит в рабочий поток
                                    # стереопроверки, пока распознавание
                                    # продолжает сбор кадров
                                    on_pair = lambda pair: stereo_worker.submit(session_id, pair)
                                try:
                                    return recognize_face_from_camera(
                                        observation_source=tracked_source,
                                        deadline=engine.session.deadline,
                                        on_pair=on_pair,
                                    )
                                except ObservationRejected as error:
                                    engine.cancel(str(error))
                                    return False, None, None

                            if challenge_check is not None:
                                challenge_check.bind(tracked_source)
                            if stereo_check is not None:
                                stereo_check.bind(tracked_source)
                            try:
                                engine.evaluate(
                                    session_id, recognize_current_track,
                                    track_guard=tracked_source.grant_guard,
                                )
                            finally:
                                if challenge_check is not None:
                                    challenge_check.release()
                                if stereo_check is not None:
                                    stereo_check.release()
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
        if stereo_worker is not None:
            stereo_worker.close()
        authentication_service.flush_audit()
        authentication_service.attach(None)
        log_info("Мониторинг остановлен")


if __name__ == "__main__":
    try:
        run_monitoring()
    finally:
        stop_camera_manager()
