"""Вывод разных потоков не должен перемешивать команды SPI"""

import threading
import time
import unittest
from unittest.mock import Mock, patch

from utils.device.display import TFTDisplay, DisplayState


class DisplayTests(unittest.TestCase):
    def test_output_is_serialized_between_threads(self):
        driver = Mock(width=128, height=160)
        active = 0
        maximum = 0
        counter_lock = threading.Lock()

        def write(image):
            nonlocal active, maximum
            with counter_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(.01)
            with counter_lock:
                active -= 1

        driver.image.side_effect = write
        display = TFTDisplay(driver)
        barrier = threading.Barrier(3)
        errors = []

        def output(action):
            try:
                barrier.wait(timeout=2)
                action()
            except Exception as error:
                errors.append(error)

        actions = [lambda: display.show_state(DisplayState.CHALLENGE, 'Смотрите прямо'),
                   lambda: display.show_text('Проверка'), display.clear]
        threads = [threading.Thread(target=output, args=(action,)) for action in actions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(maximum, 1)
        self.assertEqual(driver.image.call_count, 3)

    def test_driver_error_is_logged_and_lock_is_released(self):
        driver = Mock(width=128, height=160)
        display = TFTDisplay(driver)
        driver.image.side_effect = OSError('SPI недоступен')
        with patch('utils.device.display.log_error') as log:
            with self.assertRaises(OSError):
                display.show_state(DisplayState.CHALLENGE)
        self.assertIn('SPI недоступен', log.call_args.args[0])
        self.assertIsNone(display._last_state)
        driver.image.side_effect = None
        display.clear()


if __name__ == '__main__':
    unittest.main()
