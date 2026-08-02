import face_recognition
import math
import os
import shutil
import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.append(str(Path(__file__).parent.parent))

from utils.video_capture import capture_image, capture_images
from utils.db_connect import *
from utils.config_loader import load_config
from utils.logger import log_debug, log_error, log_info, log_warning

config = load_config()

def get_embeddings_from_image(image_path: str):
    # Загружаем изображение
    image = face_recognition.load_image_file(image_path)
    
    # Получаем эмбэддинги лиц на изображении
    embeddings = face_recognition.face_encodings(image)
    
    if len(embeddings) == 0:
        log_warning("На изображении с камеры не найдено лиц")
        return None
    
    return embeddings

def create_embeddings_from_camera():
    # Захватываем изображение с камеры
    camera_image_path = os.path.join('data', 'tmp_image.jpg')
    success = capture_image(camera_image_path)

    destination_path = os.path.join('Face-Recognition-Vue', 'public', 'tmp_image.jpg')
    shutil.copy(camera_image_path, destination_path)

    if not success:
        log_error("Не удалось получить изображение с камеры для создания эмбэддингов")
        return None
    
    return get_embeddings_from_image(camera_image_path)

def save_embedding(embedding):
    return add_user_embedding(embedding)

def add_new_user_with_embedding(username, embedding_id):
    return save_user_with_embedding(username, embedding_id)

def get_users():
    return get_all_users()

def check_for_similar_embeddings_in_db(embedding):
    user_id, distance = find_nearest_user_for_embedding(embedding)
    similarity = config.get('similarity', 0.15)

    if user_id is None:
        return False, None, None
    
    if distance < similarity:
        return True, user_id, distance
    return False, None, None

def find_nearest_user_for_embedding(embedding):
    results = find_similar_embeddings(embedding)
    if not results:
        return None, None
    
    embedding_id, distance = results[0]
    user = get_user_by_embedding_id(embedding_id)
    
    if user is None:
        log_warning(f"Для embedding_id={embedding_id} не найден пользователь")
        return None, None
    
    return user.get('id'), distance

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

def get_bayesian_scoring_config():
    bayesian_config = config.get('bayesian_scoring', {})
    enabled = bool(bayesian_config.get('enabled', True))
    prior_probability = float(bayesian_config.get('prior_probability', 0.2))
    decision_threshold = float(bayesian_config.get('decision_threshold', 0.95))
    distance_sigma = float(bayesian_config.get('distance_sigma', 0.08))
    unknown_likelihood = float(bayesian_config.get('unknown_likelihood', 0.05))
    miss_likelihood_ratio = float(bayesian_config.get('miss_likelihood_ratio', 0.4))
    minimum_likelihood = float(bayesian_config.get('minimum_likelihood', 0.000001))
    
    prior_probability = min(max(prior_probability, 0.001), 0.999)
    decision_threshold = min(max(decision_threshold, 0.001), 0.999)
    distance_sigma = max(distance_sigma, 0.000001)
    unknown_likelihood = max(unknown_likelihood, minimum_likelihood)
    miss_likelihood_ratio = max(miss_likelihood_ratio, minimum_likelihood)
    minimum_likelihood = max(minimum_likelihood, 0.000000001)
    
    return {
        'enabled': enabled,
        'prior_probability': prior_probability,
        'decision_threshold': decision_threshold,
        'distance_sigma': distance_sigma,
        'unknown_likelihood': unknown_likelihood,
        'miss_likelihood_ratio': miss_likelihood_ratio,
        'minimum_likelihood': minimum_likelihood,
    }

def create_embeddings_series_from_camera(frames_count=None, frame_delay=None):
    """Собирает эмбэддинги с нескольких кадров камеры."""
    configured_frames_count, _, configured_frame_delay, _ = get_multi_frame_recognition_config()
    frames_count = configured_frames_count if frames_count is None else max(1, int(frames_count))
    frame_delay = configured_frame_delay if frame_delay is None else max(0, float(frame_delay))
    
    embeddings_series = []
    image_paths = [
        os.path.join('data', f'tmp_image_{frame_index + 1}.jpg')
        for frame_index in range(frames_count)
    ]
    captured_paths = capture_images(image_paths, frame_delay=frame_delay)
    
    if captured_paths:
        destination_path = os.path.join('Face-Recognition-Vue', 'public', 'tmp_image.jpg')
        shutil.copy(captured_paths[-1], destination_path)
    
    for frame_index, image_path in enumerate(captured_paths):
        embeddings = get_embeddings_from_image(image_path)
        
        if embeddings is None or len(embeddings) == 0:
            log_debug(f"Кадр {frame_index + 1}/{frames_count}: эмбэддинг не получен")
        else:
            embeddings_series.append(embeddings[0])
            log_debug(f"Кадр {frame_index + 1}/{frames_count}: эмбэддинг получен")
    
    return embeddings_series

def calculate_distance_std(distances):
    if len(distances) < 2:
        return 0
    
    mean_distance = sum(distances) / len(distances)
    variance = sum((distance - mean_distance) ** 2 for distance in distances) / len(distances)
    return variance ** 0.5

def calculate_match_likelihood(distance, distance_sigma, minimum_likelihood):
    likelihood = math.exp(-((distance ** 2) / (2 * (distance_sigma ** 2))))
    return max(likelihood, minimum_likelihood)

def calculate_bayesian_user_scores(frame_matches, candidate_ids=None):
    bayesian_config = get_bayesian_scoring_config()
    if candidate_ids is None:
        candidates = {
            user_id
            for user_id, distance in frame_matches
            if user_id is not None and distance is not None
        }
    else:
        candidates = set(candidate_ids)
    
    if not candidates:
        return None, 0, {}
    
    prior_probability = bayesian_config['prior_probability']
    prior_odds = prior_probability / (1 - prior_probability)
    scores = {}
    
    for candidate_id in candidates:
        log_odds = math.log(prior_odds)
        
        for user_id, distance in frame_matches:
            if user_id == candidate_id and distance is not None:
                likelihood = calculate_match_likelihood(
                    distance,
                    bayesian_config['distance_sigma'],
                    bayesian_config['minimum_likelihood']
                )
                likelihood_ratio = likelihood / bayesian_config['unknown_likelihood']
            else:
                likelihood_ratio = bayesian_config['miss_likelihood_ratio']
            
            log_odds += math.log(max(likelihood_ratio, bayesian_config['minimum_likelihood']))
        
        posterior = 1 / (1 + math.exp(-log_odds))
        scores[candidate_id] = posterior
    
    best_user_id = max(scores, key=scores.get)
    return best_user_id, scores[best_user_id], scores

def recognize_face_from_embeddings_series(embeddings_series):
    """Принимает решение по нескольким кадрам вместо одного."""
    if not embeddings_series:
        log_warning("Не удалось получить эмбэддинги с серии кадров")
        return False, None, None
    
    _, min_successful_frames, _, max_distance_std = get_multi_frame_recognition_config()
    bayesian_config = get_bayesian_scoring_config()
    successful_matches = []
    distances_by_user = defaultdict(list)
    frame_matches = []
    
    for embedding in embeddings_series:
        nearest_user_id, nearest_distance = find_nearest_user_for_embedding(embedding)
        frame_matches.append((nearest_user_id, nearest_distance))
        
        is_known = (
            nearest_user_id is not None
            and nearest_distance is not None
            and nearest_distance < config.get('similarity', 0.15)
        )
        
        if is_known:
            successful_matches.append(nearest_user_id)
            distances_by_user[nearest_user_id].append(nearest_distance)
    
    if not successful_matches:
        log_info("Серия кадров не дала ни одного успешного совпадения")
        return False, None, None
    
    if bayesian_config['enabled']:
        user_id, posterior_probability, bayesian_scores = calculate_bayesian_user_scores(
            frame_matches,
            set(successful_matches)
        )
    else:
        user_id, posterior_probability, bayesian_scores = None, None, {}
    
    if user_id is None:
        user_id, successful_frames = Counter(successful_matches).most_common(1)[0]
    else:
        successful_frames = successful_matches.count(user_id)
    
    user_distances = distances_by_user[user_id]
    average_distance = sum(user_distances) / len(user_distances)
    distance_std = calculate_distance_std(user_distances)
    
    posterior_text = (
        f", bayesian_posterior={posterior_probability:.4f}"
        if posterior_probability is not None
        else ""
    )
    log_info(
        "Распознавание по серии кадров: "
        f"user_id={user_id}, успешных кадров={successful_frames}/{len(embeddings_series)}, "
        f"средняя дистанция={average_distance:.4f}, std={distance_std:.4f}"
        f"{posterior_text}"
    )
    if bayesian_scores:
        log_debug(f"Байесовские оценки пользователей: {bayesian_scores}")
    
    if successful_frames < min_successful_frames:
        log_warning(
            f"Недостаточно стабильное распознавание: {successful_frames} успешных кадров "
            f"из требуемых {min_successful_frames}"
        )
        return False, None, None
    
    if distance_std > max_distance_std:
        log_warning(
            f"Нестабильная дистанция распознавания: std={distance_std:.4f}, "
            f"порог={max_distance_std:.4f}"
        )
        return False, None, None
    
    if bayesian_config['enabled'] and posterior_probability < bayesian_config['decision_threshold']:
        log_warning(
            f"Недостаточная байесовская уверенность: posterior={posterior_probability:.4f}, "
            f"порог={bayesian_config['decision_threshold']:.4f}"
        )
        return False, None, None
    
    return True, user_id, average_distance

def recognize_face_from_camera():
    """Распознает лицо с камеры и проверяет его наличие в базе данных"""
    frames_count, _, frame_delay, _ = get_multi_frame_recognition_config()
    embeddings_series = create_embeddings_series_from_camera(frames_count, frame_delay)
    return recognize_face_from_embeddings_series(embeddings_series)
