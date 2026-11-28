"""YuNet: один экземпляр модели на процесс, координаты исходного кадра."""
import math
import threading

import cv2

from utils.paths import PROJECT_ROOT
from utils.capture.camera_manager import CameraError


class YuNetDetector:
    def __init__(self, settings):
        self.width = int(settings.get('input_width', 320))
        self.score = float(settings.get('score_threshold', 0.8))
        self.nms = float(settings.get('nms_threshold', 0.3))
        if self.width < 32 or not (0 < self.score <= 1 and 0 < self.nms <= 1):
            raise ValueError('Некорректные параметры YuNet')
        self.path = PROJECT_ROOT / settings.get(
            'model_path', 'data/models/face_detection_yunet_2023mar.onnx')
        self._lock = threading.Lock()
        self._model = None

    def detect(self, frame):
        height, width = frame.shape[:2]
        w = min(self.width, width)
        h = max(1, round(height * w / width))
        reduced = (cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
                   if (w, h) != (width, height) else frame)
        with self._lock:
            if self._model is None:
                if not self.path.is_file():
                    raise CameraError(f'Нет модели YuNet: {self.path}. '
                                      'Запустите scripts/install_yunet.py')
                try:
                    self._model = cv2.FaceDetectorYN.create(
                        str(self.path), '', (w, h), self.score, self.nms, 5000)
                except cv2.error as error:
                    raise CameraError(f'Не удалось загрузить YuNet: {error}') from error
            try:
                self._model.setInputSize((w, h))
                _, detections = self._model.detect(reduced)
            except cv2.error as error:
                raise CameraError(f'Ошибка YuNet: {error}') from error
        boxes = []
        if detections is None:
            return boxes
        for row in detections:
            x, y, bw, bh = row[:4]
            if not all(math.isfinite(v) for v in (x, y, bw, bh)):
                continue
            left = max(0, min(width, math.floor(x * width / w)))
            top = max(0, min(height, math.floor(y * height / h)))
            right = max(0, min(width, math.ceil((x + bw) * width / w)))
            bottom = max(0, min(height, math.ceil((y + bh) * height / h)))
            if right > left and bottom > top:
                boxes.append((left, top, right - left, bottom - top))
        return boxes
