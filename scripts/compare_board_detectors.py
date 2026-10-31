"""Сравнение двух детекторов на одном исходном изображении доски"""

import argparse
import json
import time
from pathlib import Path
from tempfile import mkdtemp

import cv2


def compare(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    results = {}
    previews = {}
    for name in ('findChessboardCorners', 'findChessboardCornersSB'):
        started = time.perf_counter()
        try:
            if name == 'findChessboardCorners':
                found, corners = cv2.findChessboardCorners(
                    gray, (7, 7), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
                )
                if found:
                    corners = cv2.cornerSubPix(
                        gray, corners, (11, 11), (-1, -1),
                        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
                    )
            else:
                found, corners = cv2.findChessboardCornersSB(
                    gray, (7, 7), cv2.CALIB_CB_NORMALIZE_IMAGE,
                )
            elapsed = time.perf_counter() - started
            results[name] = {'found': bool(found), 'corners': len(corners) if found else 0,
                             'elapsed_ms': round(elapsed * 1000, 2)}
            preview = image.copy()
            if found:
                cv2.drawChessboardCorners(preview, (7, 7), corners, True)
            previews[name] = preview
        except (cv2.error, AttributeError) as error:
            results[name] = {'found': False, 'error': str(error),
                             'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)}
    return results, previews


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path, help='Исходное фото, на котором видна доска')
    parser.add_argument('--output', type=Path, default=Path('data/board_detector_comparison'))
    args = parser.parse_args()
    image = cv2.imread(str(args.image))
    if image is None:
        parser.error('Не удалось прочитать изображение')
    results, previews = compare(image)
    # Отдельный каталог для каждого запуска, чтобы не затереть предыдущие результаты
    args.output.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix='comparison-', dir=args.output))
    for name, preview in previews.items():
        if not cv2.imwrite(str(folder / f'{name}.png'), preview):
            raise OSError('Не удалось сохранить разметку')
    report = {'source': str(args.image), 'opencv': cv2.__version__,
              'image_size': [image.shape[1], image.shape[0]], 'board': [7, 7],
              'results': results}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (folder / 'report.json').write_text(text, encoding='utf-8')
    print(text)
    print(f'Результаты: {folder}')


if __name__ == '__main__':
    main()
