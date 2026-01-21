import cv2
import logging
import os

def capture_image(output_path=None):
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()

    if ret:
        if output_path is None:
            os.makedirs('data', exist_ok=True)
            output_path = os.path.join('data', 'current_image.jpg')
        
        cv2.imwrite(output_path, frame)
        logging.info(f"Изображение сохранено как '{output_path}'")
        cap.release()
        return True
    else:
        logging.error("Не удалось получить изображение")
        cap.release()
        return False
