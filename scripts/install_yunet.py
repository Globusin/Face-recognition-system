"""Установка проверенной модели OpenCV Zoo, без скачивания при аутентификации."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

URL = ('https://media.githubusercontent.com/media/opencv/opencv_zoo/main/'
       'models/face_detection_yunet/face_detection_yunet_2023mar.onnx')
SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
TARGET = Path(__file__).resolve().parents[1] / 'data/models/face_detection_yunet_2023mar.onnx'


def main():
    if TARGET.is_file() and hashlib.sha256(TARGET.read_bytes()).hexdigest() == SHA256:
        print(TARGET)
        return
    with urlopen(URL, timeout=30) as response:
        content = response.read(232590)
    if len(content) != 232589 or hashlib.sha256(content).hexdigest() != SHA256:
        raise RuntimeError('Контрольная сумма модели YuNet не совпадает')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix('.tmp')
    temporary.write_bytes(content)
    temporary.replace(TARGET)
    print(TARGET)


if __name__ == '__main__':
    main()
