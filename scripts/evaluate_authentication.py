"""Оценка отказов по заранее размеченному журналу реальных предъявлений."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path


def summarize(rows):
    groups = defaultdict(list)
    seen = set()
    sessions = set()
    for row in rows:
        attempt = row['attempt_id']
        if not isinstance(attempt, str) or not attempt or attempt in seen:
            raise ValueError('Повтор или отсутствие attempt_id')
        seen.add(attempt)
        session = row.get('session_id')
        if session is not None:
            if not isinstance(session, str) or not session or session in sessions:
                raise ValueError('Одна сессия не может учитываться дважды')
            sessions.add(session)
        if row['detector'] not in ('haar', 'yunet') or type(row['genuine']) is not bool:
            raise ValueError('Требуются detector и genuine')
        decision = row['decision']
        if decision not in ('GRANTED', 'DENIED', 'ERROR', 'NO_SESSION'):
            raise ValueError('Неизвестный итог предъявления')
        if (decision == 'NO_SESSION') != (session is None):
            raise ValueError('session_id обязателен для завершённых сессий')
        if row['genuine'] and row.get('expected_user_id') is None:
            raise ValueError('Для genuine нужен expected_user_id')
        if decision == 'GRANTED' and row.get('user_id') is None:
            raise ValueError('Для допуска нужен user_id')
        seconds = float(row['elapsed_seconds'])
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Некорректная длительность')
        groups[row['detector']].append(row)
    result = {}
    for detector, attempts in groups.items():
        genuine = [r for r in attempts if r['genuine']]
        other = [r for r in attempts if not r['genuine']]
        refused = [r for r in genuine if r['decision'] != 'GRANTED']
        wrong = [r for r in genuine if r['decision'] == 'GRANTED'
                 and r['user_id'] != r['expected_user_id']]
        false_accept = sum(r['decision'] == 'GRANTED' for r in other)
        reasons = Counter(r.get('reason') or r['decision'] for r in refused)
        times = sorted(float(r['elapsed_seconds']) for r in genuine)
        result[detector] = {
            'genuine_attempts': len(genuine), 'non_genuine_attempts': len(other),
            'false_rejections': len(refused),
            'frr_end_to_end': len(refused)/len(genuine) if genuine else None,
            'no_session': sum(r['decision'] == 'NO_SESSION' for r in genuine),
            'wrong_identity_grants': len(wrong),
            'unsuccessful_correct_authentication_rate':
                (len(refused)+len(wrong))/len(genuine) if genuine else None,
            'false_accepts_non_genuine': false_accept,
            'false_accept_rate_non_genuine': false_accept/len(other) if other else None,
            'rejection_reasons': dict(reasons),
            'genuine_p95_seconds': times[math.ceil(.95*len(times))-1] if times else None,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.manifest.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        parser.error('Нет предъявлений')
    print(json.dumps(summarize(rows), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
