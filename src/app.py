# app.py - Основное приложение
from flask import Flask, Response, jsonify, request, session, send_from_directory
from datetime import timedelta
import os
import sys
from functools import wraps
from pathlib import Path

import cv2

sys.path.append(str(Path(__file__).parent.parent))

from utils.face.recognition import create_embeddings_from_camera, save_embedding, add_new_user_with_embedding
from utils.storage.db_connect import get_all_users, delete_user_by_id
from utils.capture.camera_manager import CameraError, get_camera_manager, get_public_camera_status
from utils.common.maintenance import maintenance
from utils.stereo.stereo_calibration import calibration_session
from utils.capture.face_detection_preview import face_detection_preview
from utils.challenge.challenge_session import challenge_session
from utils.access.api_security import authorize_admin, login_admin, FramePreviewLimiter
from utils.access.policy_store import (
    apply_override, load_override, policy_path, policy_values,
    save_override, validate_values,
)
from utils.access.status import authentication_service
from utils.common.config_loader import load_config
from utils.common.logger import log_error

app = Flask(__name__)
app.secret_key = os.urandom(24)
frame_preview_limit = FramePreviewLimiter()
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Strict', PERMANENT_SESSION_LIFETIME=timedelta(minutes=15),
                  SESSION_REFRESH_EACH_REQUEST=False, PREFERRED_URL_SCHEME='https', MAX_CONTENT_LENGTH=65536)


@app.before_request
def protect_api():
    if not request.path.startswith('/api/'):
        return None
    if not request.is_secure:
        return jsonify(message='Для API требуется HTTPS'), 403
    public = ('/api/admin/login', '/api/authentication/state')
    if request.path not in public:
        return authorize_admin()


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=86400'
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/api/admin/login')
def admin_login():
    return login_admin()


@app.get('/api/admin/session')
def admin_session():
    return jsonify(status='success')


@app.post('/api/admin/logout')
def admin_logout():
    session.clear()
    return jsonify(status='success')


@app.get('/')
@app.get('/<path:filename>')
def frontend(filename='index.html'):
    if filename.startswith('api/'):
        return jsonify(message='Маршрут API не найден'), 404
    folder = Path(__file__).resolve().parent.parent / 'Face-Recognition-Vue' / 'dist'
    if filename in ('index.html', 'face-auth'):
        filename = 'index.html'
    return send_from_directory(folder, filename)


def calibration_admin(view):
    @wraps(view)
    def protected(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except CameraError:
            return jsonify(message='Камеры недоступны'), 503
        except (ValueError, RuntimeError) as error:
            return jsonify(message=str(error)), 409
        except (cv2.error, OSError):
            return jsonify(message='Ошибка расчёта или сохранения калибровки'), 500
    return protected


@app.get('/api/calibration/status')
@calibration_admin
def calibration_status():
    return jsonify(calibration_session.status())


@app.get('/api/challenge/status')
def challenge_status():
    return jsonify(challenge_session.status())


@app.post('/api/challenge/<action>')
@calibration_admin
def challenge_action(action):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message='Неверный формат запроса'), 400
    if action == 'start':
        return jsonify(challenge_session.start(data.get('consent_confirmed'), data.get('preparation_mode', False)))
    if action == 'cancel':
        return jsonify(challenge_session.cancel(data.get('session_id')))
    return jsonify(message='Неизвестная команда'), 404


@app.post('/api/calibration/frame/<role>')
@calibration_admin
def calibration_frame(role):
    data = request.get_json(silent=True) or {}
    image = calibration_session.download_frame(data.get('session_id'), data.get('observation_id'), role)
    response = Response(image, mimetype='image/png')
    response.headers['Content-Disposition'] = f'attachment; filename="calibration_{role}.png"'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/api/calibration/<action>')
@calibration_admin
def calibration_action(action):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(message='Неверный формат запроса'), 400
    if action == 'start':
        if data.get('mounting_confirmed') is not True:
            return jsonify(message='Подтвердите крепление камер и размеры доски'), 400
        return jsonify(calibration_session.start(data.get('square_mm', 45.0)))
    if action == 'observe':
        rotation = data.get('rotation', 0)
        if type(rotation) is not int or rotation not in range(4):
            return jsonify(message='Недопустимый поворот сетки'), 400
        return jsonify(calibration_session.observe(data.get('session_id'), rotation))
    if action == 'capture':
        return jsonify(calibration_session.save_pair(
            data.get('session_id'), data.get('observation_id'),
            data.get('validation') is True, data.get('orientation_confirmed'),
        ))
    if action == 'calculate':
        return jsonify(calibration_session.calculate(data.get('session_id')))
    if action == 'review':
        return jsonify(calibration_session.review(data.get('session_id'), data.get('pair_index')))
    if action == 'verify':
        return jsonify(calibration_session.verify_observation(
            data.get('session_id'), data.get('observation_id'), data.get('calibration_id'),
            data.get('orientation_confirmed'), data.get('mounting_confirmed')))
    if action == 'validate':
        return jsonify(calibration_session.validate(data.get('session_id'), data.get('calibration_id'),
            data.get('mounting_confirmed'), data.get('review_confirmed')))
    if action == 'quality':
        return jsonify(calibration_session.measure_quality(
            data.get('session_id'), data.get('observation_id'), data.get('calibration_id'),
            data.get('orientation_confirmed'), data.get('mounting_confirmed'), data.get('stationary')))
    if action == 'face':
        response = jsonify(calibration_session.measure_face(
            data.get('session_id'), data.get('calibration_id'), data.get('mounting_confirmed'),
            data.get('consent_confirmed'), data.get('sample_type'), data.get('lighting'), data.get('distance_cm'),
            data.get('timing_confirmed'), data.get('check_timing', False),
            data.get('dense_depth', False), data.get('stationary_confirmed', False), data.get('series_id')))
        response.headers['Cache-Control'] = 'no-store'
        return response
    if action == 'timing':
        return jsonify(calibration_session.measure_timing(data.get('session_id'), data.get('calibration_id'),
            data.get('mounting_confirmed'), data.get('motion_confirmed'), data.get('rotation', 0)))
    if action == 'finish':
        return jsonify(calibration_session.finish(data.get('session_id')))
    return jsonify(message='Неизвестная команда'), 404


@app.route('/api/cameras/status', methods=['GET'])
def camera_status():
    """Возвращает безопасную телеметрию камер без кадров и device paths"""
    status = get_public_camera_status()
    status['preview_available'] = calibration_session.active and maintenance.requested.is_set()
    return jsonify(status)


def maintenance_preview(view):
    @wraps(view)
    def protected(*args, **kwargs):
        # HTTPS и права администратора уже проверены в protect_api
        # Не ставим JPEG в очередь за долгим расчётом калибровки
        if not calibration_session.lock.acquire(blocking=False):
            return jsonify(message='Обслуживание занято, повторите запрос позже'), 409
        try:
            if not calibration_session.active or not maintenance.requested.is_set():
                return jsonify(message='Кадры доступны только в режиме обслуживания камер'), 403
            if frame_preview_limit.retry_after() > 0:
                response = jsonify(message='Превышена частота получения кадров')
                response.status_code = 429
                response.headers['Retry-After'] = '1'
                return response
            # finish использует тот же lock: режим не завершится посреди подготовки кадра
            return view(*args, **kwargs)
        finally:
            calibration_session.lock.release()
    return protected


@app.route('/api/cameras/<role>/frame', methods=['GET'])
@maintenance_preview
def camera_frame(role):
    """Возвращает свежий уменьшенный кадр камеры"""
    if role not in ('primary', 'secondary'):
        return jsonify({'status': 'error', 'message': 'Неизвестная камера'}), 404

    try:
        frame = get_camera_manager().get_latest_frame(role, timeout=1.0)
    except CameraError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 503

    if frame is None:
        return jsonify({'status': 'error', 'message': 'Кадр не получен'}), 503

    image = frame.image
    if role == 'primary' and request.args.get('haar') == '1':
        face_detection_preview.enable()
        image = face_detection_preview.render(frame)
    max_width = 640
    if image.shape[1] > max_width:
        scale = max_width / image.shape[1]
        size = (max_width, round(image.shape[0] * scale))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)

    encoded, jpeg = cv2.imencode(
        '.jpg',
        image,
        [cv2.IMWRITE_JPEG_QUALITY, 70],
    )
    if not encoded:
        return jsonify({'status': 'error', 'message': 'Не удалось подготовить кадр'}), 500

    response = Response(jpeg.tobytes(), mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.get('/api/authentication/state')
def authentication_state():
    """Текущее состояние конвейера без идентификаторов пользователя"""
    return jsonify(authentication_service.public_snapshot())


@app.get('/api/authentication/history')
def authentication_history():
    """Обезличенный журнал решений только для администратора"""
    decision = request.args.get('decision')
    if decision not in (None, 'GRANTED', 'DENIED', 'ERROR'):
        return jsonify(message='Неизвестный тип решения'), 400
    try:
        limit = int(request.args.get('limit', 50))
    except (TypeError, ValueError):
        return jsonify(message='Некорректный лимит'), 400
    try:
        items = authentication_service.history(
            limit=limit, decision=decision, kind='session',
        )
    except Exception as error:
        log_error(f'Журнал аудита недоступен: {error}')
        return jsonify(message='Журнал недоступен'), 503
    return jsonify(items=items)


@app.get('/api/authentication/policy')
def authentication_policy():
    config = load_config()
    effective = policy_values(apply_override(
        config, load_override(policy_path(config)),
    ))
    running = authentication_service.running_policy()
    running_values = None
    if running is not None:
        running_values = {
            'stereo_mode': running.stereo_mode,
            'challenge_mode': running.challenge_mode,
            'challenge_count': running.challenge_count,
        }
    return jsonify(
        policy=effective,
        running=running_values,
        restart_required=running_values != effective,
    )


@app.put('/api/authentication/policy')
def update_authentication_policy():
    try:
        values = validate_values(request.get_json(silent=True))
    except ValueError as error:
        return jsonify(message=str(error)), 400
    config = load_config()
    try:
        save_override(policy_path(config), values)
    except OSError:
        return jsonify(message='Не удалось сохранить политику'), 500
    authentication_service.record_policy_change(values, request.remote_addr)
    return jsonify(status='success', policy=values, restart_required=True)

@app.route('/api/add_user', methods=['POST'])
def add_user():
    name = request.args.get('name')
    try:
        with maintenance.recognition():
            embeddings = create_embeddings_from_camera()
    except RuntimeError as error:
        return jsonify(status='error', message=str(error)), 409
        
    if embeddings:
        if len(embeddings) > 0:
            embeddings_id = save_embedding(embeddings[0])
            add_new_user_with_embedding(name, embeddings_id)
        else:
            return jsonify({'status': 'not success', 'message': 'error'})
    else:
        return jsonify({'status': 'not success', 'message': 'error'})
    
    return jsonify({'status': 'success', 'message': 'User added'})

@app.route('/api/get_users', methods=['GET'])
def get_users():
    try:
        users = get_all_users()
        return jsonify(users)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/delete_user/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    try:
        success = delete_user_by_id(user_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Пользователь удален'})
        else:
            return jsonify({'status': 'error', 'message': 'Пользователь не найден'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
