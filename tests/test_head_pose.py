"""Поза на синтетических проекциях, не проверка точности на людях"""

import unittest

import cv2
import numpy as np

from utils.face.head_pose import FACE_MODEL, estimate_head_pose


class HeadPoseTests(unittest.TestCase):
    def test_known_yaw_and_missing_points(self):
        camera = np.array([[640., 0, 320], [0, 640, 240], [0, 0, 1]])
        for yaw in (-25, 0, 25):
            points, _ = cv2.projectPoints(FACE_MODEL, np.array([0., np.deg2rad(yaw), 0.]),
                                          np.array([0., 0., 600.]), camera, np.zeros(5))
            points = points[:, 0]
            face = dict(nose_tip=[points[0]] * 5, chin=[points[1]] * 17,
                        left_eye=[points[2]] * 6, right_eye=[points[3]] * 6,
                        top_lip=[points[4]] * 6 + [points[5]] * 6)
            pose = estimate_head_pose(face, (640, 480))
            self.assertEqual(pose['status'], 'estimated')
            self.assertAlmostEqual(pose['yaw_deg'], yaw, places=3)
            self.assertFalse(pose['calibrated'])
            self.assertFalse(pose['ground_truth'])
        self.assertEqual(estimate_head_pose({}, (640, 480))['status'], 'not_measurable')
