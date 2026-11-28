"""Парное сравнение Haar/YuNet на размеченных изображениях; без камеры и БД."""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.capture.video_capture import detect_faces_haar
from utils.capture.yunet_detector import YuNetDetector
from utils.common.config_loader import load_config


def iou(a, b):
    x, y, w, h = a
    X, Y, W, H = b
    intersection = max(0, min(x+w, X+W)-max(x, X)) * max(0, min(y+h, Y+H)-max(y, Y))
    union = w*h + W*H - intersection
    return intersection / union if union > 0 else 0


def match(predictions, truth, threshold):
    """Максимальное число взаимно однозначных совпадений при заданном IoU."""
    candidates = [[j for j, box in enumerate(truth) if iou(p, box) >= threshold]
                  for p in predictions]
    assigned = {}

    def augment(i, seen):
        for j in candidates[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in assigned or augment(assigned[j], seen):
                assigned[j] = i
                return True
        return False

    tp = sum(augment(i, set()) for i in range(len(predictions)))
    return tp, len(predictions)-tp, len(truth)-tp


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path, help='JSONL: image, boxes, необязательная condition')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--iou', type=float, default=.5)
    parser.add_argument('--threads', type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1 or args.threads < 1 or not 0 < args.iou <= 1:
        parser.error('Некорректные параметры')
    cv2.setNumThreads(args.threads)
    settings = (load_config() or {}).get('face_detection', {}).get('yunet', {})
    detectors = {'haar': detect_faces_haar, 'yunet': YuNetDetector(settings).detect}
    rows = [json.loads(line) for line in args.manifest.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        parser.error('Пустая выборка')
    stats = {}

    def bucket(name, condition):
        return stats.setdefault(name, {}).setdefault(condition, {
            'tp': 0, 'fp': 0, 'fn': 0, 'images': 0, 'single_face_images': 0,
            'single_face_rejected': 0, 'times': []})

    for index, row in enumerate(rows):
        frame = cv2.imread(str(args.manifest.parent / row['image']))
        if frame is None:
            raise ValueError(f'Не читается изображение: {row["image"]}')
        truth = row['boxes']
        if any(len(b) != 4 or not all(np.isfinite(b)) or min(b[:2]) < 0 or min(b[2:]) <= 0
               or b[0]+b[2] > frame.shape[1] or b[1]+b[3] > frame.shape[0] for b in truth):
            raise ValueError(f'Некорректная разметка: {row["image"]}')
        condition = str(row.get('condition', 'unspecified'))
        names = list(detectors)
        if index % 2:
            names.reverse()
        for name in names:
            detector = detectors[name]
            if index == 0:
                detector(frame)  # прогрев не входит в замеры
            times = []
            for _ in range(args.repeats):
                started = time.perf_counter()
                prediction = detector(frame)
                times.append((time.perf_counter()-started)*1000)
            tp, fp, fn = match(prediction, truth, args.iou)
            for key in ('all', 'condition:' + condition):
                b = bucket(name, key)
                b['tp'] += tp
                b['fp'] += fp
                b['fn'] += fn
                b['images'] += 1
                b['single_face_images'] += len(truth) == 1
                b['single_face_rejected'] += len(truth) == 1 and (len(prediction) != 1 or tp != 1)
                b['times'].extend(times)
    for groups in stats.values():
        for b in groups.values():
            times = b.pop('times')
            b.update(precision=rate(b['tp'], b['tp']+b['fp']),
                     recall=rate(b['tp'], b['tp']+b['fn']),
                     single_face_rejection_rate=rate(b['single_face_rejected'], b['single_face_images']),
                     mean_ms=float(np.mean(times)), p50_ms=float(np.median(times)),
                     p95_ms=float(np.percentile(times, 95)), p99_ms=float(np.percentile(times, 99)))
    print(json.dumps({'platform': platform.platform(), 'opencv': cv2.__version__,
                      'threads': cv2.getNumThreads(), 'repeats': args.repeats,
                      'iou': args.iou, 'yunet_settings': settings, 'results': stats},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
