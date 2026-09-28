"""Task 10 runtime, cache, and concurrency checks. No real database writes."""
import hashlib
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Config
from app.services import face_detector as faces, landmarks


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask('landmark-runtime')
        self.app.config.from_object(Config)
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        self.addCleanup(landmarks.close)

    def test_real_offline_model_and_reuse(self):
        image = np.zeros((128, 128, 3), dtype=np.uint8)
        reason, result = landmarks.measure_clip([(0, image), (50, image)])
        self.assertIsNone(reason)
        self.assertEqual([r.reason for r in result], ['no_landmarks', 'no_landmarks'])
        model = landmarks._model
        self.assertIsNone(landmarks.measure_clip([(0, image)])[0])
        self.assertIs(landmarks._model, model)
        portrait = ROOT / '.runtime/fixtures/portrait.jpg'
        if portrait.is_file():
            reason, result = landmarks.measure_clip([(0, cv2.imread(str(portrait)))])
            self.assertIsNone(reason)
            self.assertIsNone(result[0].reason)
            self.assertEqual(result[0].points.shape, (478, 3))
            self.assertFalse(result[0].points.flags.writeable)

    def test_missing_and_tampered_model(self):
        with tempfile.TemporaryDirectory(prefix='authx-model-') as temp:
            path = Path(temp) / 'bad.task'
            with patch.dict(self.app.config, LANDMARK_PATH=path):
                self.assertEqual(landmarks.measure_clip([])[0], 'landmark_model_missing')
                path.write_bytes(b'wrong-model')
                self.assertEqual(landmarks.measure_clip([])[0], 'landmark_model_invalid')
            self.assertEqual(hashlib.sha256(Config.LANDMARK_PATH.read_bytes()).hexdigest(), Config.LANDMARK_SHA256)

    def test_landmarks_serialize_parallel_captures(self):
        active = maximum = 0
        def detect(image):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(.005)
            active -= 1
            return Mock(face_landmarks=[])
        model = Mock(detect=detect)
        def worker(_):
            with self.app.app_context():
                return landmarks.measure_clip([(0, np.zeros((64, 64, 3), dtype=np.uint8))])
        with patch.object(landmarks, '_load', return_value=(None, model)), ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(worker, range(8)))
        self.assertTrue(all(r[0] is None for r in results))
        self.assertEqual(maximum, 1)

    def test_yunet_detection_cache_is_scoring_local(self):
        image = np.zeros((128, 128, 3), dtype=np.uint8)
        face = np.array([[0, 0, 128, 128] + [40] * 10 + [.8]], dtype=np.float32)
        with patch.object(faces, '_detect_all_faces', return_value=(None, face)) as detect:
            with faces.detection_cache():
                faces.detect_all_faces(image)
                faces.detect_faces(image)
                faces.detect_all_faces(image)
                self.assertEqual(detect.call_count, 1)
            with faces.detection_cache():
                faces.detect_all_faces(image)
            self.assertEqual(detect.call_count, 2)
        self.assertIsNone(faces._detections.get())

    def test_shared_sface_serializes_align_and_feature(self):
        active = maximum = 0
        def align(image, row):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(.005)
            return image
        def feature(image):
            nonlocal active
            active -= 1
            return np.ones((1, 128))
        model = Mock(alignCrop=align, feature=feature)
        def worker(_):
            with self.app.app_context():
                return faces.embed_row(np.zeros((64, 64, 3), dtype=np.uint8), np.ones(15))
        with patch.object(faces, '_sface', return_value=model), ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(worker, range(8)))
        self.assertEqual(maximum, 1)

    def test_yunet_reuses_model_with_locked_size_and_threshold(self):
        detector = Mock()
        with patch.object(faces, '_detector', None), patch.object(faces, '_detector_key', None), \
                patch.object(cv2.FaceDetectorYN, 'create', return_value=detector) as create:
            with faces._model_lock:
                faces._yunet(128, 128, .6)
                faces._yunet(640, 480, .4)
            create.assert_called_once()
            detector.setInputSize.assert_called_with((640, 480))
            detector.setScoreThreshold.assert_called_with(.4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
