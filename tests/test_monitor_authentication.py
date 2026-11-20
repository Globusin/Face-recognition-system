"""Monitor использует автомат и сохраняет координацию Maintenance."""

import threading
import unittest
from unittest.mock import Mock, patch

from src.monitor import run_monitoring
from utils.maintenance import MaintenanceMode
from utils.face_observations import ObservationRejected


class MonitorAuthenticationTests(unittest.TestCase):
    def run_monitor(self, recognize):
        stop = threading.Event()
        mode = MaintenanceMode()
        lock = Mock()
        lock.unlock.return_value = True
        lock.lock.return_value = True
        display = Mock()
        def recognition(**kwargs):
            return recognize(stop, mode)
        with patch('src.monitor.load_config', return_value={}), \
                patch('src.monitor.initialize_lock_controller', return_value=lock), \
                patch('src.monitor.initialize_display', return_value=display), \
                patch('src.monitor.maintenance', mode), \
                patch('src.monitor.FaceObservationSource'), \
                patch('src.monitor.recognize_face_from_camera', side_effect=recognition), \
                patch('src.monitor.wait_or_stop', side_effect=lambda event, seconds: event.set()):
            run_monitoring(stop)
        return lock, mode, display

    def test_success_and_shutdown_close_lock(self):
        lock, mode, _ = self.run_monitor(lambda stop, mode: (True, 4, 0.1))
        lock.unlock.assert_called_once()
        lock.lock.assert_called_once()
        self.assertFalse(mode.door_open.is_set())

    def test_stop_during_recognition_prevents_unlock(self):
        def recognize(stop, mode):
            stop.set()
            return True, 4, 0.1
        lock, _, _ = self.run_monitor(recognize)
        lock.unlock.assert_not_called()
        lock.lock.assert_called_once()

    def test_maintenance_during_recognition_prevents_unlock(self):
        def recognize(stop, mode):
            mode.requested.set()
            return True, 4, 0.1
        lock, _, _ = self.run_monitor(recognize)
        lock.unlock.assert_not_called()

    def test_lost_track_prevents_unlock(self):
        def recognize(stop, mode):
            raise ObservationRejected('face_lost')
        lock, _, _ = self.run_monitor(recognize)
        lock.unlock.assert_not_called()
        lock.lock.assert_called_once()

    def test_processing_exception_prevents_unlock(self):
        def recognize(stop, mode):
            raise RuntimeError('camera unavailable')
        lock, _, _ = self.run_monitor(recognize)
        lock.unlock.assert_not_called()
        lock.lock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
