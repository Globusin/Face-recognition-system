"""Повторный расчёт калибровки из сохранённого набора пар"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.stereo_calibration import BOARD, solve_calibration, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--invalidate', action='store_true', help='Пометить параметры недействительными')
    args = parser.parse_args()
    folder = args.folder

    if args.invalidate:
        metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
        metadata['status'] = 'invalidated'
        write_json(folder / 'metadata.json', metadata)
        print('Калибровка помечена недействительной')
        return
    
    metadata = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    if metadata['board'] != list(BOARD) or metadata['units'] != 'mm':
        parser.error('Параметры доски не соответствуют этому режиму')
    samples = json.loads((folder / 'samples.json').read_text(encoding='utf-8'))
    for sample in samples:
        for role in ('primary', 'secondary'):
            sample[role] = np.asarray(sample[role], dtype=np.float32)
    training_pairs = [sample for sample in samples if not sample['validation']]
    # Контрольные пары
    validation_pairs = [sample for sample in samples if sample['validation']]

    arrays, metrics = solve_calibration(
        training_pairs, validation_pairs,
        tuple(metadata['image_size']), metadata['square_mm']
    )
    metadata.update(created_at=datetime.now(timezone.utc).isoformat(), metrics=metrics, status='requires_review')
    metadata.pop('validation', None)
    np.savez_compressed(folder / 'parameters.npz', **arrays)
    write_json(folder / 'metadata.json', metadata)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
