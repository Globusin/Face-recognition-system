"""Одна диагностическая сессия заданий, без хранения изображений и embeddings"""

import threading
import time
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone

from utils.camera_manager import get_camera_manager
from utils.config_loader import load_config
from utils.display import DisplayState, NullDisplay
from utils.challenge_response import COMMANDS, ChallengeFlow, challenge_settings, observe_face
from utils.maintenance import maintenance
from utils.stereo_calibration import calibration_session, write_json
from utils.logger import log_info, log_error
from utils.timing import measure_time


class ChallengeSession:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.worker = None
        self.session_id = None
        self.result = dict(stage='idle', access_granted=False, experimental=True)

    def status(self):
        with self.lock:
            result = dict(self.result)
            result['session_id'] = self.session_id
            return result

    def start(self, consent, preparation_mode=False):
        if type(preparation_mode) is not bool:
            raise ValueError('Режим подготовки должен быть true или false')
        if consent is not True:
            raise ValueError('Подтвердите согласие участника')
        settings = challenge_settings(load_config().get('challenge_response', {}))
        # Тот же порядок блокировок, что у калибровки: сначала её lock
        if not calibration_session.lock.acquire(blocking=False):
            raise RuntimeError('Обслуживание камер занято')
        try:
            with self.lock:
                if self.worker is not None and self.worker.is_alive():
                    raise RuntimeError('Проверка уже запущена')
                if calibration_session.active or maintenance.requested.is_set():
                    raise RuntimeError('Сначала завершите калибровку')
                if maintenance.display is None or isinstance(maintenance.display, NullDisplay):
                    raise RuntimeError('Для заданий запустите монитор с работающим TFT-дисплеем')
                maintenance.begin()
                maintenance.challenge_running.set()
                self.cancelled.clear()
                self.session_id = uuid.uuid4().hex
                self.result = dict(stage='starting', access_granted=False, experimental=True,
                                   identity_continuity_checked=False)
                self.worker = threading.Thread(target=self._run, args=(settings, preparation_mode), name='challenge-session', daemon=True)
                try:
                    self.worker.start()
                except Exception:
                    maintenance.challenge_running.clear()
                    maintenance.requested.clear()
                    raise
        finally:
            calibration_session.lock.release()
        return self.status()

    def cancel(self, session_id):
        with self.lock:
            if not session_id or session_id != self.session_id:
                raise ValueError('Неизвестная сессия заданий')
            self.cancelled.set()
        return self.status()

    def _publish(self, flow):
        with self.lock:
            self.result = flow.snapshot(time.monotonic())
            self.result['display_available'] = not isinstance(maintenance.display, NullDisplay)

    def _run(self, settings, preparation_mode=False):
        flow = ChallengeFlow(settings, preparation_mode=preparation_mode, verify_identity=False)
        created_at = datetime.now(timezone.utc).isoformat()
        display = maintenance.display
        try:
            with maintenance.lock, measure_time('Случайные задания', summary=True):
                manager = get_camera_manager()
                manager.start()
                sequence = 0
                last_stage = None
                while not flow.finished:
                    if self.cancelled.is_set():
                        flow.fail('cancelled')
                        break
                    flow.check_timeout(time.monotonic())
                    if flow.finished:
                        break
                    if flow.stage != last_stage:
                        detail = 'Смотрите\nпрямо\nГлаза открыты' if flow.stage == 'baseline' else 'Вернитесь\nв исходное\nположение'
                        display.show_state(DisplayState.CHALLENGE, detail)
                        last_stage = flow.stage
                    with measure_time('Задания: свежий кадр'):
                        frame = manager.get_latest_frame('primary', timeout=0.5)
                        if frame is not None and frame.sequence <= sequence:
                            frame = manager.get_frame('primary', after_sequence=sequence, timeout=0.5)
                    if frame is None:
                        flow.fail('camera_unavailable')
                        break
                    now = time.monotonic()
                    age = now - frame.timestamp_ns / 1e9
                    gap = None if flow.last_timestamp is None else frame.timestamp_ns / 1e9 - flow.last_timestamp
                    flow.frame_timing = dict(sequence=frame.sequence, previous_sequence=sequence,
                        stage=flow.stage, command=flow.command,
                        age_before_processing_ms=age * 1000, frame_age_limit_ms=500,
                        observation_gap_ms=None if gap is None else gap * 1000,
                        observation_limit_ms=settings['max_gap_seconds'] * 1000,
                        age_after_processing_ms=None, processing_ms=None)
                    if frame.sequence <= sequence or not 0 <= age <= 0.5:
                        flow.frame_timing['failure'] = ('non_increasing_sequence' if frame.sequence <= sequence
                            else 'future_frame_timestamp' if age < 0 else 'frame_too_old_before_processing')
                        flow.fail('stale_frame')
                        break
                    sequence = frame.sequence
                    processing_started = time.perf_counter()
                    durations = {}
                    with measure_time('Задания: детекция и ключевые точки'):
                        try:
                            observation = observe_face(frame.image, frame.timestamp_ns / 1e9, durations,
                                                       verify_identity=False)
                            flow.frame_timing['head_pose'] = observation.head_pose
                        except ValueError as error:
                            if str(error) in ('face_lost', 'landmarks_not_detected'):
                                flow.missing_observation(str(error))
                                self._publish(flow)
                                self.cancelled.wait(0.1)
                                continue
                            raise
                        finally:
                            flow.frame_timing['stages_ms'] = {name: sum(values) for name, values in durations.items()}
                            flow.frame_timing['processing_ms'] = (time.perf_counter() - processing_started) * 1000
                            flow.frame_timing['age_after_processing_ms'] = (time.monotonic() - frame.timestamp_ns / 1e9) * 1000
                            log_info(f'Проверка заданий: сессия {self.session_id}, профиль кадра: '
                                     + json.dumps(flow.frame_timing, ensure_ascii=False))
                    flow.feed(observation, time.monotonic())
                    if flow.stage == 'prompt':
                        if flow.tasks:
                            flow.tasks[-1]['prompt_started_s'] = flow.task_time(time.monotonic())
                        display.show_state(DisplayState.CHALLENGE, COMMANDS[flow.command])
                        # Старые кадры до завершения вывода команды не засчитываются
                        flow.acknowledge_prompt(time.monotonic())
                        last_stage = 'action'
                    self._publish(flow)
                if self.cancelled.is_set():
                    flow.fail('cancelled')
        except ValueError as error:
            known = ('face_lost', 'multiple_faces', 'landmarks_not_detected')
            flow.fail(str(error) if str(error) in known else 'processing_error')
        except Exception as error:
            flow.fail('processing_error')
            log_error(f'Ошибка сессии заданий: {type(error).__name__}')
        finally:
            if flow.reason == 'stale_frame':
                log_info(f'Проверка заданий: сессия {self.session_id}, диагностика stale_frame: '
                         + json.dumps(flow.frame_timing, ensure_ascii=False))
            # Сброс дисплея выполняется до возвращения управления монитору
            try:
                display.show_state(DisplayState.CHALLENGE,
                                   'Задания\nвыполнены' if flow.stage == 'passed' else 'Проверка\nне пройдена')
                self.cancelled.wait(1)
                display.show_state(DisplayState.STANDBY)
            except Exception as error:
                log_error(f'Проверка заданий: не удалось восстановить TFT после заданий: {type(error).__name__}: {error}')
            self._publish(flow)
            if self.session_id is not None:
                report = flow.snapshot(time.monotonic())
                report.update(version=1, session_id=self.session_id, created_at=created_at,
                              settings=dict(settings), timestamp_source='read_complete_monotonic',
                              pose_is_estimate=True, diagnostic_only=True,
                              pose_convention='degrees; object_to_camera; Rz(roll)*Ry(yaw)*Rx(pitch); X_right_Y_down_Z_forward',
                              timing_kind='sampled_threshold_crossings_not_true_motion_onset',
                              prompt_timestamp_source='display_call_completed_not_physical_display_measurement')
                try:
                    folder = Path(__file__).resolve().parent.parent / 'data' / 'challenge_checks'
                    folder.mkdir(parents=True, exist_ok=True)
                    write_json(folder / f'{self.session_id}.json', report)
                    log_info(f'Проверка заданий: сохранён отчёт {self.session_id}.json')
                except OSError as error:
                    log_error(f'Проверка заданий: не удалось сохранить отчёт: {error}')
            flow.anchor = None
            flow.neutral_samples.clear()
            with maintenance.lock:
                maintenance.challenge_running.clear()
                maintenance.requested.clear()
            log_info(f'Проверка заданий: сессия {self.session_id}, результат {flow.stage}, '
                     f'причина {flow.reason}, заданий {flow.completed}; '
                     'подмена участника не контролируется; замок не управляется')


challenge_session = ChallengeSession()
