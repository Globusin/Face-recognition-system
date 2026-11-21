"""Накопление свидетельств идентичности и режимы распознавания без оборудования"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from utils.evidence import FAIL, INDETERMINATE, PASS, IdentityEvidence
from utils.face_observations import ObservationRejected
from utils.recognition import (
    get_adaptive_recognition_config,
    get_recognition_mode,
    match_embedding,
    recognize_face_from_camera,
)


def make_evidence(**overrides):
    params = {
        'prior_probability': 0.2,
        'distance_sigma': 0.08,
        'unknown_likelihood': 0.05,
        'miss_likelihood_ratio': 0.4,
        'minimum_likelihood': 0.000001,
        'correlation_discount': 0.4,
        'min_frames': 3,
        'max_frames': 7,
        'min_successful_frames': 3,
        'max_distance_std': 0.05,
        'decision_threshold': 0.98,
        'early_stop_threshold': 0.98,
    }
    params.update(overrides)
    return IdentityEvidence(**params)


def add_frames(evidence, user_id, distance, count):
    for _ in range(count):
        evidence.add(user_id, distance)
    return evidence


class IdentityEvidenceTests(unittest.TestCase):
    def test_correlated_frames_do_not_multiply_confidence(self):
        independent = add_frames(make_evidence(correlation_discount=1.0), 1, 0.10, 2)
        tempered = add_frames(make_evidence(correlation_discount=0.4), 1, 0.10, 2)

        # Два независимых кадра дали бы высокую уверенность, поправка её снижает
        self.assertGreater(independent.score(1), 0.95)
        self.assertLess(tempered.score(1), 0.95)
        self.assertLess(tempered.score(1), independent.score(1))

    def test_score_orders_distances(self):
        scores = []
        for distance in (0.05, 0.10, 0.14):
            evidence = make_evidence()
            evidence.add(1, distance)
            scores.append(evidence.score(1))
        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[1], scores[2])

    def test_early_stop_only_after_enough_evidence(self):
        evidence = make_evidence()
        add_frames(evidence, 1, 0.10, 4)
        self.assertIsNone(evidence.early_decision())

        evidence.add(1, 0.10)
        decision = evidence.early_decision()
        self.assertIsNotNone(decision)
        self.assertEqual(decision.status, PASS)
        self.assertEqual(decision.reason, 'early_stop')
        self.assertEqual(decision.user_id, 1)
        self.assertEqual(decision.frames, 5)
        self.assertAlmostEqual(decision.distance, 0.10)

    def test_early_stop_respects_min_frames(self):
        relaxed = make_evidence(min_frames=3)
        add_frames(relaxed, 1, 0.02, 3)
        self.assertEqual(relaxed.early_decision().status, PASS)

        strict = make_evidence(min_frames=4)
        add_frames(strict, 1, 0.02, 3)
        self.assertIsNone(strict.early_decision())
        strict.add(1, 0.02)
        self.assertEqual(strict.early_decision().status, PASS)

    def test_conflicting_identities_are_indeterminate(self):
        evidence = make_evidence()
        add_frames(evidence, 1, 0.10, 3)
        add_frames(evidence, 2, 0.10, 3)

        decision = evidence.result()
        self.assertEqual(decision.status, INDETERMINATE)
        self.assertEqual(decision.reason, 'conflicting_identities')

    def test_identity_switch_is_not_a_pass(self):
        evidence = make_evidence()
        add_frames(evidence, 1, 0.10, 4)
        add_frames(evidence, 2, 0.10, 3)

        self.assertEqual(evidence.result().status, INDETERMINATE)

    def test_insufficient_matches_fail(self):
        evidence = make_evidence()
        add_frames(evidence, 1, 0.10, 2)

        decision = evidence.result()
        self.assertEqual(decision.status, FAIL)
        self.assertEqual(decision.reason, 'insufficient_matches')

    def test_no_matches_fail_and_impossible_attempt_stops_early(self):
        evidence = make_evidence()
        add_frames(evidence, None, None, 5)

        early = evidence.early_decision()
        self.assertEqual(early.status, FAIL)
        self.assertEqual(early.reason, 'insufficient_matches')

        self.assertEqual(evidence.result().reason, 'no_identity_matches')

    def test_unstable_distance_fails(self):
        evidence = make_evidence()
        evidence.add(1, 0.01)
        evidence.add(1, 0.10)
        evidence.add(1, 0.15)

        decision = evidence.result()
        self.assertEqual(decision.status, FAIL)
        self.assertEqual(decision.reason, 'unstable_distance')

    def test_result_distance_is_mean_of_leader_frames(self):
        evidence = make_evidence()
        add_frames(evidence, 1, 0.04, 3)
        evidence.add(1, 0.08)

        decision = evidence.result()
        self.assertEqual(decision.status, PASS)
        self.assertAlmostEqual(decision.distance, 0.05)

    def test_disabled_scoring_uses_frame_count_only(self):
        evidence = make_evidence(decision_threshold=None, early_stop_threshold=None)
        add_frames(evidence, 1, 0.14, 3)

        decision = evidence.result()
        self.assertEqual(decision.status, PASS)
        self.assertLess(decision.score, 0.98)

    def test_invalid_settings_are_rejected(self):
        invalid = (
            {'prior_probability': 1.0},
            {'miss_likelihood_ratio': 1.5},
            {'correlation_discount': 0},
            {'max_frames': 2, 'min_frames': 3},
            {'min_successful_frames': 8},
            {'max_distance_std': -0.1},
            {'decision_threshold': 1.0},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    make_evidence(**overrides)


class FakeClock:
    def __init__(self, step=0.0):
        self.value = 0.0
        self.step = step

    def __call__(self):
        return self.value


class FakeObservationSource:
    def __init__(self, available=7, step=0.0):
        self.available = available
        self.clock = FakeClock(step)
        self.used = 0
        self.next_calls = 0

    def observations(self, count, interval, deadline):
        for _ in range(min(count, self.available)):
            self.clock.value += self.clock.step
            self.used += 1
            yield SimpleNamespace(
                primary=SimpleNamespace(image=object()), face_box=(0, 0, 1, 1),
            )

    def check_cancelled(self, deadline=None):
        return None

    def next(self, deadline=None):
        self.next_calls += 1
        return None


ADAPTIVE_SETTINGS = {
    'min_frames': 3,
    'max_frames': 7,
    'min_successful_frames': 3,
    'frame_interval': 0.2,
    'early_stop_threshold': 0.98,
    'max_attempt_duration': 2.5,
    'max_distance_std': 0.05,
}


class RecognitionModeTests(unittest.TestCase):
    def test_recognition_mode_comes_from_config(self):
        with patch.dict('utils.recognition.config',
                        {'multi_frame_recognition': {'mode': 'adaptive'}}):
            self.assertEqual(get_recognition_mode(), 'adaptive')
        with patch.dict('utils.recognition.config',
                        {'multi_frame_recognition': {}}):
            self.assertEqual(get_recognition_mode(), 'fixed')
        with patch.dict('utils.recognition.config',
                        {'multi_frame_recognition': {'mode': 'unknown'}}):
            with self.assertRaises(ValueError):
                get_recognition_mode()

    def test_adaptive_settings_convert_interval_and_validate(self):
        section = {'frame_interval_ms': 250.0, 'max_frames': 3, 'min_frames': 2}
        with patch.dict('utils.recognition.config', {'adaptive_recognition': section}):
            settings = get_adaptive_recognition_config()
        self.assertAlmostEqual(settings['frame_interval'], 0.25)
        self.assertEqual(settings['max_frames'], 3)

        with patch.dict('utils.recognition.config',
                        {'adaptive_recognition': {'min_frames': 5, 'max_frames': 3}}):
            with self.assertRaises(ValueError):
                get_adaptive_recognition_config()

    def test_match_embedding_applies_similarity_threshold(self):
        cases = (
            ((1, 0.10), (1, 0.10)),
            ((1, 0.15), (None, 0.15)),
            ((None, None), (None, None)),
            ((1, None), (None, None)),
            ((1, float('nan')), (None, None)),
        )
        for nearest, expected in cases:
            with self.subTest(nearest=nearest):
                with patch('utils.recognition.find_nearest_user', return_value=nearest):
                    self.assertEqual(match_embedding([0.0]), expected)

    def test_adaptive_mode_stops_after_enough_frames(self):
        source = FakeObservationSource(available=7)
        with patch('utils.recognition.get_recognition_mode', return_value='adaptive'), \
                patch('utils.recognition.get_adaptive_recognition_config',
                      return_value=ADAPTIVE_SETTINGS), \
                patch('utils.recognition.get_embeddings_from_frame',
                      return_value=[[1.0]]) as embed, \
                patch('utils.recognition.match_embedding', return_value=(1, 0.10)):
            result = recognize_face_from_camera(source, deadline=100.0)

        self.assertTrue(result[0])
        self.assertEqual(embed.call_count, 5)
        self.assertEqual(source.used, 5)
        self.assertEqual(source.next_calls, 1)

    def test_adaptive_mode_limits_attempt_duration(self):
        source = FakeObservationSource(available=7, step=1.0)
        with patch('utils.recognition.get_recognition_mode', return_value='adaptive'), \
                patch('utils.recognition.get_adaptive_recognition_config',
                      return_value=ADAPTIVE_SETTINGS), \
                patch('utils.recognition.get_embeddings_from_frame',
                      return_value=[[1.0]]) as embed, \
                patch('utils.recognition.match_embedding', return_value=(None, None)):
            result = recognize_face_from_camera(source, deadline=100.0)

        self.assertFalse(result[0])
        self.assertEqual(embed.call_count, 3)
        self.assertEqual(source.next_calls, 0)

    def test_fixed_mode_consumes_configured_frames(self):
        source = FakeObservationSource(available=7)
        with patch('utils.recognition.get_recognition_mode', return_value='fixed'), \
                patch('utils.recognition.get_embeddings_from_frame',
                      return_value=[[1.0]]) as embed, \
                patch('utils.recognition.recognize_face_from_embeddings_series',
                      return_value=(True, 1, 0.1)) as score:
            result = recognize_face_from_camera(source, deadline=100.0)

        self.assertTrue(result[0])
        self.assertEqual(embed.call_count, 5)
        self.assertEqual(score.call_count, 1)
        self.assertEqual(len(score.call_args.args[0]), 5)

    def test_adaptive_mode_rejects_track_after_database(self):
        source = FakeObservationSource(available=7)
        source.next = Mock(side_effect=ObservationRejected('face_lost'))
        with patch('utils.recognition.get_recognition_mode', return_value='adaptive'), \
                patch('utils.recognition.get_adaptive_recognition_config',
                      return_value=ADAPTIVE_SETTINGS), \
                patch('utils.recognition.get_embeddings_from_frame',
                      return_value=[[1.0]]), \
                patch('utils.recognition.match_embedding', return_value=(1, 0.10)):
            with self.assertRaisesRegex(ObservationRejected, 'face_lost'):
                recognize_face_from_camera(source, deadline=100.0)


if __name__ == '__main__':
    unittest.main()
