import unittest
from scripts.evaluate_authentication import summarize


class EvaluationTests(unittest.TestCase):
    def row(self, i, decision, *, genuine=True, user=None, detector='haar'):
        return dict(attempt_id=str(i), session_id=None if decision == 'NO_SESSION' else str(i),
                    detector=detector, genuine=genuine, decision=decision,
                    expected_user_id=7 if genuine else None, user_id=user,
                    reason='face_lost' if decision == 'DENIED' else '',
                    elapsed_seconds=2.0)

    def test_refusals_include_no_session_and_wrong_identity_is_separate(self):
        rows = [self.row(1,'GRANTED',user=7), self.row(2,'DENIED'),
                self.row(3,'NO_SESSION'), self.row(4,'GRANTED',user=8),
                self.row(5,'GRANTED',genuine=False,user=7),
                self.row(6,'ERROR',detector='yunet')]
        result = summarize(rows)
        self.assertEqual(result['haar']['frr_end_to_end'], .5)
        self.assertEqual(result['haar']['unsuccessful_correct_authentication_rate'], .75)
        self.assertEqual(result['haar']['false_accept_rate_non_genuine'], 1)
        self.assertEqual(result['yunet']['frr_end_to_end'], 1)

    def test_duplicate_attempt_is_rejected(self):
        row = self.row(1,'DENIED')
        with self.assertRaises(ValueError):
            summarize([row,row])
