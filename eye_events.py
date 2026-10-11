"""EAR và máy trạng thái mắt. Không phụ thuộc camera hay MediaPipe.

Các ngưỡng thời gian là tham số thử nghiệm, không phải tiêu chuẩn chẩn đoán.
"""
from dataclasses import dataclass, asdict
import math


def eye_aspect_ratio(points, indices):
    """points phải là tọa độ pixel, không dùng trực tiếp x/y chuẩn hóa."""
    p = [points[i] for i in indices]
    if not all(math.isfinite(float(v)) for pair in p for v in pair):
        return None
    width = math.dist(p[0], p[3])
    if width <= 0:
        return None
    return (math.dist(p[1], p[5]) + math.dist(p[2], p[4])) / (2 * width)


@dataclass
class EyeConfig:
    left_close: float
    left_open: float
    right_close: float
    right_open: float
    blink_min_s: float = 0.06
    blink_max_s: float = 0.50
    long_closure_s: float = 1.50
    max_gap_s: float = 0.20
    max_disagreement_s: float = 0.12

    def __post_init__(self):
        for value in asdict(self).values():
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Tham số phải hữu hạn và > 0')
        if not (self.left_close < self.left_open and self.right_close < self.right_open):
            raise ValueError('Ngưỡng đóng phải nhỏ hơn ngưỡng mở')
        if not self.blink_min_s < self.blink_max_s < self.long_closure_s:
            raise ValueError('Cần blink_min < blink_max < long_closure')


class EyeTracker:
    """Đếm sự kiện hai mắt đóng/mở; mất quan sát ngắt sự kiện ngay.

    Cần quan sát OPEN trước CLOSED để biết mốc bắt đầu. Khi mới lấy lại
    mặt mà mắt đã nhắm, không đoán thời điểm bắt đầu nhắm.
    """
    def __init__(self, config):
        self.config = config
        self.left = self.right = self.state = 'UNKNOWN'
        self.last_t = None
        self.start = None
        self.long_sent = False
        self.armed = False
        self.disagreement_since = None
        self.last_closed_t = None

    @staticmethod
    def classify(value, previous, close, reopen):
        if value <= close:
            return 'CLOSED'
        if value >= reopen:
            return 'OPEN'
        return previous  # Hysteresis: giữ trạng thái trong vùng giữa ngưỡng.

    def interrupt(self, t, reason):
        events = []
        if self.start is not None:
            # Dùng mốc quan sát hợp lệ cuối, không cộng thời gian bị mất.
            end = self.last_closed_t if self.last_closed_t is not None else self.start
            events.append(dict(kind='interrupted_closure', start_s=self.start,
                               end_s=end, duration_s=max(0, end-self.start), reason=reason))
        self.start = None
        self.long_sent = False
        self.armed = False
        self.disagreement_since = None
        self.last_closed_t = None
        self.left = self.right = self.state = 'UNKNOWN'
        return events

    def update(self, t, left_ear, right_ear, valid=True, reason='invalid_eyes'):
        if not math.isfinite(t) or (self.last_t is not None and t <= self.last_t):
            raise ValueError('Timestamp phải hữu hạn và tăng nghiêm ngặt')
        events = []
        if self.last_t is not None and t-self.last_t > self.config.max_gap_s:
            events += self.interrupt(t, 'frame_gap')
        good = valid and all(v is not None and math.isfinite(v) and v >= 0
                             for v in (left_ear, right_ear))
        if not good:
            events += self.interrupt(t, reason)
        else:
            cfg = self.config
            if self.disagreement_since is not None and t-self.disagreement_since > cfg.max_disagreement_s:
                events += self.interrupt(t, 'eyes_disagree_timeout')
            self.left = self.classify(left_ear, self.left, cfg.left_close, cfg.left_open)
            self.right = self.classify(right_ear, self.right, cfg.right_close, cfg.right_open)
            if self.left != self.right or self.left == 'UNKNOWN':
                # Mắt có thể vượt ngưỡng ở hai frame khác nhau. Giữ trạng thái
                # riêng và chờ ngắn khi dữ liệu hai mắt vẫn hợp lệ.
                self.state = 'UNKNOWN'
                if self.disagreement_since is None:
                    self.disagreement_since = t
            else:
                self.state = self.left
                if self.state == 'CLOSED' and self.start is None and self.armed:
                    self.start = t
                    self.long_sent = False
                elif self.state == 'OPEN' and self.start is not None:
                    # Kết thúc tại frame đầu một mắt mở, chỉ khi cả hai xác
                    # nhận OPEN trong khoảng chuyển tiếp cho phép.
                    end = self.disagreement_since if self.disagreement_since is not None else t
                    duration = end-self.start
                    kind = ('brief_closure' if duration < cfg.blink_min_s else
                            'blink_candidate' if duration <= cfg.blink_max_s else
                            'prolonged_closure')
                    events.append(dict(kind=kind, start_s=self.start, end_s=end,
                                       duration_s=duration, reason='reopened'))
                    self.start = None
                    self.long_sent = False
                    self.last_closed_t = None
                if self.state == 'OPEN':
                    self.armed = True
                elif self.state == 'CLOSED':
                    self.last_closed_t = t
                self.disagreement_since = None
                if self.start is not None and t-self.start >= cfg.long_closure_s and not self.long_sent:
                    events.append(dict(kind='long_closure_flag', start_s=self.start,
                                       end_s=t, duration_s=t-self.start,
                                       reason='observed_duration_threshold'))
                    self.long_sent = True
        self.last_t = t
        return dict(state=self.state, left_state=self.left, right_state=self.right,
                    closure_s=None if self.start is None or self.state != 'CLOSED' else t-self.start,
                    long_closure=self.long_sent and self.state == 'CLOSED', events=events)

    def finish(self):
        return self.interrupt(self.last_t or 0.0, 'run_ended')
