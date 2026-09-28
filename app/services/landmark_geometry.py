"""Dimensionless measurements from MediaPipe's pixel-coordinate landmarks."""
import numpy as np

LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)


def _points(points):
    if points is None:
        return None
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < 468 or values.shape[1] < 2 or not np.isfinite(values).all():
        return None
    return values[:, :2]


def eye_ratios(points):
    points = _points(points)
    if points is None:
        return None
    ratios = []
    for indices in (LEFT_EYE, RIGHT_EYE):
        p = points[list(indices)]
        width = float(np.linalg.norm(p[0] - p[3]))
        if width < 4:
            return None
        ratio = float((np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])) / (2 * width))
        if not 0 <= ratio <= 1:
            return None
        ratios.append(ratio)
    return tuple(ratios)


def mouth_ratio(points):
    points = _points(points)
    if points is None:
        return None
    width = float(np.linalg.norm(points[78] - points[308]))
    if width < 8:
        return None
    ratio = float(np.linalg.norm(points[13] - points[14]) / width)
    return ratio if 0 <= ratio <= 1 else None
