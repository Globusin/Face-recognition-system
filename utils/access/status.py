"""Снимок текущей попытки и история для веб-панели"""

import threading
import time
from datetime import datetime, timezone

CHECK_NAMES = ('recognition', 'stereo', 'challenge')
DECISIONS = ('GRANTED', 'DENIED', 'ERROR')


class AuthenticationService:
    """Связывает автомат аутентификации с API и журналом

    Автомат остаётся единственным распознавателем: сервис только читает его
    снимок и записывает обезличенный итог попытки
    """

    def __init__(self, clock=time.monotonic):
        self._lock = threading.Lock()
        self._engine = None
        self._audit = None
        self._running_policy = None
        self._challenge_session = None
        self._challenge_progress = None
        self.clock = clock

    def attach(self, engine):
        with self._lock:
            self._engine = engine

    def configure_audit(self, audit):
        with self._lock:
            self._audit = audit

    def set_running_policy(self, policy):
        with self._lock:
            self._running_policy = policy

    def running_policy(self):
        with self._lock:
            return self._running_policy

    def publish_challenge_progress(self, session_id, progress):
        with self._lock:
            self._challenge_session = session_id
            self._challenge_progress = progress

    def snapshot(self):
        with self._lock:
            engine = self._engine
            progress = self._challenge_progress
            progress_session = self._challenge_session
        if engine is None:
            return {'state': 'IDLE', 'session': None, 'door_open': False}
        raw = engine.snapshot()
        session = raw.get('session') or {}
        if progress_session != session.get('session_id'):
            progress = None
        return dict(raw, challenge=progress)

    def public_snapshot(self):
        """Снимок без идентификаторов для пользовательской панели"""
        raw = self.snapshot()
        session = raw.get('session') or {}
        checks = session.get('checks') or {}
        diagnostics = session.get('diagnostics') or {}
        stereo = diagnostics.get('stereo') or {}
        state = raw.get('state')
        decision = None
        if state == 'GRANTED':
            decision = 'GRANTED'
        elif state in ('DENIED', 'ERROR'):
            decision = 'DENIED'
        elif state in ('TRACKING', 'EVALUATING', 'CHALLENGE'):
            decision = 'PENDING'
        now = self.clock()
        started = session.get('started_at')
        updated = session.get('updated_at')
        return {
            'state': state,
            'door_open': bool(raw.get('door_open')),
            'session_id': session.get('session_id'),
            'decision': decision,
            'reason': session.get('reason') or '',
            'identity_matched': (
                (checks.get('recognition') or {}).get('status') == 'PASS'
            ),
            'checks': {
                name: checks.get(name) or {'status': None, 'reason': None}
                for name in CHECK_NAMES
            },
            'stereo': {
                'decision': stereo.get('decision'),
                'reason': stereo.get('reason'),
            },
            'challenge': raw.get('challenge'),
            'elapsed_seconds': (
                round(now - started, 2) if started is not None else None
            ),
            'updated_seconds_ago': (
                round(now - updated, 2) if updated is not None else None
            ),
        }

    def record_session(self, session):
        """Обезличенный итог попытки; изображения и embeddings не пишутся"""
        with self._lock:
            audit = self._audit
        if audit is None:
            return
        checks = {
            name: {'status': result.status.value, 'reason': result.reason}
            for name, result in session.checks.items()
        }
        diagnostics = session.diagnostics or {}
        stereo = diagnostics.get('stereo') or {}
        finished = session.finished_at or self.clock()
        audit.append({
            'type': 'session',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'session_id': session.session_id,
            'decision': getattr(session.state, 'value', session.state),
            'reason': session.reason,
            'user_id': session.user_id,
            'distance': session.distance,
            'checks': checks,
            'stereo_decision': stereo.get('decision'),
            'stereo_reason': stereo.get('reason'),
            'unlock_attempted': session.unlock_attempted,
            'duration_seconds': round(max(0.0, finished - session.started_at), 2),
        })

    def record_policy_change(self, values, remote_addr=None):
        with self._lock:
            audit = self._audit
        if audit is None:
            return
        audit.append({
            'type': 'policy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'details': {'values': values, 'remote_addr': remote_addr},
        })

    def flush_audit(self, timeout=2.0):
        """Дожидается записи журнала при остановке; ошибки не критичны"""
        with self._lock:
            audit = self._audit
        flush = getattr(audit, 'flush', None)
        if callable(flush):
            return flush(timeout)
        return True

    def history(self, limit=50, decision=None, kind=None):
        with self._lock:
            audit = self._audit
        if audit is None:
            return []
        return audit.read(limit=limit, decision=decision, kind=kind)


authentication_service = AuthenticationService()
