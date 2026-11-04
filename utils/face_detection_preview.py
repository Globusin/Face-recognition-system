"""Временное превью результатов уже выполненной детекции Haar"""

import threading
import time

import cv2


class FaceDetectionPreview:
    def __init__(self):
        self.lock = threading.Lock()
        self.enabled_until = 0
        self.latest = None
        self.last_positive = None

    def enable(self):
        with self.lock:
            self.enabled_until = time.monotonic() + 5

    def record(self, frame, faces, stage):
        with self.lock:
            if time.monotonic() > self.enabled_until:
                self.latest = None
                self.last_positive = None
                return

            sample = dict(image=frame.image.copy(), faces=tuple(faces), stage=stage,
                          sequence=frame.sequence, recorded_at=time.monotonic())
            self.latest = sample
            if faces:
                self.last_positive = sample

    def render(self, current_frame):
        with self.lock:
            now = time.monotonic()
            # Сохраняем редкое ложное срабатывание видимым в течение 10 секунд
            sample = self.last_positive
            if sample is None or now - sample['recorded_at'] > 10:
                sample = self.latest
            if sample is None or now - sample['recorded_at'] > 10:
                image = current_frame.image.copy()
                label = 'Haar: no recent detection sample'
            else:
                image = sample['image'].copy()
                for x, y, width, height in sample['faces']:
                    cv2.rectangle(image, (x, y), (x + width, y + height), (0, 0, 255), 3)
                age = now - sample['recorded_at']
                label = f'Haar: {len(sample["faces"])} | #{sample["sequence"]} | {sample["stage"]} | {age:.1f}s ago'

        # Надпись остаётся читаемой после уменьшения кадра до ширины 640
        scale = max(1, image.shape[1] / 640)
        cv2.rectangle(image, (0, 0), (image.shape[1], round(36 * scale)), (0, 0, 0), -1)
        cv2.putText(image, label, (round(8 * scale), round(25 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (255, 255, 255), max(1, round(scale)))
        return image


face_detection_preview = FaceDetectionPreview()
