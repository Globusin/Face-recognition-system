"""Переопределение политик аутентификации из админ-панели

Файл применяется при запуске Monitor: изменение настроек защиты требует
перезапуска, чтобы не менять правила посреди попытки
"""

import copy
import json
from pathlib import Path

from utils.paths import PROJECT_ROOT

STEREO_MODES = ('off', 'advisory', 'required')
CHALLENGE_MODES = ('disabled', 'adaptive', 'always')


def policy_path(config):
    return PROJECT_ROOT / config.get('authentication', {}).get(
        'policy_file', 'data/security/authentication-policy.json',
    )


def load_override(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_override(config, override):
    """Копия конфига с применёнными переопределениями политики"""
    if not override:
        return config
    result = copy.deepcopy(config)
    for section, keys in (('stereo_liveness', ('mode',)),
                          ('challenge_response', ('policy', 'pipeline_count'))):
        values = override.get(section)
        if isinstance(values, dict):
            target = result.setdefault(section, {})
            for key in keys:
                if key in values:
                    target[key] = values[key]
    return result


def policy_values(config):
    return {
        'stereo_mode': str(
            config.get('stereo_liveness', {}).get('mode', 'off'),
        ).strip().lower(),
        'challenge_mode': str(
            config.get('challenge_response', {}).get('policy', 'disabled'),
        ).strip().lower(),
        'challenge_count': config.get('challenge_response', {}).get(
            'pipeline_count', 1,
        ),
    }


def validate_values(values):
    if not isinstance(values, dict):
        raise ValueError('Нужен объект с настройками политики')
    stereo = values.get('stereo_mode')
    challenge = values.get('challenge_mode')
    count = values.get('challenge_count')
    if stereo not in STEREO_MODES:
        raise ValueError('Неизвестный режим стереопроверки')
    if challenge not in CHALLENGE_MODES:
        raise ValueError('Неизвестная политика заданий')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
        raise ValueError('Число заданий должно быть от 1 до 5')
    return {
        'stereo_mode': stereo,
        'challenge_mode': challenge,
        'challenge_count': count,
    }


def save_override(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'stereo_liveness': {'mode': values['stereo_mode']},
        'challenge_response': {
            'policy': values['challenge_mode'],
            'pipeline_count': values['challenge_count'],
        },
    }
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    temporary.replace(path)
