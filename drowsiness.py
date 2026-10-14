"""Time-based observation rules, independent of camera and alarm transport."""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RiskConfig:
    eye_closed_seconds: float = 1.5
    tilt_angle: float = 10.0
    tilt_seconds: float = .8  # Legacy configuration; static tilt never sounds the alarm.
    nod_enter: float = 4.0
    nod_exit: float = 2.0
    nod_min: float = .03
    nod_max: float = 4.0
    head_drop_angle: float = 10.0
    head_rest_angle: float = 5.0
    head_hold_seconds: float = .75
    jerk_speed: float = 60.0
    lateral_drop_angle: float = 15.0
    lateral_return_angle: float = 8.0
    lateral_min_seconds: float = .2
    lateral_max_seconds: float = 2.5
    lateral_baseline_seconds: float = .5
    lateral_baseline_spread: float = 3.0
    head_max_yaw: float = 35.0
    head_yaw_change: float = 10.0
    max_gap: float = .2

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in vars(self).values()):
            raise ValueError('Risk thresholds must be finite and positive')
        if not 1 <= self.eye_closed_seconds <= 2:
            raise ValueError('Eye closure threshold must be between 1 and 2 seconds')
        if not self.nod_exit < self.nod_enter or self.nod_min > self.nod_max:
            raise ValueError('Invalid nod thresholds')
        if not self.head_rest_angle < self.head_drop_angle:
            raise ValueError('Head rest angle must be below drop angle')
        if not self.lateral_return_angle < self.lateral_drop_angle:
            raise ValueError('Lateral return angle must be below drop angle')
        if self.lateral_min_seconds > self.lateral_max_seconds:
            raise ValueError('Invalid lateral duration range')


class MouthObservation:
    """Immediate visible-mouth state; no yawn timing, counting or diagnosis."""
    def __init__(self):
        self.state = None

    def update(self, t, row):
        state = ('CALIBRATING' if row.get('phase') != 'TRACKING' else 'UNKNOWN'
                 if not row.get('mouth_valid') else row.get('mouth_state', 'UNKNOWN'))
        events = []
        if state != self.state:
            events.append(dict(channel='mouth', kind='mouth_observation', state=state,
                               mar=row.get('mar_simple'), eye_state=row.get('eye_state'), end_s=t))
        self.state = state
        return dict(state=state, events=events)


class HeadCycle:
    """Observe rest then drop; forward drops may alert before return."""
    def __init__(self, config, lateral=False):
        self.cfg, self.lateral = config, lateral
        self.reset()

    def reset(self):
        self.baseline = None
        self.samples = deque()
        self.start = self.start_yaw = self.held_since = None
        self.held = self.jerk = False
        self.drop_duration = 0.
        self.hold_active = False
        self.block_reason = 'waiting_for_rest'
        self.side = 1

    def _rest(self, t, value, yaw):
        cfg = self.cfg
        if not self.lateral:
            if value <= cfg.head_rest_angle:
                self.baseline = 0.
                self.block_reason = 'rest_observed'
            return
        self.samples.append((t, value, yaw))
        # Keep the sample immediately before the window boundary as well.
        while len(self.samples) > 1 and self.samples[1][0] <= t - cfg.lateral_baseline_seconds:
            self.samples.popleft()
        values = [s[1] for s in self.samples]
        yaws = [s[2] for s in self.samples]
        if (t - self.samples[0][0] + 1e-9 >= cfg.lateral_baseline_seconds
                and max(values) - min(values) <= cfg.lateral_baseline_spread
                and max(yaws) - min(yaws) <= cfg.head_yaw_change):
            self.baseline = sum(values) / len(values)
            self.block_reason = 'rest_observed'

    def update(self, t, value, yaw, velocity):
        cfg = self.cfg
        enter = cfg.lateral_drop_angle if self.lateral else cfg.head_drop_angle
        leave = cfg.lateral_return_angle if self.lateral else cfg.head_rest_angle
        self.hold_active = False
        if self.baseline is None:
            self._rest(t, value, yaw)
            return False
        delta = value - self.baseline
        if self.start is None:
            drop = abs(delta) if self.lateral else delta
            if drop >= enter:
                self.start, self.start_yaw, self.held_since = t, yaw, t
                self.side = -1 if self.lateral and delta < 0 else 1
                self.samples.clear()
                self.block_reason = 'drop_too_short'
            else:
                self._rest(t, value, yaw)
            return False
        if abs(yaw - self.start_yaw) > cfg.head_yaw_change:
            self.reset()
            self.block_reason = 'yaw_changed'
            # Rest must be reacquired on subsequent valid samples.
            return False
        if self.side * delta >= enter:
            if self.held_since is None:
                self.held_since = t
            self.drop_duration = t - self.held_since
            if t - self.held_since + 1e-9 >= (cfg.lateral_min_seconds if self.lateral else cfg.nod_min):
                self.held = True
            if not self.lateral and self.drop_duration + 1e-9 >= cfg.head_hold_seconds:
                self.hold_active = True
        else:
            self.held_since = None
            self.drop_duration = 0.
        if (self.held and velocity is not None and math.isfinite(velocity)
                and self.side * velocity <= -cfg.jerk_speed):
            self.jerk = True
        returned = abs(delta) <= leave if self.lateral else delta <= leave
        if returned:
            event = self.lateral and self.held and self.jerk
            self.reset()
            self._rest(t, value, yaw)
            return event
        if t - self.start > (cfg.lateral_max_seconds if self.lateral else cfg.nod_max) and (self.lateral or not self.hold_active):
            self.reset()
            self.block_reason = 'cycle_timeout'
            return False
        self.block_reason = ('held_drop' if self.hold_active else 'waiting_for_return' if self.held
                             else 'drop_too_short')
        # Crossing completely through rest without observing it is not a return.
        if self.lateral and self.side * delta < -leave:
            self.reset()
        return False


class NodCandidateGate:
    """Check observation quality of completed source events, not their motion again."""
    def __init__(self, config):
        self.cfg = config
        self.samples = deque()
        self.last_consumed_start = float('-inf')

    def update(self, t, row, events):
        yaw = row.get('yaw_deg')
        valid = bool(row.get('pose_valid')) and all(
            v is not None and math.isfinite(v) for v in (yaw, row.get('pitch_deg'), row.get('roll_deg')))
        self.samples.append((t, valid, yaw))
        while self.samples and self.samples[0][0] < t - self.cfg.nod_max - self.cfg.max_gap:
            self.samples.popleft()
        decisions = []
        for event in events:
            if event.get('kind') != 'nod_candidate':
                continue
            start, end, duration = (event.get(k) for k in ('start_s', 'end_s', 'duration_s'))
            reason = 'accepted'
            if not event.get('start_known'):
                reason = 'unknown_onset'
            elif not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end, duration)):
                reason = 'invalid_event'
            elif start <= self.last_consumed_start:
                reason = 'duplicate_event'
            else:
                self.last_consumed_start = start
                samples = [s for s in self.samples if start - 1e-6 <= s[0] <= end + 1e-6]
                if not (self.cfg.nod_min - 1e-9 <= duration <= self.cfg.nod_max + 1e-9) or abs(end-start-duration) > 1e-6:
                    reason = 'invalid_duration'
                elif (not samples or abs(samples[0][0]-start) > 1e-6
                      or abs(samples[-1][0]-end) > 1e-6 or abs(end-t) > 1e-6):
                    reason = 'incomplete_observation'
                elif any(b[0]-a[0] > self.cfg.max_gap for a, b in zip(samples, samples[1:])):
                    reason = 'frame_gap'
                elif not all(s[1] for s in samples):
                    reason = 'invalid_pose'
                elif any(abs(s[2]) > self.cfg.head_max_yaw for s in samples):
                    reason = 'yaw_out_of_range'
                elif any(abs(s[2]-samples[0][2]) > self.cfg.head_yaw_change for s in samples):
                    reason = 'yaw_changed'
            decisions.append(dict(channel='head', kind='nod_alert_accepted' if reason == 'accepted' else 'nod_alert_rejected',
                                  start_s=start, end_s=end, reason=reason))
        return decisions


class RiskEvaluator:
    def __init__(self, config=RiskConfig()):
        self.config = config
        self.yawns = deque()
        self.last_t = None
        self.tilt_start = self.tilt_side = None
        self.forward = HeadCycle(config)
        self.lateral = HeadCycle(config, lateral=True)
        self.previous_roll = None
        self.head_alerts = {}
        self.was_yawn_high = False
        self.nod_gate = NodCandidateGate(config)
        self.nod_feedback = None

    def interrupt(self):
        self.tilt_start = self.tilt_side = None
        self.forward.reset()
        self.lateral.reset()
        self.previous_roll = None
        self.head_alerts.clear()

    def update(self, t, row, events=()):
        if not math.isfinite(t) or (self.last_t is not None and t <= self.last_t):
            raise ValueError('Timestamps must increase strictly')
        cfg = self.config
        if self.last_t is not None and t - self.last_t > cfg.max_gap:
            self.interrupt()
        previous_t = self.last_t
        self.last_t = t
        if row.get('phase') != 'TRACKING':
            self.interrupt()
            self.yawns.clear()
            self.was_yawn_high = False
            self.nod_gate = NodCandidateGate(cfg)
            self.nod_feedback = None
            return dict(level='CALIBRATING', reasons=[], yawn_count=0,
                        tilt_duration=0., tilt_band='UNKNOWN', urgent=False,
                        yawn_reminder=False, nod_event=False, forward_nod_event=False,
                        lateral_nod_event=False, head_motion='CALIBRATING', head_drop_duration=0.,
                        head_block_reason='calibrating', roll_velocity_deg_s=None,
                        nod_alert_reason='calibrating', nod_decisions=[], alarm_active=False,
                        alarm_reasons=[], observation_reasons=[], frequent_yawns_event=False)
        decisions = self.nod_gate.update(t, row, events)
        if decisions:
            self.nod_feedback = (t, decisions[-1]['reason'])
        high = reminder = False
        reasons = []
        duration = row.get('eye_observed_closed_s')
        if (row.get('eyes_valid') and row.get('eye_state') == 'CLOSED'
                and duration is not None and duration >= cfg.eye_closed_seconds):
            reasons.append('suspected_sleep_eye_closure')
        pose = bool(row.get('pose_valid'))
        roll, pitch, yaw = row.get('roll_deg'), row.get('pitch_deg'), row.get('yaw_deg')
        pose = pose and all(v is not None and math.isfinite(v) for v in (roll, pitch, yaw))
        tilt_band, tilt_duration = 'UNKNOWN', 0.
        forward_event = any(d['kind'] == 'nod_alert_accepted' for d in decisions)
        lateral_event = False
        head_motion = 'UNKNOWN'
        roll_velocity = None
        if pose:
            magnitude = abs(roll)
            tilt_band = 'STRAIGHT' if magnitude <= 5 else 'LEANING' if magnitude < cfg.tilt_angle else 'TILTED'
            side = 1 if roll >= 0 else -1
            if magnitude >= cfg.tilt_angle:
                if self.tilt_start is None or side != self.tilt_side:
                    self.tilt_start, self.tilt_side = t, side
                tilt_duration = t - self.tilt_start
            else:
                self.tilt_start = self.tilt_side = None
            if abs(yaw) <= cfg.head_max_yaw:
                roll_velocity = ((roll - self.previous_roll) / (t - previous_t)
                                 if self.previous_roll is not None and previous_t is not None else None)
                self.forward.update(t, pitch, yaw, row.get('pitch_velocity_deg_s'))
                lateral_event = self.lateral.update(t, roll, yaw, roll_velocity)
                self.previous_roll = roll
                head_motion = 'DROPPING' if self.forward.start is not None or self.lateral.start is not None else 'REST'
                for event, reason in ((forward_event, 'forward_head_bob'), (lateral_event, 'lateral_head_bob')):
                    if event:
                        self.head_alerts[reason] = t + 3.
                self.head_alerts = {reason: end for reason, end in self.head_alerts.items() if t < end}
                if self.forward.hold_active:
                    reasons.append('forward_head_drop')
                    head_motion = 'HELD_DROP'
                if forward_event or lateral_event:
                    head_motion = 'NODDING CONFIRMED' if forward_event else 'BOB_CONFIRMED'
            else:
                self.forward.reset()
                self.lateral.reset()
                self.previous_roll = None
                self.head_alerts.clear()
                head_motion = 'LOOKING_ASIDE'
        else:
            self.interrupt()
        if decisions and not forward_event:
            head_motion = 'NODDING REJECTED'
        feedback = self.nod_feedback[1] if self.nod_feedback and t-self.nod_feedback[0] < 3 else ''
        if 'forward_head_bob' in self.head_alerts and not self.forward.hold_active:
            head_motion = 'NODDING CONFIRMED'
        elif feedback and feedback != 'accepted' and head_motion == 'REST':
            head_motion = 'NODDING REJECTED'
        urgent = bool(reasons)
        observation_reasons = list(self.head_alerts)
        if high:
            observation_reasons.append('frequent_yawns')
        observed = bool(row.get('eyes_valid') or row.get('mouth_valid') or pose)
        level = 'DANGER' if urgent else 'NORMAL' if observed else 'UNKNOWN'
        return dict(level=level, reasons=reasons, yawn_count=len(self.yawns),
                    tilt_duration=tilt_duration, tilt_band=tilt_band, urgent=urgent,
                    yawn_reminder=False, frequent_yawns_event=reminder,
                    alarm_active=urgent, alarm_reasons=list(reasons), observation_reasons=observation_reasons,
                    nod_event=forward_event or lateral_event,
                    forward_nod_event=forward_event, lateral_nod_event=lateral_event,
                    head_motion=head_motion, head_drop_duration=self.forward.drop_duration,
                    roll_velocity_deg_s=roll_velocity,
                    nod_decisions=decisions, nod_alert_reason=feedback,
                    head_block_reason=('invalid_pose' if not pose else 'yaw_out_of_range'
                                       if abs(yaw) > cfg.head_max_yaw else self.forward.block_reason))
