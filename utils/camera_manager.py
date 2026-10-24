import atexit
import json
import os
import threading
import time
from collections import deque
from pathlib import Path

import cv2

from utils.config_loader import load_config
from utils.frame_pairing import CameraFrame, FramePairer
from utils.logger import log_error, log_info, log_warning

try:
    import fcntl
except ImportError:  # pragma: no cover - проект запускается на Linux
    fcntl = None


class CameraError(RuntimeError):
    pass


class CameraBusyError(CameraError):
    pass


class CameraUnavailableError(CameraError):
    pass


def _device_identity(source):
    if isinstance(source, int):
        return str(Path(f'/dev/video{source}').resolve())
    return str(Path(str(source)).resolve())


def find_camera_sources(max_index=10):
    """Находит стабильные пути камер и резервные video-индексы"""
    sources = []
    found_devices = set()

    for folder in ('/dev/v4l/by-id', '/dev/v4l/by-path'):
        path = Path(folder)
        if not path.exists():
            continue

        for camera_path in sorted(path.glob('*-video-index0')):
            device_id = _device_identity(str(camera_path))
            if device_id not in found_devices:
                sources.append(str(camera_path))
                found_devices.add(device_id)

    for index in range(max_index):
        device_path = Path(f'/dev/video{index}')
        if not device_path.exists():
            continue

        device_id = _device_identity(index)
        if device_id not in found_devices:
            sources.append(index)
            found_devices.add(device_id)

    return sources


def _normalize_source(source):
    if isinstance(source, str) and source.isdigit():
        return int(source)
    return source


def _decode_fourcc(value):
    """Преобразует числовой код OpenCV в короткое имя формата"""
    code = int(value or 0)
    if code == 0:
        return None
    return ''.join(chr((code >> (8 * index)) & 0xFF) for index in range(4))


class CameraReader:
    """Постоянно читает одну камеру в отдельном потоке"""

    def __init__(
        self,
        role,
        source,
        settings,
        frame_callback=None,
        buffer_size=8,
        max_read_failures=20,
        capture_factory=cv2.VideoCapture,
    ):
        self.role = role
        self.source = _normalize_source(source)
        self.settings = settings
        self.frame_callback = frame_callback
        self.max_read_failures = max_read_failures
        self.capture_factory = capture_factory

        self.frames = deque(maxlen=buffer_size)
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = None
        self.capture = None

        self.sequence = 0
        self.frame_count = 0
        self.read_failures = 0
        self.first_timestamp_ns = None
        self.last_timestamp_ns = None
        self.read_time_sum_ms = 0.0
        self.max_read_time_ms = 0.0
        self.error = None
        self.actual_width = None
        self.actual_height = None
        self.reported_fps = None
        self.reported_format = None

    def start(self):
        self.capture = self.capture_factory(self.source)
        if not self.capture.isOpened():
            self.capture.release()
            self.capture = None
            raise CameraUnavailableError(
                f"Камера {self.role} не открылась"
            )

        self._apply_settings()
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._read_loop,
            name=f'camera-{self.role}',
            daemon=True,
        )
        self.thread.start()

    def _apply_settings(self):
        image_format = self.settings.get('format')
        width = self.settings.get('width')
        height = self.settings.get('height')
        fps = self.settings.get('fps')

        if image_format:
            image_format = str(image_format).upper()
            if len(image_format) != 4:
                raise CameraError('Формат камеры должен состоять из 4 символов')
            fourcc = cv2.VideoWriter_fourcc(*image_format)
            self.capture.set(cv2.CAP_PROP_FOURCC, fourcc)
        if width:
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
        if height:
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
        if fps:
            self.capture.set(cv2.CAP_PROP_FPS, float(fps))
        if hasattr(cv2, 'CAP_PROP_BUFFERSIZE'):
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # cap.set() может быть проигнорирован, поэтому сохраняем реальные значения
        self.actual_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.actual_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.reported_fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0)
        self.reported_format = _decode_fourcc(
            self.capture.get(cv2.CAP_PROP_FOURCC)
        )

    def _read_loop(self):
        consecutive_failures = 0

        while not self.stop_event.is_set():
            read_started = time.perf_counter()
            success, image = self.capture.read()
            read_time_ms = (time.perf_counter() - read_started) * 1000
            timestamp_ns = time.monotonic_ns()

            if not success or image is None:
                self.read_failures += 1
                consecutive_failures += 1
                if consecutive_failures >= self.max_read_failures:
                    self.error = 'Камера перестала отдавать кадры'
                    log_error(f"{self.role}: {self.error}")
                    break
                time.sleep(0.01)
                continue

            consecutive_failures = 0
            self.sequence += 1
            self.frame_count += 1
            self.read_time_sum_ms += read_time_ms
            self.max_read_time_ms = max(self.max_read_time_ms, read_time_ms)

            if self.first_timestamp_ns is None:
                self.first_timestamp_ns = timestamp_ns
            self.last_timestamp_ns = timestamp_ns

            frame = CameraFrame(
                role=self.role,
                sequence=self.sequence,
                timestamp_ns=timestamp_ns,
                image=image,
                read_time_ms=read_time_ms,
            )

            with self.condition:
                self.frames.append(frame)
                self.condition.notify_all()

            if self.frame_callback:
                self.frame_callback(frame)

        with self.condition:
            self.condition.notify_all()

    def get_frame(self, after_sequence=0, timeout=1.0):
        deadline = time.monotonic() + timeout

        with self.condition:
            while True:
                for frame in self.frames:
                    if frame.sequence > after_sequence:
                        return frame

                if self.error or self.stop_event.is_set():
                    return None

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)

    def get_latest_frame(self, timeout=1.0):
        """Возвращает самый свежий кадр из памяти"""
        deadline = time.monotonic() + timeout

        with self.condition:
            while not self.frames:
                if self.error or self.stop_event.is_set():
                    return None

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)

            return self.frames[-1]

    def stop(self):
        self.stop_event.set()
        if self.capture is not None:
            self.capture.release()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        self.capture = None
        self.thread = None

    def get_status(self):
        actual_fps = 0.0
        if (
            self.frame_count > 1
            and self.first_timestamp_ns is not None
            and self.last_timestamp_ns > self.first_timestamp_ns
        ):
            elapsed = (self.last_timestamp_ns - self.first_timestamp_ns) / 1_000_000_000
            actual_fps = (self.frame_count - 1) / elapsed

        return {
            'role': self.role,
            'status': 'error' if self.error else 'online',
            'width': self.actual_width,
            'height': self.actual_height,
            'requested_format': self.settings.get('format'),
            'reported_format': self.reported_format,
            'requested_fps': self.settings.get('fps'),
            'reported_fps': self.reported_fps,
            'actual_fps': actual_fps,
            'frames': self.frame_count,
            'read_failures': self.read_failures,
            'average_read_ms': (
                self.read_time_sum_ms / self.frame_count
                if self.frame_count
                else None
            ),
            'max_read_ms': self.max_read_time_ms if self.frame_count else None,
            'error': self.error,
        }


class CameraManager:
    """Управление основной и дополнительной камерой"""

    def __init__(
        self,
        config=None,
        dual_mode=None,
        capture_factory=cv2.VideoCapture,
        use_process_lock=True,
    ):
        self.config = config or load_config()
        self.cameras_config = self.config.get('cameras', {})
        self.dual_mode = (
            self.cameras_config.get('enabled', False)
            if dual_mode is None
            else dual_mode
        )
        self.capture_factory = capture_factory
        self.use_process_lock = use_process_lock

        pair_delta = self.cameras_config.get('pair_max_delta_ms', 80)
        buffer_size = self.cameras_config.get('buffer_size', 8)
        self.pairer = FramePairer(pair_delta, buffer_size)
        self.readers = {}
        self.sources = {}
        self.source_candidates = []
        self.started = False
        self.state_lock = threading.Lock()
        self.capture_lock = threading.Lock()
        self.lock_handle = None
        self.pairing_enabled = False

    def start(self, require_secondary=False):
        with self.state_lock:
            if self.started:
                if require_secondary and 'secondary' not in self.readers:
                    raise CameraUnavailableError('Дополнительная камера недоступна')
                return

            self._get_process_lock()
            try:
                self.pairing_enabled = self.dual_mode or require_secondary
                self.sources = self._choose_sources()
                self._start_reader('primary')

                if self.dual_mode or require_secondary:
                    try:
                        self._start_reader('secondary')
                    except CameraUnavailableError:
                        if self.dual_mode or require_secondary:
                            raise
                        log_warning('Дополнительная камера недоступна')

                self.started = True
                log_info('Менеджер камер запущен')
            except Exception:
                self._stop_readers()
                self._release_process_lock()
                raise

    def _choose_sources(self):
        max_index = int(self.cameras_config.get('scan_max_index', 10))
        self.source_candidates = find_camera_sources(max_index)

        primary_settings = self._settings_for_camera_from_config('primary')
        secondary_settings = self._settings_for_camera_from_config('secondary')
        primary = _normalize_source(primary_settings.get('device'))
        secondary = _normalize_source(secondary_settings.get('device'))

        if primary is None and not self.source_candidates:
            raise CameraUnavailableError('Основная камера не найдена')

        return {'primary': primary, 'secondary': secondary}

    def _settings_for_camera_from_config(self, role):
        return dict(self.cameras_config.get(role, {}))

    def _start_reader(self, role):
        configured_source = self.sources.get(role)
        candidates = (
            [configured_source]
            if configured_source is not None
            else self.source_candidates
        )
        used_devices = {
            _device_identity(reader.source) for reader in self.readers.values()
        }

        for source in candidates:
            if _device_identity(source) in used_devices:
                continue

            reader = CameraReader(
                role=role,
                source=source,
                settings=self._settings_for_camera_from_config(role),
                frame_callback=(
                    self.pairer.add_frame
                    if self.pairing_enabled
                    else None
                ),
                buffer_size=int(self.cameras_config.get('buffer_size', 8)),
                max_read_failures=int(self.cameras_config.get('max_read_failures', 20)),
                capture_factory=self.capture_factory,
            )
            try:
                reader.start()
            except CameraUnavailableError:
                if configured_source is not None:
                    raise
                continue

            self.sources[role] = source
            self.readers[role] = reader
            log_info(f"Камера {role} открыта")
            return

        raise CameraUnavailableError(f"Камера {role} не найдена или не открылась")

    def get_frame(self, role='primary', after_sequence=0, timeout=1.0):
        self.start(require_secondary=(role == 'secondary'))
        self._check_required_cameras()
        reader = self.readers.get(role)
        if reader is None:
            return None
        frame = reader.get_frame(after_sequence, timeout)
        self._check_required_cameras()
        return frame

    def get_latest_frame(self, role='primary', timeout=1.0):
        self.start(require_secondary=(role == 'secondary'))
        self._check_required_cameras()
        reader = self.readers.get(role)
        if reader is None:
            return None
        frame = reader.get_latest_frame(timeout)
        self._check_required_cameras()
        return frame

    def get_last_sequence(self, role='primary'):
        self.start(require_secondary=(role == 'secondary'))
        reader = self.readers.get(role)
        return reader.sequence if reader else 0

    def get_pair(self, after_number=0, timeout=1.0):
        self.start(require_secondary=True)
        self._check_required_cameras(require_secondary=True)
        pair = self.pairer.wait_for_pair(after_number, timeout)
        self._check_required_cameras(require_secondary=True)
        return pair

    def _check_required_cameras(self, require_secondary=False):
        required_roles = ['primary']
        if self.dual_mode or require_secondary:
            required_roles.append('secondary')

        for role in required_roles:
            reader = self.readers.get(role)
            if reader is None:
                raise CameraUnavailableError(f"Камера {role} недоступна")
            if reader.error:
                raise CameraUnavailableError(
                    f"Камера {role} потеряна: {reader.error}"
                )

    def stop(self):
        with self.state_lock:
            self._stop_readers()
            self._release_process_lock()
            self.started = False

    def _stop_readers(self):
        for reader in self.readers.values():
            reader.stop()
        self.readers.clear()

    def _get_process_lock(self):
        """Не даёт двум процессам одновременно использовать камеры"""
        if not self.use_process_lock or fcntl is None:
            return

        # Все процессы используют один и тот же файл
        lock_path = self.cameras_config.get(
            'lock_file', '/tmp/face_recognition_cameras.lock'
        )

        # Запись в файл не нужна, он используется только как блокировка
        # Режим чтения позволяет открыть файл после запуска через sudo
        descriptor = os.open(lock_path, os.O_RDONLY | os.O_CREAT, 0o666)
        self.lock_handle = os.fdopen(descriptor, 'r', encoding='utf-8')
        try:
            # Если файл уже занят, сразу выдаём ошибку и не ждём
            fcntl.flock(
                self.lock_handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as error:
            # Другой процесс уже работает с камерами
            self.lock_handle.close()
            self.lock_handle = None
            raise CameraBusyError(
                'Камеры уже используются другим процессом'
            ) from error

    def _release_process_lock(self):
        if self.lock_handle is None:
            return
        if fcntl is not None:
            fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_UN)
        self.lock_handle.close()
        self.lock_handle = None

    def get_status(self):
        cameras = {}
        for role in ('primary', 'secondary'):
            reader = self.readers.get(role)
            if reader:
                cameras[role] = reader.get_status()
            else:
                cameras[role] = {
                    'role': role,
                    'status': 'disabled' if role == 'secondary' and not self.dual_mode else 'offline',
                    'width': None,
                    'height': None,
                    'requested_format': self._settings_for_camera_from_config(role).get('format'),
                    'reported_format': None,
                    'requested_fps': self._settings_for_camera_from_config(role).get('fps'),
                    'reported_fps': None,
                    'actual_fps': 0.0,
                    'frames': 0,
                    'read_failures': 0,
                    'average_read_ms': None,
                    'max_read_ms': None,
                    'error': None,
                }

        return {
            'started': self.started,
            'dual_mode_enabled': bool(self.dual_mode),
            'cameras': cameras,
            'pairing': self.pairer.get_metrics(),
        }


_camera_manager = None
_manager_lock = threading.Lock()


def get_camera_manager():
    global _camera_manager
    with _manager_lock:
        if _camera_manager is None:
            _camera_manager = CameraManager()
            # При завершении программы вызываем stop
            atexit.register(_camera_manager.stop)
        return _camera_manager


def stop_camera_manager():
    global _camera_manager
    with _manager_lock:
        if _camera_manager is not None:
            _camera_manager.stop()
            _camera_manager = None


def _public_status(status, source, updated_at=None):
    cameras = {}
    for role in ('primary', 'secondary'):
        camera = status.get('cameras', {}).get(role, {})
        cameras[role] = {
            'role': role,
            'status': camera.get('status', 'offline'),
            'width': camera.get('width'),
            'height': camera.get('height'),
            'requested_format': camera.get('requested_format'),
            'reported_format': camera.get('reported_format'),
            'requested_fps': camera.get('requested_fps'),
            'actual_fps': camera.get('actual_fps', 0.0),
            'average_read_ms': camera.get('average_read_ms'),
            'max_read_ms': camera.get('max_read_ms'),
            'error': camera.get('error'),
        }

    pairing = status.get('pairing', {})
    return {
        'status': 'success',
        'source': source,
        'updated_at': updated_at,
        'dual_mode_enabled': status.get('dual_mode_enabled', False),
        'cameras': cameras,
        'pairing': {
            'paired_frames': pairing.get('paired_frames', 0),
            'average_delta_ms': pairing.get('average_delta_ms'),
            'max_delta_ms': pairing.get('max_delta_ms'),
            'drop_rate': pairing.get('drop_rate', 0.0),
        },
    }


def get_public_camera_status():
    manager = get_camera_manager()
    live_status = manager.get_status()
    if live_status['started']:
        return _public_status(live_status, source='live')

    config = load_config()
    report_name = config.get('cameras', {}).get(
        'diagnostic_report', 'data/camera_diagnostics.json'
    )
    report_path = Path(report_name)
    if not report_path.is_absolute():
        report_path = Path(__file__).parent.parent / report_path

    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return _public_status(live_status, source='configuration')

    report_status = {
        'dual_mode_enabled': True,
        'cameras': report.get('cameras', {}),
        'pairing': report.get('pairing', {}),
    }
    return _public_status(
        report_status,
        source='diagnostic',
        updated_at=report.get('generated_at'),
    )
