import face_recognition
import math
import cv2
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.video_capture import capture_face_frames, detect_faces
from utils.db_connect import *
from utils.config_loader import load_config
from utils.evidence import PASS, IdentityEvidence
from utils.logger import log_debug, log_error, log_info, log_warning
from utils.timing import measure_time

config = load_config()

def get_embeddings_from_image(image_path: str):
    # Загружаем изображение
    with measure_time("JPEG: чтение и декодирование"):
        image = face_recognition.load_image_file(image_path)
    return _get_embeddings_from_rgb(image)


def get_embeddings_from_frame(frame, face_box=None):
    """Получает эмбеддинги из BGR-кадра камеры без сохранения на диск"""
    settings = config.get('recognition_optimization', {})
    if settings.get('roi_enabled', True):
        try:
            if face_box is None:
                faces = detect_faces(frame)
                if len(faces) != 1:
                    log_warning("Для ROI требуется ровно одно лицо")
                    return None
                face_box = faces[0]
            with measure_time("Подготовка ROI и преобразование BGR в RGB"):
                rgb_roi, location = prepare_face_roi(
                    frame, face_box, settings.get('roi_padding', 0.30),
                )
            with measure_time("Формирование эмбеддингов"):
                embeddings = face_recognition.face_encodings(
                    rgb_roi, known_face_locations=[location],
                    num_jitters=1, model='small',
                )
            return embeddings if len(embeddings) else None
        except (ValueError, TypeError, OverflowError, RuntimeError, cv2.error) as error:
            log_warning(f"Ошибка обработки ROI, кадр отклонён: {error}")
            return None

    with measure_time("Преобразование BGR в RGB"):
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return _get_embeddings_from_rgb(image)


def prepare_face_roi(frame, face_box, padding):
    """Вырезает лицо с отступами и возвращает RGB ROI и координаты внутри него"""
    padding = float(padding)
    if not math.isfinite(padding) or padding < 0:
        raise ValueError('Отступ ROI должен быть конечным неотрицательным числом')
    x, y, width, height = (int(value) for value in face_box)
    image_height, image_width = frame.shape[:2]
    if (width <= 0 or height <= 0 or x < 0 or y < 0
            or x + width > image_width or y + height > image_height):
        raise ValueError('Некорректные координаты лица')

    left = max(0, math.floor(x - width * padding))
    top = max(0, math.floor(y - height * padding))
    right = min(image_width, math.ceil(x + width + width * padding))
    bottom = min(image_height, math.ceil(y + height + height * padding))
    roi = frame[top:bottom, left:right]
    if roi.size == 0:
        raise ValueError('Пустая область ROI')
    location = (y - top, x + width - left, y + height - top, x - left)
    return cv2.cvtColor(roi, cv2.COLOR_BGR2RGB), location


def _get_embeddings_from_rgb(image):
    # Получаем эмбэддинги лиц на изображении
    with measure_time("Детекция лица: dlib"):
        locations = face_recognition.face_locations(image)
    with measure_time("Формирование эмбеддингов"):
        embeddings = face_recognition.face_encodings(
            image, known_face_locations=locations,
        )
    
    if len(embeddings) == 0:
        log_warning("На изображении с камеры не найдено лиц")
        return None
    
    return embeddings

def create_embeddings_from_camera():
    frames = capture_face_frames(1, frame_delay=0)
    if not frames:
        log_error("Не удалось получить изображение с камеры для создания эмбэддингов")
        return None

    image, face_box = frames[0]
    return get_embeddings_from_frame(image, face_box)

def save_embedding(embedding):
    return add_user_embedding(embedding)

def add_new_user_with_embedding(username, embedding_id):
    return save_user_with_embedding(username, embedding_id)

def get_users():
    return get_all_users()

def check_for_similar_embeddings_in_db(embedding):
    user_id, distance = find_nearest_user(embedding)
    similarity = config.get('similarity', 0.15)

    if user_id is None:
        return False, None, None
    
    if distance < similarity:
        return True, user_id, distance
    return False, None, None

def get_multi_frame_recognition_config():
    recognition_config = config.get('multi_frame_recognition', {})
    frames_count = recognition_config.get('frames_count', 5)
    min_successful_frames = recognition_config.get('min_successful_frames', 3)
    frame_delay = recognition_config.get('frame_delay', 0.15)
    max_distance_std = recognition_config.get('max_distance_std', 0.05)
    
    frames_count = max(1, int(frames_count))
    min_successful_frames = max(1, min(int(min_successful_frames), frames_count))
    frame_delay = max(0, float(frame_delay))
    max_distance_std = max(0, float(max_distance_std))
    
    return frames_count, min_successful_frames, frame_delay, max_distance_std

def get_recognition_mode():
    """Режим решения: адаптивное накопление свидетельств или фиксированная серия"""
    mode = str(
        config.get('multi_frame_recognition', {}).get('mode', 'fixed')
    ).strip().lower()
    if mode not in ('fixed', 'adaptive'):
        raise ValueError(f'Неизвестный режим распознавания: {mode}')
    return mode

def get_adaptive_recognition_config():
    """Параметры адаптивного накопления свидетельств"""
    settings = config.get('adaptive_recognition', {})
    min_frames = max(1, int(settings.get('min_frames', 3)))
    max_frames = max(1, int(settings.get('max_frames', 7)))
    min_successful_frames = max(1, int(settings.get('min_successful_frames', 3)))
    frame_interval = max(0, float(settings.get('frame_interval_ms', 200)) / 1000)
    early_stop_threshold = min(
        max(float(settings.get('early_stop_threshold', 0.98)), 0.001), 1.0
    )
    max_attempt_duration = max(
        0.001, float(settings.get('max_attempt_duration_s', 2.5))
    )
    max_distance_std = max(0, float(settings.get('max_distance_std', 0.05)))

    if max_frames < min_frames:
        raise ValueError('max_frames не может быть меньше min_frames')
    if min_successful_frames > max_frames:
        raise ValueError('min_successful_frames не может превышать max_frames')

    return {
        'min_frames': min_frames,
        'max_frames': max_frames,
        'min_successful_frames': min_successful_frames,
        'frame_interval': frame_interval,
        'early_stop_threshold': early_stop_threshold,
        'max_attempt_duration': max_attempt_duration,
        'max_distance_std': max_distance_std,
    }

def get_bayesian_scoring_config():
    bayesian_config = config.get('bayesian_scoring', {})
    enabled = bool(bayesian_config.get('enabled', True))
    prior_probability = float(bayesian_config.get('prior_probability', 0.2))
    decision_threshold = float(bayesian_config.get('decision_threshold', 0.98))
    distance_sigma = float(bayesian_config.get('distance_sigma', 0.08))
    unknown_likelihood = float(bayesian_config.get('unknown_likelihood', 0.05))
    miss_likelihood_ratio = float(bayesian_config.get('miss_likelihood_ratio', 0.4))
    minimum_likelihood = float(bayesian_config.get('minimum_likelihood', 0.000001))
    correlation_discount = float(bayesian_config.get('correlation_discount', 0.4))
    
    prior_probability = min(max(prior_probability, 0.001), 0.999)
    decision_threshold = min(max(decision_threshold, 0.001), 0.999)
    distance_sigma = max(distance_sigma, 0.000001)
    unknown_likelihood = max(unknown_likelihood, minimum_likelihood)
    miss_likelihood_ratio = max(miss_likelihood_ratio, minimum_likelihood)
    minimum_likelihood = max(minimum_likelihood, 0.000000001)
    correlation_discount = min(max(correlation_discount, 0.001), 1.0)
    
    return {
        'enabled': enabled,
        'prior_probability': prior_probability,
        'decision_threshold': decision_threshold,
        'distance_sigma': distance_sigma,
        'unknown_likelihood': unknown_likelihood,
        'miss_likelihood_ratio': miss_likelihood_ratio,
        'minimum_likelihood': minimum_likelihood,
        'correlation_discount': correlation_discount,
    }

def create_embeddings_series_from_camera(frames_count, frame_delay):
    """Собирает эмбэддинги с нескольких кадров камеры."""
    
    embeddings_series = []
    frames = capture_face_frames(frames_count, frame_delay=frame_delay)
    
    for frame_index, (frame, face_box) in enumerate(frames):
        embeddings = get_embeddings_from_frame(frame, face_box)
        
        if embeddings is None or len(embeddings) == 0:
            log_debug(f"Кадр {frame_index + 1}/{frames_count}: эмбэддинг не получен")
        else:
            embeddings_series.append(embeddings[0])
            log_debug(f"Кадр {frame_index + 1}/{frames_count}: эмбэддинг получен")
    
    return embeddings_series

def match_embedding(embedding):
    """Ищет ближайшего пользователя и применяет порог similarity

    Возвращает пару (user_id, distance). Если ближайший шаблон дальше порога,
    кадр не подтверждает ни одного пользователя, но дистанция сохраняется
    для диагностики
    """
    user_id, distance = find_nearest_user(embedding)
    if user_id is None or distance is None:
        return None, None

    try:
        distance = float(distance)
    except (TypeError, ValueError):
        log_warning("Поиск в базе вернул некорректную дистанцию")
        return None, None
    if not math.isfinite(distance) or distance < 0:
        log_warning("Поиск в базе вернул некорректную дистанцию")
        return None, None

    if distance >= config.get('similarity', 0.15):
        return None, distance
    return user_id, distance

def _create_evidence(*, min_frames, max_frames, min_successful_frames,
                     max_distance_std, early_stop_threshold):
    """Создаёт оценщик с общими параметрами скоринга и границами режима"""
    bayesian = get_bayesian_scoring_config()
    # Отключённый скоринг оставляет сравнение по числу кадров без порога score
    decision_threshold = bayesian['decision_threshold'] if bayesian['enabled'] else None
    return IdentityEvidence(
        prior_probability=bayesian['prior_probability'],
        distance_sigma=bayesian['distance_sigma'],
        unknown_likelihood=bayesian['unknown_likelihood'],
        miss_likelihood_ratio=bayesian['miss_likelihood_ratio'],
        minimum_likelihood=bayesian['minimum_likelihood'],
        correlation_discount=bayesian['correlation_discount'],
        min_frames=min_frames,
        max_frames=max_frames,
        min_successful_frames=min_successful_frames,
        max_distance_std=max_distance_std,
        decision_threshold=decision_threshold,
        early_stop_threshold=early_stop_threshold if bayesian['enabled'] else None,
    )

def _decision_result(decision):
    """Переводит решение оценщика в контракт (успех, user_id, distance)"""
    score_text = f"{decision.score:.4f}" if decision.score is not None else '-'
    log_info(
        f"Свидетельства идентичности: кадров={decision.frames}, score={score_text}, "
        f"решение={decision.status}, причина={decision.reason or '-'}"
    )
    if decision.status == PASS:
        return True, decision.user_id, decision.distance
    return False, None, None

def _confirm_fresh_after_database(observation_source, deadline, result):
    """Перед допуском проверяет новый кадр: поиск в БД мог занять время"""
    observation_source.check_cancelled(deadline)
    if result[0]:
        observation_source.next(deadline)
    return result

@recognition_db_session()
def recognize_face_from_embeddings_series(embeddings_series):
    """Фиксированный режим: решение по заранее собранной серии кадров

    Использует ту же математику, что и адаптивный режим, но без ранней
    остановки: все кадры серии обрабатываются всегда
    """
    if not embeddings_series:
        log_warning("Не удалось получить эмбэддинги с серии кадров")
        return False, None, None

    frames_count, min_successful_frames, _, max_distance_std = \
        get_multi_frame_recognition_config()
    evidence = _create_evidence(
        min_frames=frames_count,
        max_frames=frames_count,
        min_successful_frames=min_successful_frames,
        max_distance_std=max_distance_std,
        early_stop_threshold=1.0,
    )
    for embedding in embeddings_series:
        evidence.add(*match_embedding(embedding))
    return _decision_result(evidence.result())

def _recognize_fixed(observation_source, deadline):
    """Фиксированная серия кадров из наблюдений текущего трека"""
    frames_count, _, frame_delay, _ = get_multi_frame_recognition_config()
    embeddings_series = []
    for observation in observation_source.observations(
            frames_count, frame_delay, deadline):
        embeddings = get_embeddings_from_frame(
            observation.primary.image, observation.face_box,
        )
        observation_source.check_cancelled(deadline)
        if embeddings is not None and len(embeddings):
            embeddings_series.append(embeddings[0])
    result = recognize_face_from_embeddings_series(embeddings_series)
    return _confirm_fresh_after_database(observation_source, deadline, result)

def _recognize_adaptive(observation_source, deadline):
    """Накопление свидетельств по одному кадру до решения или лимита попытки"""
    settings = get_adaptive_recognition_config()
    evidence = _create_evidence(
        min_frames=settings['min_frames'],
        max_frames=settings['max_frames'],
        min_successful_frames=settings['min_successful_frames'],
        max_distance_std=settings['max_distance_std'],
        early_stop_threshold=settings['early_stop_threshold'],
    )
    clock = getattr(observation_source, 'clock', time.monotonic)
    attempt_started = clock()
    decision = None

    # Одно соединение на попытку: поиск по базе выполняется для каждого кадра
    with recognition_db_session():
        for observation in observation_source.observations(
                settings['max_frames'], settings['frame_interval'], deadline):
            embeddings = get_embeddings_from_frame(
                observation.primary.image, observation.face_box,
            )
            observation_source.check_cancelled(deadline)
            if embeddings is not None and len(embeddings):
                evidence.add(*match_embedding(embeddings[0]))
                decision = evidence.early_decision()
                if decision is not None:
                    break
            if clock() - attempt_started >= settings['max_attempt_duration']:
                break

    if decision is None:
        decision = evidence.result()
    result = _decision_result(decision)
    return _confirm_fresh_after_database(observation_source, deadline, result)

@measure_time("Полное распознавание с камеры", summary=True)
def recognize_face_from_camera(observation_source=None, deadline=None):
    """Распознаёт лицо с камеры и проверяет его наличие в базе данных

    Без источника наблюдений используется прежний захват одиночной камеры:
    адаптивный режим требует потока наблюдений от CameraManager
    """
    if observation_source is None:
        frames_count, _, frame_delay, _ = get_multi_frame_recognition_config()
        embeddings_series = create_embeddings_series_from_camera(
            frames_count, frame_delay,
        )
        return recognize_face_from_embeddings_series(embeddings_series)

    if get_recognition_mode() == 'fixed':
        return _recognize_fixed(observation_source, deadline)
    return _recognize_adaptive(observation_source, deadline)
