"""Đặc trưng miệng/đầu và sự kiện theo thời gian; chưa phân loại buồn ngủ."""
from dataclasses import dataclass, asdict
import math
import numpy as np


def mouth_ratio(points):
    """MAR_simple: khoảng môi trong 13–14 / chiều rộng miệng 78–308, đơn vị pixel."""
    if points is None or len(points) <= 308:
        return None
    p = np.asarray(points)[[13, 14, 78, 308]]
    if not np.isfinite(p).all():
        return None
    width = float(np.linalg.norm(p[2]-p[3]))
    return float(np.linalg.norm(p[0]-p[1])/width) if width > 0 else None


def rotation_from_matrix(matrix):
    """Lấy rotation gần nhất bằng SVD; bỏ translation/scale, từ chối reflection."""
    if matrix is None:
        return None
    m = np.asarray(matrix, dtype=float)
    if m.shape != (4, 4) or not np.isfinite(m).all():
        return None
    a = m[:3, :3]
    if np.linalg.det(a) <= 0:
        return None
    u, s, vt = np.linalg.svd(a)
    if s[-1] < 1e-6 or s[0]/s[-1] > 1.5:
        return None
    r = u @ vt
    return r if np.linalg.det(r) > 0 else None


def mean_rotation(rotations):
    u, _, vt = np.linalg.svd(np.mean(rotations, axis=0))
    d = np.eye(3)
    d[2, 2] = np.linalg.det(u @ vt)
    return u @ d @ vt


def euler_degrees(rotation):
    """R = Rz(roll) Ry(yaw) Rx(pitch). Trả (pitch,yaw,roll), không dùng gần gimbal lock."""
    r = np.asarray(rotation)
    yaw = math.asin(float(np.clip(-r[2, 0], -1, 1)))
    if abs(math.cos(yaw)) < 1e-3:
        return None
    pitch = math.atan2(r[2, 1], r[2, 2])
    roll = math.atan2(r[1, 0], r[0, 0])
    return tuple(math.degrees(x) for x in (pitch, yaw, roll))


def relative_angles(rotation, neutral, pitch_sign=1):
    # Delta trong hệ trục camera, không trừ trực tiếp các góc Euler tuyệt đối.
    angles = euler_degrees(rotation @ neutral.T)
    if angles is None:
        return None
    return (pitch_sign*angles[0], angles[1], angles[2])


class AngleFilter:
    def __init__(self, tau=.15, max_gap=.2):
        self.tau, self.max_gap = tau, max_gap
        self.last_t = self.value = None

    def update(self, t, angles):
        if angles is None:
            self.last_t = self.value = None
            return None, None
        new = np.asarray(angles, dtype=float)
        velocity = None
        if self.last_t is not None and 0 < t-self.last_t <= self.max_gap:
            dt = t-self.last_t
            alpha = 1-math.exp(-dt/self.tau)
            new = self.value + alpha*(new-self.value)
            velocity = float((new[0]-self.value[0])/dt)
        self.last_t, self.value = t, new
        return tuple(float(x) for x in new), velocity


@dataclass
class DurationConfig:
    channel: str
    enter: float
    exit: float
    min_duration: float
    max_candidate_duration: float
    flag_duration: float
    max_gap: float = .2

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key != 'channel' and (not math.isfinite(value) or value < 0):
                raise ValueError('Tham số sự kiện phải hữu hạn và không âm')
        if not self.enter > self.exit >= 0:
            raise ValueError('Cần enter > exit >= 0')
        if not 0 < self.min_duration <= self.max_candidate_duration:
            raise ValueError('Khoảng thời lượng ứng viên không hợp lệ')
        if self.flag_duration <= 0 or self.max_gap <= 0 or self.channel not in ('mouth', 'head'):
            raise ValueError('Channel hoặc thời gian không hợp lệ')


class DurationTracker:
    """Sự kiện mở miệng/cúi đầu. Giữ tách mốc bắt đầu biết được và đoạn quan sát."""
    def __init__(self, config):
        self.config = config
        self.state = 'UNKNOWN'
        self.last_t = self.start = None
        self.start_known = False
        self.flag_sent = False
        self.peak = None

    def event(self, kind, end, reason):
        return dict(channel=self.config.channel, kind=kind, start_s=self.start,
                    end_s=end, duration_s=max(0, end-self.start),
                    start_known=int(self.start_known), peak=self.peak, reason=reason)

    def interrupt(self, reason):
        events = []
        if self.start is not None:
            events.append(self.event('interrupted_'+self.config.channel,
                                     self.last_t if self.last_t is not None else self.start, reason))
        self.state = 'UNKNOWN'
        self.start = self.peak = None
        self.flag_sent = self.start_known = False
        return events

    def update(self, t, value, valid=True, reason='invalid_observation'):
        if not math.isfinite(t) or (self.last_t is not None and t <= self.last_t):
            raise ValueError('Timestamp phải tăng nghiêm ngặt')
        cfg = self.config
        events = []
        if self.last_t is not None and t-self.last_t > cfg.max_gap:
            events += self.interrupt('source_gap')
        if not valid or value is None or not math.isfinite(value):
            events += self.interrupt(reason)
        else:
            previous = self.state
            if value >= cfg.enter:
                self.state = 'ACTIVE'
            elif value <= cfg.exit:
                self.state = 'REST'
            if self.state == 'ACTIVE':
                if self.start is None:
                    self.start = t
                    self.start_known = previous == 'REST'
                    self.peak = value
                    self.flag_sent = False
                self.peak = max(self.peak, value)
                if t-self.start >= cfg.flag_duration and not self.flag_sent:
                    events.append(self.event(cfg.channel+'_held_flag', t, 'observed_duration'))
                    self.flag_sent = True
            elif self.state == 'REST' and self.start is not None:
                duration = t-self.start
                if not self.start_known:
                    kind = 'observed_'+cfg.channel+'_segment'
                elif cfg.min_duration <= duration <= cfg.max_candidate_duration:
                    kind = 'yawn_candidate' if cfg.channel == 'mouth' else 'nod_candidate'
                else:
                    kind = 'mouth_open_event' if cfg.channel == 'mouth' else 'head_down_event'
                events.append(self.event(kind, t, 'returned'))
                self.start = self.peak = None
                self.flag_sent = self.start_known = False
        self.last_t = t
        return dict(state=self.state, duration_s=None if self.start is None else t-self.start,
                    start_known=int(self.start_known), held_flag=self.flag_sent, events=events)

    def finish(self, reason='run_ended'):
        return self.interrupt(reason)


class NeutralCalibration:
    def __init__(self, seconds=8):
        self.seconds = seconds
        self.valid_seconds = 0.0
        self.last_valid_t = None
        self.samples = []

    def add(self, t, left, right, mar, rotation, valid, max_gap=.2):
        if not valid:
            self.last_valid_t = None
            return False
        if self.last_valid_t is not None and 0 < t-self.last_valid_t <= max_gap:
            self.valid_seconds += t-self.last_valid_t
        self.last_valid_t = t
        self.samples.append((left, right, mar, rotation))
        return self.valid_seconds >= self.seconds and len(self.samples) >= 60

    def result(self):
        numeric = np.asarray([s[:3] for s in self.samples])
        r = mean_rotation([s[3] for s in self.samples])
        spread = [np.linalg.norm(euler_degrees(s[3] @ r.T)) for s in self.samples
                  if euler_degrees(s[3] @ r.T) is not None]
        if not spread or np.percentile(spread, 90) > 8:
            raise ValueError('Đầu chuyển động nhiều khi hiệu chỉnh. Chạy lại và giữ nhìn thẳng.')
        return dict(left_baseline=float(np.percentile(numeric[:, 0], 70)),
                    right_baseline=float(np.percentile(numeric[:, 1], 70)),
                    mouth_baseline=float(np.percentile(numeric[:, 2], 30)),
                    neutral_rotation=r, head_spread_p90=float(np.percentile(spread, 90)))
