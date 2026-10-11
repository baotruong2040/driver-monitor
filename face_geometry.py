"""Kiểm tra hình học đơn giản của landmarks; chưa phân loại mắt/ngáp/buồn ngủ."""

from dataclasses import dataclass, field
import numpy as np


LEFT_EYE = (362, 385, 387, 263, 373, 380)
RIGHT_EYE = (33, 160, 158, 133, 153, 144)
MOUTH = (78, 191, 80, 81, 82, 13, 312, 311, 310, 415,
         308, 324, 318, 402, 317, 14, 87, 178, 88, 95)
HEAD_POINTS = (1, 10, 152, 234, 454)


@dataclass
class Geometry:
    state: str = "NO_FACE"
    points: np.ndarray | None = None
    widths: dict = field(default_factory=dict)
    valid: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)


def inspect_face(landmarks, width, height):
    if not landmarks:
        return Geometry()
    points = np.asarray([(point.x * width, point.y * height) for point in landmarks], dtype=float)
    result = Geometry("LIMITED_GEOMETRY", points)
    if len(points) < 468:
        result.reasons.append("too_few_landmarks")
        return result

    def inside(indices):
        region = points[list(indices)]
        return bool(np.isfinite(region).all() and
                    (region[:, 0] >= 0).all() and (region[:, 0] < width).all() and
                    (region[:, 1] >= 0).all() and (region[:, 1] < height).all())

    for name, indices, corners, minimum in (
        ("left_eye", LEFT_EYE, (362, 263), 14),
        ("right_eye", RIGHT_EYE, (33, 133), 14),
        ("mouth", MOUTH, (78, 308), 20),
    ):
        endpoints = points[list(corners)]
        distance = float(np.linalg.norm(endpoints[0] - endpoints[1])) if np.isfinite(endpoints).all() else None
        result.widths[name] = distance
        result.valid[name] = inside(indices) and distance is not None and distance >= minimum
        if not result.valid[name]:
            result.reasons.append(f"{name}_outside_or_small")
    result.valid["head"] = inside(HEAD_POINTS)
    if not result.valid["head"]:
        result.reasons.append("head_points_outside")
    if not np.isfinite(points).all():
        result.reasons.append("nonfinite_landmarks")
    if not result.reasons:
        result.state = "GEOMETRY_OK"
    return result


def draw_geometry(frame, geometry, cv2, full_mesh=False):
    if geometry.points is None:
        return
    height, width = frame.shape[:2]

    def visible(point):
        return np.isfinite(point).all() and 0 <= point[0] < width and 0 <= point[1] < height

    if full_mesh:
        for point in geometry.points:
            if visible(point):
                cv2.circle(frame, tuple(np.rint(point).astype(int)), 1, (150, 150, 150), -1)

    if len(geometry.points) < 468:
        return
    for indices, color in ((LEFT_EYE, (0, 255, 0)), (RIGHT_EYE, (255, 255, 0)),
                           (MOUTH, (0, 180, 255))):
        region = geometry.points[list(indices)]
        if all(visible(point) for point in region):
            contour = np.rint(region).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(frame, [contour], True, color, 1, cv2.LINE_AA)
        for point in region:
            if visible(point):
                cv2.circle(frame, tuple(np.rint(point).astype(int)), 2, color, -1)
    for index in HEAD_POINTS:
        point = geometry.points[index]
        if visible(point):
            xy = tuple(np.rint(point).astype(int))
            cv2.circle(frame, xy, 3, (255, 255, 255), -1)
            cv2.putText(frame, str(index), (xy[0] + 4, xy[1] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, .35, (255, 255, 255), 1)
