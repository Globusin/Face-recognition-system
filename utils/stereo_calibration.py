"""Калибровка неподвижной пары камер по шахматной доске"""

import json
import base64
import threading
import time
import uuid
import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from utils.camera_manager import get_camera_manager
from utils.config_loader import load_config
from utils.maintenance import maintenance
from utils.logger import log_info
from utils.calibration_quality import measure_planarity, measure_depth_stability


BOARD = (7, 7)
SQUARE_MM = 45.0


def find_board(image, rotation=0):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found, corners = cv2.findChessboardCorners(
        gray, BOARD, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
    )
    if not found:
        return None

    corners = cv2.cornerSubPix(
        gray, corners, (11, 11), (-1, -1),
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
    )

    return np.ascontiguousarray(np.rot90(corners.reshape(7, 7, 2), rotation).reshape(-1, 1, 2))


def validate_square_mm(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
        raise ValueError('Размер клетки должен быть положительным числом в миллиметрах')

    return float(value)


def board_points(square_mm=SQUARE_MM):
    points = np.zeros((49, 3), np.float32)
    points[:, :2] = np.mgrid[0:7, 0:7].T.reshape(-1, 2) * validate_square_mm(square_mm)

    return points


def solve_calibration(training, validation, image_size, square_mm=SQUARE_MM):
    """Контрольные пары не участвуют в подгонке параметров"""
    if len(training) < 15 or len(validation) < 3:
        raise ValueError('Нужно не менее 15 обучающих и 3 контрольных пар')

    square_mm = validate_square_mm(square_mm)
    objects = [board_points(square_mm) for _ in training]
    primary = [pair['primary'] for pair in training]
    secondary = [pair['secondary'] for pair in training]

    # Ошибка в пикселях, матрица камеры и коэффициенты искажения объектива
    # Повороты и смещения доски не используем
    primary_rms, primary_camera_matrix, primary_distortion, _, _ = cv2.calibrateCamera(
        objects, primary, image_size, None, None,
    )
    secondary_rms, secondary_camera_matrix, secondary_distortion, _, _ = cv2.calibrateCamera(
        objects, secondary, image_size, None, None,
    )

    (
        rms,
        primary_camera_matrix, primary_distortion,
        secondary_camera_matrix, secondary_distortion,
        rotation, translation, essential, fundamental,
    ) = cv2.stereoCalibrate(
        objects, primary, secondary, primary_camera_matrix, primary_distortion,
        secondary_camera_matrix, secondary_distortion, image_size,
        flags=cv2.CALIB_FIX_INTRINSIC,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-6),
    )

    (
        primary_rectification, secondary_rectification,  # Повороты для выравнивания ракурсов камер
        primary_projection, secondary_projection,  # Матрицы проекции выровненных камер
        disparity_to_depth,  # Матрица перевода смещения между изображениями в 3D-координаты
        primary_valid_roi, secondary_valid_roi,  # Области без пустых краёв после выравнивания: x, y, ширина, высота
    ) = cv2.stereoRectify(
        primary_camera_matrix, primary_distortion, secondary_camera_matrix, secondary_distortion,
        image_size, rotation, translation,
        flags=cv2.CALIB_ZERO_DISPARITY, alpha=0,
    )

    maps1 = cv2.initUndistortRectifyMap(
        primary_camera_matrix, primary_distortion, primary_rectification, primary_projection,
        image_size, cv2.CV_32FC1,
    )
    maps2 = cv2.initUndistortRectifyMap(
        secondary_camera_matrix, secondary_distortion, secondary_rectification, secondary_projection,
        image_size, cv2.CV_32FC1,
    )

    vertical = []
    reprojection = []

    for pair in validation:
        a = cv2.undistortPoints(pair['primary'], primary_camera_matrix, primary_distortion,
                              R=primary_rectification, P=primary_projection)
        b = cv2.undistortPoints(pair['secondary'], secondary_camera_matrix, secondary_distortion,
                              R=secondary_rectification, P=secondary_projection)
        vertical.extend(np.abs(a[:, 0, 1] - b[:, 0, 1]).tolist())

        # Положение доски оценивается по основной камере, вторая её не подгоняет
        ok, rvec, tvec = cv2.solvePnP(board_points(square_mm), pair['primary'], primary_camera_matrix, primary_distortion)
        if not ok:
            raise ValueError('Не удалось оценить позу контрольной доски')

        board_rotation, _ = cv2.Rodrigues(rvec)
        predicted_rvec, _ = cv2.Rodrigues(rotation @ board_rotation)
        predicted_tvec = rotation @ tvec + translation
        predicted, _ = cv2.projectPoints(board_points(square_mm), predicted_rvec, predicted_tvec,
                                        secondary_camera_matrix, secondary_distortion)
        reprojection.extend(np.linalg.norm(predicted[:, 0] - pair['secondary'][:, 0], axis=1).tolist())

    metrics = {
        'primary_rms_px': float(primary_rms), 'secondary_rms_px': float(secondary_rms),
        'stereo_rms_px': float(rms),
        'validation_vertical_mean_px': float(np.mean(vertical)),
        'validation_vertical_max_px': float(np.max(vertical)),
        'validation_reprojection_mean_px': float(np.mean(reprojection)),
        'baseline_mm': float(np.linalg.norm(translation)),
        'training_pairs': len(training), 'validation_pairs': len(validation),
        'valid_roi_primary': list(map(int, primary_valid_roi)),
        'valid_roi_secondary': list(map(int, secondary_valid_roi)),
    }

    overlap_left = max(primary_valid_roi[0], secondary_valid_roi[0])
    overlap_top = max(primary_valid_roi[1], secondary_valid_roi[1])
    overlap_width = max(0, min(primary_valid_roi[0] + primary_valid_roi[2],
                               secondary_valid_roi[0] + secondary_valid_roi[2]) - overlap_left)
    overlap_height = max(0, min(primary_valid_roi[1] + primary_valid_roi[3],
                                secondary_valid_roi[1] + secondary_valid_roi[3]) - overlap_top)
    metrics['valid_overlap_roi'] = list(map(int, (overlap_left, overlap_top, overlap_width, overlap_height)))

    arrays = dict(k1=primary_camera_matrix, d1=primary_distortion,
                  k2=secondary_camera_matrix, d2=secondary_distortion, R=rotation, T=translation,
                  E=essential, F=fundamental,
                  R1=primary_rectification, R2=secondary_rectification,
                  P1=primary_projection, P2=secondary_projection, Q=disparity_to_depth,
                  map1_x=maps1[0], map1_y=maps1[1], map2_x=maps2[0], map2_y=maps2[1])

    if (not all(np.isfinite(value).all() for value in arrays.values())
            or not all(np.isfinite(value) for key, value in metrics.items() if isinstance(value, float))
            or metrics['baseline_mm'] <= 0):
        raise ValueError('Калибровка содержит некорректные числа')

    return arrays, metrics


def triangulate_board(primary, secondary, arrays):
    points = []

    for corners, suffix in ((primary, '1'), (secondary, '2')):
        corners = np.asarray(corners, dtype=np.float64)
        if corners.size != 98 or not np.isfinite(corners).all():
            raise ValueError('Нужно 49 корректных углов в каждой камере')

        points.append(cv2.undistortPoints(corners.reshape(49, 1, 2), arrays['k' + suffix],
                      arrays['d' + suffix], R=arrays['R' + suffix], P=arrays['P' + suffix])[:, 0])

    homogeneous = cv2.triangulatePoints(arrays['P1'], arrays['P2'], points[0].T, points[1].T)
    if np.any(np.abs(homogeneous[3]) < 1e-10):
        raise ValueError('Невозможно измерить глубину: вырожденная триангуляция')

    xyz = (homogeneous[:3] / homogeneous[3]).T
    projected = [matrix @ np.vstack((xyz.T, np.ones(49))) for matrix in (arrays['P1'], arrays['P2'])]
    if not np.isfinite(xyz).all() or any(np.any(p[2] <= 0) for p in projected):
        raise ValueError('Точки находятся за камерой или имеют некорректную глубину')

    return xyz, points


def measure_board_geometry(primary, secondary, arrays, square_mm=SQUARE_MM):
    """Размер клетки проверяется после триангуляции, а не задаётся ей"""
    square_mm = validate_square_mm(square_mm)
    xyz, points = triangulate_board(primary, secondary, arrays)

    grid = xyz.reshape(7, 7, 3)
    lengths = np.concatenate((np.linalg.norm(np.diff(grid, axis=0), axis=2).ravel(),
                              np.linalg.norm(np.diff(grid, axis=1), axis=2).ravel()))
    if not np.isfinite(lengths).all():
        raise ValueError('Некорректные расстояния после триангуляции')

    errors = np.abs(lengths - square_mm)
    vertical = np.abs(points[0][:, 1] - points[1][:, 1])

    return dict(expected_mm=square_mm, segments=len(lengths), mean_length_mm=float(lengths.mean()),
                mean_error_mm=float(errors.mean()), max_error_mm=float(errors.max()),
                mean_error_percent=float(errors.mean() / square_mm * 100),
                vertical_mean_px=float(vertical.mean()), vertical_max_px=float(vertical.max()),
                **measure_planarity(xyz))


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def calibration_fingerprint(folder, metadata, parameter_bytes=None):
    identity = {key: metadata.get(key) for key in (
        'version', 'created_at', 'session_id', 'units', 'board', 'square_mm', 'image_size', 'cameras')}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode())
    if parameter_bytes is not None:
        digest.update(parameter_bytes)
        return digest.hexdigest()
    with (Path(folder) / 'parameters.npz').open('rb') as source:
        for block in iter(lambda: source.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def load_calibration(folder, cameras, mounting_confirmed=False, *, allow_unvalidated=False):
    """Не позволяет молча применить параметры другого режима или монтажа"""
    if not mounting_confirmed:
        raise ValueError('Подтвердите неизменность крепления, фокуса и режима камер')

    metadata = json.loads((Path(folder) / 'metadata.json').read_text(encoding='utf-8'))
    if metadata.get('version') != 1 or metadata.get('cameras') != cameras:
        raise ValueError('Калибровка не соответствует камерам или версии формата')
    if metadata.get('status') == 'invalidated':
        raise ValueError('Калибровка помечена недействительной')
    if metadata.get('status') not in ('requires_review', 'validated'):
        raise ValueError('Неизвестный статус калибровки')
    if not allow_unvalidated and metadata.get('status') != 'validated':
        raise ValueError('Калибровка не подтверждена на независимых данных')
    # Проверяем и загружаем одни и те же байты, даже если файл заменят параллельно
    parameter_bytes = (Path(folder) / 'parameters.npz').read_bytes()
    if not allow_unvalidated:
        validation = metadata.get('validation', {})
        if (metadata.get('status') != 'validated' or not isinstance(validation, dict)
                or type(validation.get('checks_count')) is not int or validation['checks_count'] < 3
                or validation.get('fingerprint') != calibration_fingerprint(folder, metadata, parameter_bytes)):
            raise ValueError('Калибровка не подтверждена на независимых данных или параметры изменились')

    width, height = metadata['image_size']
    required = ('k1', 'k2', 'd1', 'd2', 'R', 'T', 'R1', 'R2', 'P1', 'P2', 'Q',
                'map1_x', 'map1_y', 'map2_x', 'map2_y')

    with np.load(io.BytesIO(parameter_bytes), allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in required}

    if not all(np.isfinite(value).all() for value in arrays.values()):
        raise ValueError('Некорректные значения калибровки')

    for key in ('map1_x', 'map1_y', 'map2_x', 'map2_y'):
        if arrays[key].shape != (height, width):
            raise ValueError('Размер карт ректификации не совпадает с режимом камеры')

    if any(arrays[key].shape != (3, 3) for key in ('k1', 'k2', 'R', 'R1', 'R2')):
        raise ValueError('Некорректные размеры матриц калибровки')
    if (arrays['Q'].shape != (4, 4) or arrays['T'].shape != (3, 1)
            or arrays['P1'].shape != (3, 4) or arrays['P2'].shape != (3, 4)):
        raise ValueError('Некорректные размеры матриц ректификации')

    return metadata, arrays


def annotated_preview(image, corners):
    preview = image.copy()
    if corners is not None:
        cv2.drawChessboardCorners(preview, BOARD, corners, True)
        for index, color in ((0, (0, 0, 255)), (6, (0, 255, 255))):
            position = tuple(np.rint(corners[index, 0]).astype(int))
            cv2.circle(preview, position, 10, color, 3)
            cv2.putText(preview, str(index + 1), position, cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
    scale = min(1, 640 / preview.shape[1])
    preview = cv2.resize(preview, (round(preview.shape[1] * scale), round(preview.shape[0] * scale)))
    ok, jpeg = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise ValueError('Не удалось подготовить превью')
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')


class CalibrationSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.active = False
        self.session_id = None
        self.samples = [] # Сохранённые пары углов доски с метками обучающих и контрольных пар
        self.observation = None # Текущая пара кадров и найденные углы до сохранения
        self.result = None # Метаданные
        self.image_size = None
        self.signature = None # Устройства и режимы камер
        self.rectified_previews = None # Изображения в UI
        self.square_mm = SQUARE_MM # Сторона клетки
        self.timing_result = None

    def status(self):
        with self.lock:
            if self.result is None and not self.active:
                root = self._root()
                paths = sorted(root.glob('*/metadata.json'), key=lambda path: path.stat().st_mtime, reverse=True)

                if paths:
                    try:
                        self.result = json.loads(paths[0].read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        self.result = None

            result = None
            if self.result:
                result = {key: self.result[key] for key in (
                    'version', 'created_at', 'session_id', 'units', 'board', 'square_mm',
                    'image_size', 'metrics', 'status', 'validation',
                ) if key in self.result}

            return dict(active=self.active, session_id=self.session_id,
                        training_pairs=sum(not s['validation'] for s in self.samples),
                        validation_pairs=sum(s['validation'] for s in self.samples),
                        result=result, rectified_previews=self.rectified_previews,
                        board=list(BOARD), square_mm=self.square_mm)

    def start(self, square_mm=SQUARE_MM):
        with self.lock:
            square_mm = validate_square_mm(square_mm)
            if self.active:
                raise ValueError('Калибровка уже запущена')

            maintenance.begin()

            self.square_mm = square_mm
            self.session_id = uuid.uuid4().hex
            self.samples = []
            self.observation = None
            self.result = None
            self.image_size = None
            self.signature = None
            self.rectified_previews = None
            self.active = True
            self.timing_result = None

            log_info(f'Калибровка: начата сессия {self.session_id}, распознавание приостановлено')
            return self.status()

    def require_session(self, session_id):
        if not self.active or session_id != self.session_id:
            raise ValueError('Сессия калибровки неактивна или устарела')

    def _camera_signature(self, manager):
        status = manager.get_status()
        if not status['started'] or any(
            status['cameras'][role]['status'] != 'online' for role in ('primary', 'secondary')
        ):
            raise ValueError('Обе камеры должны работать в выбранном режиме')

        return {
            role: dict(device=str(manager.sources.get(role)),
                       width=status['cameras'][role]['width'],
                       height=status['cameras'][role]['height'],
                       format=status['cameras'][role]['reported_format'],
                       fps=status['cameras'][role]['reported_fps'])
            for role in ('primary', 'secondary')
        }

    def observe(self, session_id, rotation, prepare_preview=True):
        with self.lock:
            self.require_session(session_id)
            self.observation = None

            manager = get_camera_manager()
            manager.start(require_secondary=True)
            after = manager.get_status()['pairing']['paired_frames']
            pair = manager.get_pair(after_number=after, timeout=3)

            if pair is None:
                raise ValueError('Нет свежей пары кадров')
            if pair.delta_ms > manager.cameras_config.get('pair_max_delta_ms', 80):
                raise ValueError('Слишком большой рассинхрон кадров')
            if time.monotonic_ns() - min(pair.primary.timestamp_ns, pair.secondary.timestamp_ns) > 1_000_000_000:
                raise ValueError('Пара кадров устарела')

            images = {'primary': pair.primary.image.copy(), 'secondary': pair.secondary.image.copy()}
            sizes = [image.shape[1::-1] for image in images.values()]
            if sizes[0] != sizes[1]:
                raise ValueError('Для этого режима нужны одинаковые разрешения камер')

            signature = self._camera_signature(manager)
            if self.signature is not None and (signature != self.signature or sizes[0] != self.image_size):
                raise ValueError('Режим камер изменился, начните новую сессию')

            self.signature, self.image_size = signature, sizes[0]
            corners = {role: find_board(image, rotation if role == 'secondary' else 0)
                       for role, image in images.items()}

            observation_id = uuid.uuid4().hex
            self.observation = dict(id=observation_id, created=time.monotonic(), pair=pair,
                                    images=images, corners=corners, rotation=rotation)

            return dict(observation_id=observation_id, delta_ms=pair.delta_ms,
                        found={role: points is not None for role, points in corners.items()},
                        previews={role: annotated_preview(image, corners[role]) for role, image in images.items()}
                        if prepare_preview else {})

    def download_frame(self, session_id, observation_id, role):
        with self.lock:
            self.require_session(session_id)
            if role not in ('primary', 'secondary'):
                raise ValueError('Неизвестная камера')
            if not self.observation or self.observation['id'] != observation_id:
                raise ValueError('Обновите пару кадров')

            # Для диагностики можно скачать и пару старше 30 секунд
            ok, encoded = cv2.imencode('.png', self.observation['images'][role])
            if not ok:
                raise RuntimeError('Не удалось подготовить исходный кадр')

            return encoded.tobytes()

    def save_pair(self, session_id, observation_id, validation, confirmed):
        with self.lock:
            self.require_session(session_id)
            observation = self.observation

            if not observation or observation['id'] != observation_id:
                raise ValueError('Обновите пару кадров')
            if time.monotonic() - observation['created'] > 30:
                raise ValueError('Пара устарела, обновите изображения')
            if confirmed is not True:
                raise ValueError('Подтвердите соответствие углов 1 и 7')
            if self._camera_signature(get_camera_manager()) != self.signature:
                raise ValueError('Режим камер изменился, обновите сессию')
            if any(points is None for points in observation['corners'].values()):
                raise ValueError('Доска должна быть найдена обеими камерами')

            pair = observation['pair']
            if any(sample['pair_number'] == pair.number for sample in self.samples):
                raise ValueError('Эта пара кадров уже сохранена')

            sample = dict(observation['corners'], validation=bool(validation),
                          pair_number=pair.number, delta_ms=pair.delta_ms,
                          primary_sequence=pair.primary.sequence, secondary_sequence=pair.secondary.sequence,
                          primary_timestamp_ns=pair.primary.timestamp_ns, secondary_timestamp_ns=pair.secondary.timestamp_ns,
                          secondary_rotation=observation['rotation'])

            # Повтор почти того же положения не добавляет полезной геометрии
            if any(np.mean(np.linalg.norm(s['primary'] - sample['primary'], axis=2)) < 12
                   for s in self.samples):
                raise ValueError('Слишком похожая пара: измените положение или наклон доски')

            folder = self._session_folder()
            folder.mkdir(parents=True, exist_ok=True)
            index = len(self.samples) + 1

            for role, image in observation['images'].items():
                if not cv2.imwrite(str(folder / f'{index:03d}_{role}.png'), image):
                    raise ValueError('Не удалось сохранить изображения доски')

            self.samples.append(sample)
            try:
                self._write_samples()
            except OSError:
                self.samples.pop()
                raise

            self.observation = None
            self.result = None
            self.rectified_previews = None

            metadata_path = folder / 'metadata.json'
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
                metadata['status'] = 'invalidated'
                write_json(metadata_path, metadata)

            log_info(f'Калибровка: сессия {self.session_id}, сохранена пара {index}, контрольная={bool(validation)}')
            return self.status()

    def _root(self):
        settings = load_config().get('stereo_calibration', {})
        return Path(__file__).resolve().parent.parent / settings.get('output_dir', 'data/calibration')

    def _session_folder(self):
        return self._root() / self.session_id

    def _write_samples(self):
        data = [dict(sample, primary=sample['primary'].tolist(), secondary=sample['secondary'].tolist())
                for sample in self.samples]

        write_json(self._session_folder() / 'samples.json', data)
        write_json(self._session_folder() / 'session.json', dict(
            version=1, session_id=self.session_id, image_size=list(self.image_size),
            cameras=self.signature, units='mm', board=list(BOARD), square_mm=self.square_mm,
            pairing='software', timestamp_source='monotonic_ns_at_read',
            pair_max_delta_ms=load_config().get('cameras', {}).get('pair_max_delta_ms', 80),
        ))

    def calculate(self, session_id):
        with self.lock:
            self.require_session(session_id)
            if self._camera_signature(get_camera_manager()) != self.signature:
                raise ValueError('Режим камер изменился')

            arrays, metrics = solve_calibration(
                [s for s in self.samples if not s['validation']],
                [s for s in self.samples if s['validation']], self.image_size, self.square_mm,
            )

            metadata = dict(version=1, created_at=datetime.now(timezone.utc).isoformat(),
                            session_id=self.session_id, units='mm', board=list(BOARD),
                            square_mm=self.square_mm, image_size=list(self.image_size), cameras=self.signature,
                            reported_mount_baseline_mm=120, metrics=metrics,
                            status='requires_review', mounting_confirmed=True)

            folder = self._session_folder()
            np.savez_compressed(folder / 'parameters.npz', **arrays)
            write_json(folder / 'metadata.json', metadata)
            self.result = metadata

            log_info(f'Калибровка: сессия {self.session_id}, RMS={metrics["stereo_rms_px"]:.3f} px, требуется проверка')

            index = next(i for i, sample in enumerate(self.samples, 1) if sample['validation'])
            self.rectified_previews = {}

            for role, prefix in (('primary', 'map1'), ('secondary', 'map2')):
                image = cv2.imread(str(folder / f'{index:03d}_{role}.png'))
                if image is None:
                    raise ValueError('Контрольное изображение не найдено')

                image = cv2.remap(image, arrays[prefix + '_x'], arrays[prefix + '_y'], cv2.INTER_LINEAR)
                for y in range(0, image.shape[0], 40):
                    cv2.line(image, (0, y), (image.shape[1] - 1, y), (0, 255, 0), 1)
                self.rectified_previews[role] = annotated_preview(image, None)

            return self.status()

    def review(self, session_id, pair_index=None):
        """Просмотр сохранённых данных не активирует калибровку для допуска"""
        if not isinstance(session_id, str) or len(session_id) != 32 or any(
            char not in '0123456789abcdef' for char in session_id
        ):
            raise ValueError('Неверный номер сессии')

        with self.lock:
            folder = self._root() / session_id
            metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
            if metadata.get('status') == 'invalidated':
                raise ValueError('Калибровка помечена недействительной')

            samples = json.loads((folder / 'samples.json').read_text(encoding='utf-8'))
            indices = [i for i, sample in enumerate(samples, 1) if sample['validation']]
            if not indices:
                raise ValueError('В сессии нет контрольных пар')

            index = indices[0] if pair_index is None else pair_index
            if type(index) is not int or index not in indices:
                raise ValueError('Выберите контрольную пару этой сессии')

            previews = {}
            with np.load(folder / 'parameters.npz', allow_pickle=False) as arrays:
                sample = samples[index - 1]
                geometry = measure_board_geometry(sample.get('primary', []), sample.get('secondary', []),
                                                  arrays, metadata['square_mm'])
                log_info(f'Контрольная пара {index}: средняя ошибка {geometry["mean_error_mm"]:.3f} мм')

                for role, prefix in (('primary', 'map1'), ('secondary', 'map2')):
                    image = cv2.imread(str(folder / f'{index:03d}_{role}.png'))
                    if image is None or list(image.shape[1::-1]) != metadata['image_size']:
                        raise ValueError('Контрольный кадр отсутствует или имеет неверный размер')

                    if any(prefix + suffix not in arrays for suffix in ('_x', '_y')):
                        raise ValueError('В файле отсутствуют карты ректификации')
                    map_x, map_y = arrays[prefix + '_x'], arrays[prefix + '_y']
                    if any(grid.shape != image.shape[:2] or not np.isfinite(grid).all()
                           for grid in (map_x, map_y)):
                        raise ValueError('Некорректные карты ректификации')

                    image = cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR)
                    for y in range(0, image.shape[0], 40):
                        cv2.line(image, (0, y), (image.shape[1] - 1, y), (0, 255, 0), 1)
                    previews[role] = annotated_preview(image, None)

            return dict(session_id=session_id, pair_index=index, pair_indices=indices,
                        delta_ms=samples[index - 1].get('delta_ms'), previews=previews, geometry=geometry)

    def verify_observation(self, session_id, observation_id, calibration_id, confirmed, mounting_confirmed):
        with self.lock:
            self.require_session(session_id)
            observation = self.observation
            if not observation or observation['id'] != observation_id or time.monotonic() - observation['created'] > 30:
                raise ValueError('Обновите пару кадров')
            if confirmed is not True or mounting_confirmed is not True:
                raise ValueError('Подтвердите соответствие углов и неизменность крепления и фокуса')
            if not isinstance(calibration_id, str) or len(calibration_id) != 32 or any(
                char not in '0123456789abcdef' for char in calibration_id
            ):
                raise ValueError('Неверный номер сохранённой калибровки')
            if any(value is None for value in observation['corners'].values()):
                raise ValueError('Доска должна быть найдена обеими камерами')

            signature = self._camera_signature(get_camera_manager())
            if signature != self.signature:
                raise ValueError('Режим камер изменился, обновите пару')

            parameter_file = self._root() / calibration_id / 'parameters.npz'
            parameter_bytes = parameter_file.read_bytes()
            metadata, arrays = load_calibration(self._root() / calibration_id, signature,
                                                mounting_confirmed=True, allow_unvalidated=True)
            if parameter_file.read_bytes() != parameter_bytes:
                raise ValueError('Параметры изменились во время проверки, повторите наблюдение')
            if metadata.get('units') != 'mm' or metadata.get('board') != list(BOARD):
                raise ValueError('Параметры доски или единицы сохранённой калибровки не соответствуют проверке')
            if list(self.image_size) != metadata['image_size']:
                raise ValueError('Размер кадра не соответствует калибровке')

            geometry = measure_board_geometry(observation['corners']['primary'], observation['corners']['secondary'],
                                              arrays, self.square_mm)

            # Проверки внутри исходной сессии не служат независимым подтверждением
            check_id = None
            if session_id != calibration_id:
                check_id = observation_id
                folder = self._session_folder() / 'geometry_checks'
                folder.mkdir(parents=True, exist_ok=True)
                write_json(folder / f'{check_id}.json', dict(
                    observation_id=observation_id, calibration_id=calibration_id,
                    fingerprint=calibration_fingerprint(self._root() / calibration_id, metadata, parameter_bytes),
                    geometry=geometry, primary_corners=observation['corners']['primary'].tolist(),
                    created_at=datetime.now(timezone.utc).isoformat()))

            log_info(f'Проверка геометрии: средняя ошибка {geometry["mean_error_mm"]:.3f} мм, '
                     f'максимальная {geometry["max_error_mm"]:.3f} мм, параметры не изменены')
            return dict(geometry=geometry, calibration_id=calibration_id, observation_id=observation_id,
                        independent_check_id=check_id)

    def validate(self, session_id, calibration_id, mounting_confirmed, review_confirmed):
        with self.lock:
            self.require_session(session_id)
            if review_confirmed is not True or mounting_confirmed is not True:
                raise ValueError('Подтвердите проверку независимых пар и неизменность камер')
            if (not isinstance(calibration_id, str) or len(calibration_id) != 32
                    or any(char not in '0123456789abcdef' for char in calibration_id)
                    or calibration_id == session_id):
                raise ValueError('Для подтверждения нужна отдельная сессия проверок')
            signature = self._camera_signature(get_camera_manager())
            folder = self._root() / calibration_id
            metadata, _ = load_calibration(folder, signature, mounting_confirmed=True, allow_unvalidated=True)
            fingerprint = calibration_fingerprint(folder, metadata)
            checks = [json.loads(path.read_text(encoding='utf-8'))
                      for path in sorted((self._session_folder() / 'geometry_checks').glob('*.json'))]
            checks = [check for check in checks if check.get('calibration_id') == calibration_id]
            if len(checks) < 3:
                raise ValueError('Нужны минимум три независимые проверки доски в новой сессии')

            limits = load_config().get('stereo_calibration', {}).get('validation_limits', {})
            limits = {key: limits.get(key, default) for key, default in (
                ('mean_error_percent', 3.0), ('vertical_max_px', 3.0), ('plane_rms_mm', 2.0))}
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not np.isfinite(value) or value <= 0 for value in limits.values()):
                raise ValueError('Неверные пределы подтверждения калибровки')
            positions = []
            observations = set()
            metric_names = dict(mean_error_percent='Средняя ошибка размера клетки (%)',
                                vertical_max_px='Расхождение углов по вертикали (px)',
                                plane_rms_mm='RMS отклонения от плоскости (мм)')
            for check in checks:
                if check.get('fingerprint') != fingerprint:
                    raise ValueError('Параметры изменились после проверки, снимите независимые пары заново')
                if check['observation_id'] in observations:
                    raise ValueError('Одна пара не может считаться несколькими независимыми проверками')
                observations.add(check['observation_id'])
                for key, limit in limits.items():
                    value = check['geometry'].get(key)
                    if (isinstance(value, bool) or not isinstance(value, (int, float))
                            or not np.isfinite(value) or value < 0 or value > limit):
                        raise ValueError(f'Проверка {check["observation_id"]}: '
                                         f'{metric_names[key]} не проходит предел {limit}')
                corners = np.asarray(check['primary_corners'], dtype=np.float64)
                if corners.shape != (49, 1, 2) or not np.isfinite(corners).all():
                    raise ValueError('Неверные углы в отчёте проверки')
                if any(np.linalg.norm(corners - previous, axis=2).mean() < 12 for previous in positions):
                    raise ValueError('Проверки слишком похожи, нужны разные положения доски')
                positions.append(corners)

            metadata['status'] = 'validated'
            metadata['validation'] = dict(fingerprint=fingerprint, checks_count=len(checks),
                source_session_id=session_id, observation_ids=sorted(observations), limits=limits,
                validated_at=datetime.now(timezone.utc).isoformat())
            write_json(folder / 'metadata.json', metadata)
            self.result = metadata
            log_info(f'Калибровка {calibration_id}: подтверждена по {len(checks)} независимым парам')
            return self.status()

    def measure_quality(self, session_id, observation_id, calibration_id, confirmed, mounting_confirmed, stationary):
        with self.lock:
            if stationary is not True:
                raise ValueError('Подтвердите, что доска закреплена неподвижно')

            self.verify_observation(session_id, observation_id, calibration_id, confirmed, mounting_confirmed)
            reference = self.observation
            metadata, arrays = load_calibration(self._root() / calibration_id, self.signature,
                                                mounting_confirmed=True, allow_unvalidated=True)
            last_sequences = (reference['pair'].primary.sequence, reference['pair'].secondary.sequence)
            point_series = []
            frames = []
            started = time.perf_counter()
            report = dict(version=1, session_id=session_id, calibration_id=calibration_id,
                          created_at=datetime.now(timezone.utc).isoformat(), square_mm=self.square_mm,
                          calibration_created_at=metadata.get('created_at'), cameras=self.signature,
                          image_size=list(self.image_size),
                          requested_frames=10, interval_seconds=0.3, movement_limit_px=5,
                          status='not_measurable', frames=frames)

            try:
                for _ in range(10):
                    if time.perf_counter() - started > 25:
                        raise ValueError('Серия не завершилась за 25 секунд')

                    time.sleep(0.3)
                    self.observe(session_id, reference['rotation'], prepare_preview=False)
                    observation = self.observation
                    sequences = (observation['pair'].primary.sequence, observation['pair'].secondary.sequence)
                    if any(current <= previous for current, previous in zip(sequences, last_sequences)):
                        raise ValueError('Повторный или устаревший кадр в серии')
                    last_sequences = sequences

                    for role in ('primary', 'secondary'):
                        corners = observation['corners'][role]
                        if corners is None:
                            raise ValueError('Доска потеряна, повторите серию')
                        shift = np.linalg.norm(corners - reference['corners'][role], axis=2)
                        if shift.max() > 5:
                            raise ValueError('Доска сдвинулась или изменился порядок углов, повторите серию')

                    xyz, _ = triangulate_board(observation['corners']['primary'], observation['corners']['secondary'], arrays)
                    point_series.append(xyz)
                    frames.append(dict(primary_sequence=sequences[0], secondary_sequence=sequences[1],
                                       primary_timestamp_ns=observation['pair'].primary.timestamp_ns,
                                       secondary_timestamp_ns=observation['pair'].secondary.timestamp_ns,
                                       delta_ms=observation['pair'].delta_ms, **measure_planarity(xyz)))

                if time.perf_counter() - started > 25:
                    raise ValueError('Серия не завершилась за 25 секунд')
                quality = measure_depth_stability(point_series)
                quality.update(plane_mean_mm=float(np.mean([f['plane_mean_mm'] for f in frames])),
                               plane_rms_mm=float(np.sqrt(np.mean([f['plane_rms_mm'] ** 2 for f in frames]))),
                               plane_max_mm=max(f['plane_max_mm'] for f in frames),
                               elapsed_seconds=time.perf_counter() - started)
                report.update(status='measured', quality=quality)
                log_info(f'Качество стереопары: плоскость RMS={quality["plane_rms_mm"]:.3f} мм, '
                         f'максимум={quality["plane_max_mm"]:.3f} мм, '
                         f'среднее СКО глубины точек={quality["point_depth_std_mean_mm"]:.3f} мм')
            except (ValueError, RuntimeError, cv2.error) as error:
                report['reason'] = str(error)
                log_info(f'Качество стереопары: измерение не завершено, {error}')
                raise
            finally:
                self.observation = None
                report['elapsed_seconds'] = time.perf_counter() - started
                folder = self._session_folder() / 'quality_checks'
                folder.mkdir(parents=True, exist_ok=True)
                report_id = uuid.uuid4().hex
                write_json(folder / f'{report_id}.json', report)

            return dict(quality=quality, report_id=report_id, status='measured')

    def measure_timing(self, session_id, calibration_id, mounting_confirmed, motion_confirmed, rotation):
        from utils.stereo_timing import estimate_timing, rectified_points, exposure_settings

        with self.lock:
            self.require_session(session_id)
            if mounting_confirmed is not True or motion_confirmed is not True:
                raise ValueError('Подтвердите монтаж и движение доски для теста времени')
            if type(rotation) is not int or rotation not in range(4):
                raise ValueError('Недопустимый поворот сетки')
            if (not isinstance(calibration_id, str) or len(calibration_id) != 32
                    or any(char not in '0123456789abcdef' for char in calibration_id)):
                raise ValueError('Неверный номер калибровки')
            self.timing_result = None
            manager = get_camera_manager()
            manager.start(require_secondary=True)
            signature = self._camera_signature(manager)
            metadata, arrays = load_calibration(self._root() / calibration_id, signature, mounting_confirmed=True)
            if not np.allclose(arrays['P1'][1:], arrays['P2'][1:]):
                raise ValueError('Тест вертикального движения требует горизонтальной ректификации')
            samples = {'primary': [], 'secondary': []}
            started = time.monotonic()
            sequences = {'primary': -1, 'secondary': -1}
            report = dict(version=1, algorithm='moving_board_vertical_v1', calibration_id=calibration_id,
                          status='not_measurable', run_id=manager.get_status().get('run_id'),
                          fingerprint=metadata['validation']['fingerprint'], samples=samples,
                          timestamp_source='read_complete_monotonic', hardware_synchronized=False,
                          created_at=datetime.now(timezone.utc).isoformat())
            maintenance.timing_measuring.set()
            try:
                report['exposure_controls'] = exposure_settings(manager)
                while time.monotonic() - started < 20:
                    self.observe(session_id, rotation, prepare_preview=False)
                    observation = self.observation
                    for role, suffix in (('primary', '1'), ('secondary', '2')):
                        frame = getattr(observation['pair'], role)
                        if frame.sequence <= sequences[role]:
                            raise ValueError('Повторный кадр в тесте времени')
                        sequences[role] = frame.sequence
                        corners = observation['corners'][role]
                        if corners is not None:
                            rectified = rectified_points(corners, arrays, suffix)
                            samples[role].append([frame.timestamp_ns / 1e9, float(rectified[:, 1].mean())])
                if self._camera_signature(manager) != signature:
                    raise ValueError('Режим камер изменился во время теста')
                if exposure_settings(manager) != report['exposure_controls']:
                    raise ValueError('Выдержка изменилась во время теста')
                report.update(estimate=estimate_timing(samples), status='measured',
                              created_monotonic=time.monotonic(), recent_fps={
                                  role: manager.get_status()['cameras'][role].get('recent_fps', 0)
                                  for role in ('primary', 'secondary')})
                self.timing_result = report
            except (ValueError, RuntimeError, cv2.error) as error:
                report['reason'] = str(error)
            finally:
                maintenance.timing_measuring.clear()
                self.observation = None
            report['elapsed_seconds'] = time.monotonic() - started
            report['report_id'] = uuid.uuid4().hex
            folder = self._session_folder() / 'timing_checks'
            folder.mkdir(parents=True, exist_ok=True)
            write_json(folder / f'{report["report_id"]}.json', report)
            log_info(f'Тест времени: {report["status"]}, отчёт {report["report_id"]}')
            return report

    def _timing_context(self, manager, calibration_id, metadata, arrays, limits, confirmed):
        from utils.stereo_timing import check_timing_profile, exposure_settings
        from utils.two_view_pad import wait_for_measurement_pair, extract_face_points

        check_timing_profile(self.timing_result, calibration_id, metadata['validation']['fingerprint'],
                             manager.get_status(), time.monotonic(), confirmed)
        if exposure_settings(manager) != self.timing_result.get('exposure_controls'):
            raise ValueError('Выдержка камер изменилась после теста времени')
        if self.timing_result['estimate']['uncertainty_ms'] > limits['max_exposure_error_ms']:
            raise ValueError('Неопределённость теста времени превышает допустимый предел для лица')
        pair = wait_for_measurement_pair(manager, limits, {})
        previous = dict(points={}, timestamps={})
        for role in ('primary', 'secondary'):
            frame = getattr(pair, role)
            previous['points'][role] = extract_face_points(frame.image)
            previous['timestamps'][role] = frame.timestamp_ns
        return dict(previous=previous, profile=self.timing_result)

    def measure_face(self, session_id, calibration_id, mounting_confirmed, consent_confirmed,
                     sample_type, lighting, distance_cm, timing_confirmed=False):
        from utils.two_view_pad import inspect_pair, measurement_limits, wait_for_measurement_pair

        with self.lock:
            self.require_session(session_id)
            if consent_confirmed is not True or mounting_confirmed is not True:
                raise ValueError('Подтвердите согласие на опыт и неизменность камер')
            if (not isinstance(calibration_id, str) or len(calibration_id) != 32
                    or any(char not in '0123456789abcdef' for char in calibration_id)):
                raise ValueError('Неверный номер сохранённой калибровки')
            if sample_type not in ('live', 'print', 'phone_photo', 'phone_video'):
                raise ValueError('Выберите тип предъявления')
            if lighting not in ('daylight', 'artificial', 'mixed'):
                raise ValueError('Выберите освещение')
            if (isinstance(distance_cm, bool) or not isinstance(distance_cm, (int, float))
                    or not np.isfinite(distance_cm) or distance_cm <= 0):
                raise ValueError('Укажите приблизительное расстояние в сантиметрах')

            limits = measurement_limits(load_config().get('stereo_pad', {}))
            manager = get_camera_manager()
            manager.start(require_secondary=True)
            signature = self._camera_signature(manager)
            metadata, arrays = load_calibration(self._root() / calibration_id, signature,
                                                mounting_confirmed=True)
            if metadata.get('units') != 'mm':
                raise ValueError('Для измерения геометрии лица нужна калибровка в миллиметрах')

            self.observation = None
            report_id = uuid.uuid4().hex
            started = time.perf_counter()
            report = dict(version=1, algorithm='stereo_face_31_v1', report_id=report_id,
                          session_id=session_id, calibration_id=calibration_id,
                          calibration_created_at=metadata.get('created_at'), cameras=signature,
                          created_at=datetime.now(timezone.utc).isoformat(), limits=limits,
                          sample_type=sample_type, lighting=lighting, distance_cm=distance_cm,
                          status='not_measurable', decision='not_evaluated')
            report['timestamp_source'] = 'read_complete_monotonic'
            report['hardware_synchronized'] = False
            maintenance.stereo_measuring.set()
            report['pair_selection'] = dict(checked_pairs=0, skipped_pairs=0,
                                             minimum_delta_ms=None, wait_seconds=0.0)
            try:
                temporal = self._timing_context(manager, calibration_id, metadata, arrays, limits, timing_confirmed)
                if temporal is None:
                    raise ValueError('Не оценена временная точность камер')
                pair = wait_for_measurement_pair(manager, limits, report['pair_selection'])
                from utils.stereo_timing import check_timing_profile
                check_timing_profile(temporal['profile'], calibration_id, metadata['validation']['fingerprint'],
                                     manager.get_status(), time.monotonic(), timing_confirmed)
                if self._camera_signature(manager) != signature:
                    raise ValueError('Режим камер изменился во время опыта')
                report.update(pair_number=pair.number, delta_ms=pair.delta_ms,
                              primary_sequence=pair.primary.sequence,
                              secondary_sequence=pair.secondary.sequence,
                              primary_timestamp_ns=pair.primary.timestamp_ns,
                              secondary_timestamp_ns=pair.secondary.timestamp_ns)
                result = inspect_pair(pair, arrays, metadata['image_size'], limits, temporal_context=temporal)
                if temporal is not None:
                    report['timing_report_id'] = temporal['profile']['report_id']
                from utils.stereo_timing import exposure_settings
                if exposure_settings(manager) != temporal['profile'].get('exposure_controls'):
                    result.pop('metrics', None)
                    result.update(status='not_measurable', reason='Выдержка изменилась во время измерения лица')
                report.update({key: value for key, value in result.items() if key != 'previews'})
            except (ValueError, RuntimeError, cv2.error) as error:
                result = dict(status='not_measurable', reason=str(error))
                report.update(result)
            finally:
                maintenance.stereo_measuring.clear()

            # Это средняя частота с начала работы камер, а не мгновенный FPS
            camera_status = manager.get_status().get('cameras', {})
            report['actual_fps'] = {role: camera_status.get(role, {}).get('actual_fps')
                                    for role in ('primary', 'secondary')}

            report['elapsed_seconds'] = time.perf_counter() - started
            folder = self._session_folder() / 'stereo_pad_checks'
            folder.mkdir(parents=True, exist_ok=True)
            write_json(folder / f'{report_id}.json', report)
            log_info(f'P3: {report["status"]}, отчёт {report_id}, '
                     f'время {report["elapsed_seconds"]:.2f} с, решение о доступе не принималось')
            if report['status'] == 'measured':
                metrics = report['metrics']
                log_info(f'P3: RMS плоскости {metrics["plane_rms_mm"]:.3f} мм, '
                         f'глубина {metrics["mean_depth_mm"]:.1f} мм, рассинхрон {report["delta_ms"]:.1f} мс')
            else:
                log_info(f'P3: причина отказа измерения: {report["reason"]}')
            return dict(report, previews=result.get('previews', {}))

    def finish(self, session_id):
        with self.lock:
            self.require_session(session_id)
            self.active = False
            self.observation = None

            maintenance.end()
            log_info(f'Калибровка: завершена сессия {self.session_id}, распознавание возобновлено')
            return self.status()


calibration_session = CalibrationSession()
