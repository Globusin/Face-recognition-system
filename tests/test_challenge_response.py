"""Проверки P6 без камер, дисплея и подключения к БД"""

import threading
import time
import unittest
import json
from unittest.mock import Mock, patch

import numpy as np

from utils.challenge_response import ChallengeFlow, FaceObservation, challenge_settings, eye_aspect_ratio, observe_face
from utils.maintenance import MaintenanceMode
from utils.challenge_session import ChallengeSession


def observation(timestamp, eye=0.3, yaw=0.0, identity=0.0, right=None):
    return FaceObservation(timestamp, eye, eye if right is None else right, yaw, np.full(128, identity))


class ChallengeFlowTests(unittest.TestCase):
    def test_task_report_times_angles_and_timeout(self):
        flow = self.make_flow('TURN_LEFT')
        for timestamp in (1.0, 1.3):
            sample = observation(timestamp, yaw=.3)
            sample.head_pose = dict(status='estimated', yaw_deg=-20., pitch_deg=2., roll_deg=1.)
            flow.feed(sample, timestamp)
        flow.feed(observation(1.5), 1.5)
        task = flow.snapshot(1.5)['tasks'][0]
        self.assertEqual(task['result'], 'PASS')
        self.assertAlmostEqual(task['reaction_seconds'], .1)
        self.assertAlmostEqual(task['confirmation_seconds'], .4)
        self.assertAlmostEqual(task['confirmed_hold_seconds'], .3)
        self.assertAlmostEqual(task['return_seconds'], .2)
        self.assertEqual(task['angle_ranges_deg']['yaw_deg'], {'min': -20., 'max': -20.})
        self.assertEqual(task['pose_observations'], 2)
        task['result'] = 'MODIFIED'
        self.assertEqual(flow.tasks[0]['result'], 'PASS')
        flow = self.make_flow('TURN_RIGHT')
        flow.check_timeout(10)
        self.assertEqual(flow.tasks[0]['result'], 'FAIL')
        self.assertEqual(flow.tasks[0]['reason'], 'timeout')
        self.assertEqual(flow.tasks[0]['finished_s'], 10)
        json.dumps(flow.snapshot(10), allow_nan=False)

    def test_missing_face_resets_hold_without_extending_timeout(self):
        flow = self.make_flow('TURN_LEFT')
        flow.feed(observation(1, yaw=.3), 1)
        self.assertEqual(flow.snapshot(1)['observation_status'], 'action_detected')
        deadline_start = flow.stage_started
        flow.missing_observation('face_lost')
        self.assertEqual(flow.snapshot(1)['observation_status'], 'face_lost')
        self.assertEqual(flow.stage, 'action')
        self.assertIsNone(flow.action_started)
        self.assertEqual(flow.stage_started, deadline_start)
        flow.feed(observation(2, yaw=.3), 2)
        self.assertEqual(flow.stage, 'action')
        flow.feed(observation(2.3, yaw=.3), 2.3)
        self.assertEqual(flow.snapshot(2.3)['observation_status'], 'action_confirmed')
        self.assertEqual(flow.stage, 'return')
        flow.check_timeout(10)
        self.assertEqual(flow.reason, 'timeout')

    def test_multiple_faces_are_visible_in_status(self):
        flow = self.make_flow('TURN_RIGHT')
        flow.fail('multiple_faces')
        self.assertEqual(flow.snapshot(1)['observation_status'], 'multiple_faces')
        self.assertEqual(flow.snapshot(1)['result'], 'FAIL')

    def test_missing_landmarks_resets_baseline_and_search_continues(self):
        flow = ChallengeFlow(challenge_settings({}), now=0, verify_identity=False)
        flow.feed(observation(.1), .1)
        flow.missing_observation('landmarks_not_detected')
        self.assertEqual(flow.neutral_samples, [])
        self.assertEqual(flow.stage, 'baseline')
        flow.check_timeout(13)
        self.assertEqual(flow.reason, 'baseline_timeout')

    def test_random_selection_contains_only_head_turns(self):
        flow = ChallengeFlow(challenge_settings({}), now=0, verify_identity=False)
        with patch('utils.challenge_response.secrets.choice', return_value='TURN_RIGHT') as choose:
            for timestamp in (.1, .4, .8):
                flow.feed(observation(timestamp), timestamp)
        choose.assert_called_once_with(('TURN_LEFT', 'TURN_RIGHT'))
        self.assertEqual(flow.command, 'TURN_RIGHT')

    def test_diagnostic_actions_accept_observations_without_embeddings(self):
        flow = ChallengeFlow(challenge_settings({'count': 1}), now=0, verify_identity=False)
        with patch('utils.challenge_response.secrets.choice', return_value='BLINK'):
            for timestamp, eye in ((.1, .3), (.4, .3), (.8, .3)):
                flow.feed(FaceObservation(timestamp, eye, eye, 0), timestamp)
        flow.acknowledge_prompt(.9)
        for timestamp, eye in ((1, .1), (1.2, .1), (1.4, .3)):
            flow.feed(FaceObservation(timestamp, eye, eye, 0), timestamp)
        self.assertEqual(flow.stage, 'passed')
        self.assertFalse(flow.snapshot(1.4)['identity_continuity_checked'])
        self.assertFalse(flow.snapshot(1.4)['access_granted'])
        self.assertIsNone(flow.anchor)

    def test_stale_frame_diagnostics_distinguish_age_and_gap(self):
        cases = [
            (None, 1.0, 3.0, 'observation_too_old'),
            (0.1, 2.0, 2.1, 'observation_gap_exceeded'),
            (1.0, 1.0, 1.1, 'non_increasing_observation_timestamp'),
            (None, 2.0, 1.0, 'future_observation_timestamp'),
        ]
        for previous, timestamp, now, failure in cases:
            with self.subTest(failure=failure):
                flow = ChallengeFlow(challenge_settings({}), now=0, preparation_mode=True)
                flow.last_timestamp = previous
                flow.feed(observation(timestamp), now)
                result = flow.snapshot(now)
                self.assertEqual(result['reason'], 'stale_frame')
                self.assertEqual(result['frame_timing']['failure'], failure)
                self.assertAlmostEqual(result['frame_timing']['age_after_processing_ms'], (now - timestamp) * 1000)
                self.assertEqual(result['frame_timing']['observation_limit_ms'], 1500)

    def test_preparation_has_no_timeout_but_action_does(self):
        flow = ChallengeFlow(challenge_settings({}), now=0, preparation_mode=True)
        flow.check_timeout(100)
        self.assertEqual(flow.stage, 'baseline')
        self.assertIsNone(flow.snapshot(100)['remaining_seconds'])
        flow.feed(observation(100, eye=.1), 100)
        self.assertEqual(flow.diagnostics['reason'], 'eyes_not_open')
        flow.feed(observation(100.1, yaw=.3), 100.1)
        self.assertEqual(flow.diagnostics['reason'], 'head_not_straight')
        flow.wait_for_baseline('face_lost')
        self.assertIsNone(flow.anchor)
        self.assertEqual(flow.neutral_samples, [])
        for timestamp in (101, 101.4, 101.8):
            flow.feed(observation(timestamp), timestamp)
        self.assertEqual(flow.stage, 'prompt')
        flow.acknowledge_prompt(102)
        flow.check_timeout(111)
        self.assertEqual(flow.reason, 'timeout')

    def test_preparation_reset_keeps_identity_after_completed_command(self):
        flow = ChallengeFlow(challenge_settings({}), now=0, preparation_mode=True)
        flow.anchor = np.zeros(128)
        flow.completed = 1
        flow.wait_for_baseline('face_lost')
        flow.feed(observation(1, identity=1), 1)
        self.assertEqual(flow.reason, 'identity_changed')

    def make_flow(self, command='BLINK'):
        flow = ChallengeFlow(challenge_settings({'count': 1}), now=0)
        with patch('utils.challenge_response.secrets.choice', return_value=command) as choose:
            for timestamp in (0.1, 0.4, 0.8):
                flow.feed(observation(timestamp), timestamp)
            choose.assert_called_once()
        self.assertEqual(flow.stage, 'prompt')
        flow.acknowledge_prompt(0.9)
        return flow

    def test_blink_requires_closing_both_eyes_then_reopening(self):
        flow = self.make_flow()
        flow.feed(observation(1.0, eye=.1, right=.3), 1.0)
        self.assertEqual(flow.stage, 'action')
        flow.feed(observation(1.2, eye=.1), 1.2)
        flow.feed(observation(1.35, eye=.1), 1.35)
        self.assertEqual(flow.stage, 'return')
        flow.feed(observation(1.5), 1.5)
        self.assertEqual(flow.snapshot(1.5)['result'], 'PASS')
        self.assertFalse(flow.snapshot(1.5)['access_granted'])

    def test_turn_direction_hold_and_return(self):
        for command, direction in [('TURN_LEFT', 1), ('TURN_RIGHT', -1)]:
            with self.subTest(command=command):
                flow = self.make_flow(command)
                flow.feed(observation(1.0, yaw=-direction * .3), 1.0)
                self.assertEqual(flow.stage, 'action')
                flow.feed(observation(1.2, yaw=direction * .3), 1.2)
                flow.feed(observation(1.5, yaw=direction * .3), 1.5)
                self.assertEqual(flow.stage, 'return')
                flow.feed(observation(1.7), 1.7)
                self.assertEqual(flow.stage, 'passed')

    def test_old_actions_and_closed_baseline_do_not_count(self):
        flow = ChallengeFlow(challenge_settings({}), now=0)
        with patch('utils.challenge_response.secrets.choice') as choose:
            for timestamp in (.1, .5, 1.0):
                flow.feed(observation(timestamp, eye=.1), timestamp)
            choose.assert_not_called()
        self.assertEqual(flow.stage, 'baseline')
        flow = self.make_flow()
        flow.feed(observation(.85, eye=.1), 1.0)
        self.assertEqual(flow.stage, 'action')
        self.assertIsNone(flow.action_started)

    def test_timeout_repeated_stale_and_changed_identity(self):
        cases = [(observation(.8), 1.0, 'stale_frame'),
                 (observation(3.0), 3.0, 'stale_frame'),
                 (observation(1.0, identity=.1), 1.0, 'identity_changed'),
                 (observation(1.0), 4.0, 'stale_frame'),
                 (observation(10.0), 10.0, 'timeout')]
        for sample, now, reason in cases:
            flow = self.make_flow()
            flow.feed(sample, now)
            self.assertEqual(flow.reason, reason)

    def test_baseline_timeout_and_bad_landmarks(self):
        flow = ChallengeFlow(challenge_settings({}), now=0)
        flow.check_timeout(6)
        self.assertEqual(flow.stage, 'baseline')
        flow.check_timeout(12)
        self.assertEqual(flow.reason, 'baseline_timeout')
        flow = self.make_flow()
        sample = observation(1.0)
        sample.embedding[0] = np.nan
        flow.feed(sample, 1.0)
        self.assertEqual(flow.reason, 'landmarks_not_detected')

    def test_multiple_commands_require_new_baseline_and_same_identity(self):
        flow = self.make_flow('TURN_LEFT')
        flow.settings['count'] = 2
        for sample in [observation(1., yaw=.3), observation(1.3, yaw=.3), observation(1.5)]:
            flow.feed(sample, sample.timestamp)
        self.assertEqual(flow.stage, 'baseline')
        self.assertEqual(flow.completed, 1)
        flow.feed(observation(1.7, identity=.2), 1.7)
        self.assertEqual(flow.reason, 'identity_changed')

    def test_settings_and_eye_formula(self):
        self.assertAlmostEqual(eye_aspect_ratio([(0, 0), (1, -1), (3, -1), (4, 0), (3, 1), (1, 1)]), .5)
        for config in [{'count': True}, {'count': 6}, {'open_ratio': .5}, {'action_timeout': 100}, {'turn_ratio': float('nan')}]:
            with self.assertRaises(ValueError):
                challenge_settings(config)
        with self.assertRaises(ValueError):
            eye_aspect_ratio([(0, 0)] * 6)

    def test_detector_errors_and_known_locations(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        durations = {}
        with patch('face_recognition.face_locations', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'face_lost'):
                observe_face(image, 1, durations)
        self.assertEqual(set(durations), {'image_preparation', 'face_detection'})
        with patch('face_recognition.face_locations', return_value=[(1, 2, 3, 4)] * 2):
            with self.assertRaisesRegex(ValueError, 'multiple_faces'):
                observe_face(image, 1)
        with patch('face_recognition.face_locations', return_value=[(1, 2, 3, 4)]), \
                patch('face_recognition.face_landmarks', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'landmarks_not_detected'):
                observe_face(image, 1)
        left = np.array([(10, 20), (12, 18), (18, 18), (20, 20), (18, 22), (12, 22)])
        landmarks = dict(left_eye=left, right_eye=left + [30, 0], nose_tip=[[25, 30]] * 5)
        locations = [(5, 60, 70, 5)]
        durations = {}
        with patch('face_recognition.face_locations', return_value=locations), \
                patch('face_recognition.face_landmarks', return_value=[landmarks]) as detect_points, \
                patch('face_recognition.face_encodings', return_value=[np.zeros(128)]) as encode:
            result = observe_face(image, 1, durations)
        self.assertEqual(set(durations), {'image_preparation', 'face_detection', 'landmarks', 'embedding', 'head_pose'})
        self.assertTrue(all(len(values) == 1 and values[0] >= 0 for values in durations.values()))
        self.assertAlmostEqual(result.left_eye, .4)
        self.assertEqual(result.timestamp, 1)
        self.assertEqual(detect_points.call_args.kwargs['face_locations'], locations)
        self.assertEqual(encode.call_args.kwargs['known_face_locations'], locations)
        self.assertEqual(encode.call_args.kwargs['model'], 'small')
        durations = {}
        with patch('face_recognition.face_locations', return_value=locations), \
                patch('face_recognition.face_landmarks', return_value=[landmarks]), \
                patch('face_recognition.face_encodings') as encode:
            result = observe_face(image, 1, durations, verify_identity=False)
        encode.assert_not_called()
        self.assertIsNone(result.embedding)
        self.assertNotIn('embedding', durations)


class ChallengeSessionTests(unittest.TestCase):
    def test_maintenance_waits_for_monitor_search_and_allows_resume(self):
        gate = MaintenanceMode()
        searching = threading.Event()
        paused = threading.Event()

        def search():
            with gate.recognition():
                searching.set()
                gate.requested.wait(2)
            paused.set()

        worker = threading.Thread(target=search)
        worker.start()
        try:
            self.assertTrue(searching.wait(2))
            gate.begin()
            self.assertTrue(paused.wait(2))
            with self.assertRaises(RuntimeError):
                with gate.recognition():
                    self.fail('Монитор не должен работать во время обслуживания')
            gate.end()
            with gate.recognition():
                pass
        finally:
            gate.requested.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_requires_consent_and_excludes_calibration(self):
        service = ChallengeSession()
        with self.assertRaises(ValueError):
            service.start(False)
        with patch('utils.challenge_session.load_config', return_value={}), \
                patch('utils.challenge_session.calibration_session.active', True):
            with self.assertRaises(RuntimeError):
                service.start(True)

    def test_cancellation_and_resource_cleanup(self):
        gate = MaintenanceMode()
        gate.display = Mock()
        entered = threading.Event()
        manager = Mock()

        def latest(*args, **kwargs):
            entered.set()
            time.sleep(.02)
            return None

        manager.get_latest_frame.side_effect = latest
        service = ChallengeSession()
        with patch('utils.challenge_session.maintenance', gate), \
                patch('utils.challenge_session.calibration_session.active', False), \
                patch('utils.challenge_session.load_config', return_value={}), \
                patch('utils.challenge_session.get_camera_manager', return_value=manager), \
                patch('utils.challenge_session.write_json') as save_report:
            result = service.start(True)
            self.assertTrue(entered.wait(2))
            with self.assertRaises(RuntimeError):
                gate.begin()
            with self.assertRaises(RuntimeError):
                with gate.recognition():
                    pass
            service.cancel(result['session_id'])
            service.worker.join(3)
            self.assertFalse(service.worker.is_alive())
            saved = save_report.call_args.args[1]
            self.assertEqual(saved['session_id'], result['session_id'])
            self.assertTrue(saved['diagnostic_only'])
            self.assertFalse(saved['access_granted'])
            self.assertEqual(saved['reason'], 'cancelled')
            json.dumps(saved, allow_nan=False)
        self.assertFalse(gate.requested.is_set())
        self.assertFalse(gate.challenge_running.is_set())
        self.assertEqual(service.status()['reason'], 'cancelled')
        self.assertNotIn('embedding', service.status())
        with self.assertRaises(ValueError):
            service.cancel('old-session')

    def test_worker_completes_and_shows_command_after_baseline(self):
        gate = MaintenanceMode()
        gate.display = Mock()
        gate.requested.set()
        gate.challenge_running.set()
        manager = Mock()
        clock = [100.0]
        samples = iter([(100.0, None), (100.1, 0), (100.4, 0), (100.8, 0),
                        (101.0, None), (101.1, .3), (101.4, .3), (101.6, 0)])
        current = [None]

        def latest(*args, **kwargs):
            timestamp, yaw = next(samples)
            clock[0] = timestamp
            current[0] = None if yaw is None else observation(timestamp, yaw=yaw)
            return Mock(sequence=round(timestamp * 10), timestamp_ns=int(timestamp * 1e9), image=None)

        def observe(*args, **kwargs):
            if current[0] is None:
                raise ValueError('face_lost')
            return current[0]

        manager.get_latest_frame.side_effect = latest
        service = ChallengeSession()
        with patch('utils.challenge_session.maintenance', gate), \
                patch('utils.challenge_session.get_camera_manager', return_value=manager), \
                patch('utils.challenge_session.observe_face', side_effect=observe), \
                patch('utils.challenge_response.secrets.choice', return_value='TURN_LEFT'), \
                patch('utils.challenge_session.time.monotonic', side_effect=lambda: clock[0]), \
                patch.object(service.cancelled, 'wait'):
            service._run(challenge_settings({'count': 1}))
        result = service.status()
        self.assertEqual(result['result'], 'PASS')
        self.assertFalse(result['access_granted'])
        self.assertEqual(result['completed'], 1)
        self.assertFalse(gate.requested.is_set())
        details = [call.args[1] for call in gate.display.show_state.call_args_list if len(call.args) > 1]
        self.assertIn('Поверните\nголову влево', details)
        self.assertEqual(details[-1], 'Задания\nвыполнены')

    def test_missing_hardware_display_and_thread_failure_do_not_reserve_mode(self):
        from utils.display import NullDisplay
        for display in (None, NullDisplay()):
            gate = MaintenanceMode()
            gate.display = display
            with patch('utils.challenge_session.maintenance', gate), \
                    patch('utils.challenge_session.load_config', return_value={}), \
                    patch('utils.challenge_session.calibration_session.active', False):
                with self.assertRaises(RuntimeError):
                    ChallengeSession().start(True)
            self.assertFalse(gate.requested.is_set())
        gate.display = Mock()
        with patch('utils.challenge_session.maintenance', gate), \
                patch('utils.challenge_session.load_config', return_value={}), \
                patch('utils.challenge_session.calibration_session.active', False), \
                patch('utils.challenge_session.threading.Thread.start', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                ChallengeSession().start(True)
        self.assertFalse(gate.requested.is_set())
        self.assertFalse(gate.challenge_running.is_set())

    def test_api_requires_https_admin_and_does_not_authenticate(self):
        from src.app import app
        client = app.test_client()
        with patch('src.app.authorize_admin', return_value=({'message': 'denied'}, 401)):
            self.assertEqual(client.get('/api/challenge/status').status_code, 401)
        self.assertEqual(client.post('/api/challenge/start', base_url='http://localhost', json={}).status_code, 403)
        with patch('src.app.authorize_admin', return_value=None):
            self.assertEqual(client.post('/api/challenge/start', json=[]).status_code, 400)
            self.assertEqual(client.post('/api/challenge/start', json={}).status_code, 409)
            self.assertEqual(client.post('/api/challenge/cancel', json={'session_id': 'bad'}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
