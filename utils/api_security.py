"""Доступ к административной панели без доверия к заголовкам прокси"""

import hashlib
import hmac
import ipaddress
import os
import time
import threading
from pathlib import Path

from flask import jsonify, request, session

from utils.config_loader import load_config

PROJECT_DIR = Path(__file__).resolve().parent.parent
_failures = {}
_failure_lock = threading.Lock()


class FramePreviewLimiter:
    """Общий бюджет JPEG для устройства: две выдачи в секунду, всплеск до двух"""

    def __init__(self, rate=2.0, burst=2.0):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def retry_after(self):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + max(0, now - self.updated) * self.rate)
            self.updated = now
            if self.tokens < 1:
                return (1 - self.tokens) / self.rate
            self.tokens -= 1
            return 0


def admin_token():
    config = load_config()
    token = os.environ.get('CALIBRATION_ADMIN_TOKEN') or config.get('stereo_calibration', {}).get('admin_token')
    if token:
        return token if isinstance(token, str) else ''
    path = PROJECT_DIR / config.get('security', {}).get('admin_token_file', 'data/security/admin-token')
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def check_transport_and_network():
    if not request.is_secure:
        return jsonify(message='Для API требуется HTTPS'), 403
    networks = load_config().get('security', {}).get('admin_networks', ['127.0.0.1/32', '::1/128'])
    try:
        address = ipaddress.ip_address(request.remote_addr)
        allowed = isinstance(networks, list) and any(address in ipaddress.ip_network(net) for net in networks)
    except (ValueError, TypeError):
        allowed = False
    if not allowed:
        return jsonify(message='Административный доступ с этого адреса запрещён'), 403
    # Не принимаем чужой Origin даже с действующей сессией
    origin = request.headers.get('Origin')
    if origin and origin != request.host_url.rstrip('/'):
        return jsonify(message='Источник запроса не разрешён'), 403
    return None


def authorize_admin():
    denied = check_transport_and_network()
    if denied is not None:
        return denied
    token = admin_token()
    if not token:
        return jsonify(message='Административный доступ отключён: не задан токен'), 503
    supplied = request.headers.get('X-Admin-Token', request.headers.get('X-Calibration-Token'))
    if supplied:
        valid = hmac.compare_digest(supplied.encode(), token.encode())
    else:
        expected = hashlib.sha256(token.encode()).hexdigest()
        valid = hmac.compare_digest(session.get('admin_digest', ''), expected)
    if not valid:
        return jsonify(message='Требуется вход администратора'), 401
    return None


def login_admin():
    denied = check_transport_and_network()
    if denied is not None:
        return denied
    address = request.remote_addr
    now = time.monotonic()
    with _failure_lock:
        for key in list(_failures):
            if now - _failures[key][0] >= 60:
                del _failures[key]
        if address in _failures and _failures[address][1] >= 5:
            return jsonify(message='Слишком много попыток, повторите через минуту'), 429
    token = admin_token()
    if not token:
        return jsonify(message='Административный доступ отключён: не задан токен'), 503
    supplied = request.headers.get('X-Admin-Token', '')
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        with _failure_lock:
            if len(_failures) >= 256 and address not in _failures:
                _failures.pop(next(iter(_failures)))
            started, count = _failures.get(address, (now, 0))
            _failures[address] = (started, count + 1)
        return jsonify(message='Неверный токен администратора'), 401
    with _failure_lock:
        _failures.pop(address, None)
    session.clear()
    session['admin_digest'] = hashlib.sha256(token.encode()).hexdigest()
    session.permanent = True
    return jsonify(status='success')
