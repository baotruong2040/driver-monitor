"""Synthetic time-series and transport tests for the live app."""
from dataclasses import replace
import threading
import time
import unittest
import contextlib
import io
from unittest.mock import patch

from app import arguments, update_observation
from behavior_features import DurationConfig, DurationTracker
from face_geometry import Geometry, LEFT_EYE, RIGHT_EYE
from check_behavior import Processor
from drowsiness import RiskConfig, RiskEvaluator, MouthObservation
from live_io import AlarmController, AlarmPattern, LatestCamera
from usb_alarm import USBAlarm


def observation(**changes):
    row = dict(phase='TRACKING', eyes_valid=1, eye_state='OPEN',
               eye_observed_closed_s=None, mouth_valid=1, pose_valid=1,
               pitch_deg=0., roll_deg=0., yaw_deg=0., pitch_velocity_deg_s=0.)
    row.update(changes)
    return row


def nod_candidate(start, end, **changes):
    event = dict(channel='head', kind='nod_candidate', start_known=1,
                 start_s=start, end_s=end, duration_s=end-start)
    event.update(changes)
    return event


class RiskTests(unittest.TestCase):
    def test_new_hold_threshold_and_sensitive_nod(self):
        risk = RiskEvaluator()
        risk.update(0., observation())
        for i in range(16):
            t = .1+i*.05
            result = risk.update(t, observation(pitch_deg=10.))
            self.assertEqual(result['alarm_active'], i == 15)
        self.assertIn('forward_head_drop', result['alarm_reasons'])
        source = DurationTracker(DurationConfig('head', 10, 5, .1, 2.5, .75))
        risk = RiskEvaluator()
        for t, pitch in [(0., 0.), (.1, 11.), (.2, 7.), (.3, 4.)]:
            result = risk.update(t, observation(pitch_deg=pitch), source.update(t, pitch)['events'])
        self.assertTrue(result['nod_event'])
        self.assertFalse(result['alarm_active'])

    def test_yawning_observations_do_not_mask_eye_alarm(self):
        risk = RiskEvaluator()
        for i in range(4):
            result = risk.update(i*.1, observation(), [dict(kind='yawn_confirmed')])
        self.assertEqual(result['yawn_count'], 0)
        self.assertFalse(result['alarm_active'])
        result = risk.update(.4, observation(eye_state='CLOSED', eye_observed_closed_s=1.5))
        self.assertTrue(result['alarm_active'])
        self.assertEqual(result['alarm_reasons'], ['suspected_sleep_eye_closure'])
        self.assertNotIn('frequent_yawns', result['observation_reasons'])

    def test_source_hysteresis_nod_alerts_without_second_motion_check(self):
        risk = RiskEvaluator()
        source = DurationTracker(DurationConfig('head', 15, 8, .2, 2.5, 1))
        result = None
        for t, pitch in [(0., 0.), (.1, 20.), (.2, 12.), (.3, 10.), (.4, 7.)]:
            events = source.update(t, pitch)['events']
            result = risk.update(t, observation(pitch_deg=pitch, pitch_velocity_deg_s=-20), events)
        self.assertTrue(result['forward_nod_event'])
        self.assertEqual(result['nod_alert_reason'], 'accepted')
        pattern = AlarmPattern()
        pattern.publish(.4, result)
        self.assertFalse(pattern.active(.4))
        self.assertEqual(risk.update(.5, observation())['head_motion'], 'NODDING CONFIRMED')

    def test_nod_candidate_quality_rejections_and_deduplication(self):
        cases = [('unknown_onset', dict(start_known=0), {}),
                 ('invalid_duration', {}, {}, .025),
                 ('invalid_pose', {}, dict(pose_valid=0)),
                 ('yaw_out_of_range', {}, dict(yaw_deg=40)),
                 ('yaw_changed', {}, dict(yaw_deg=15))]
        for case in cases:
            reason, event_changes, row_changes, *duration = case
            end = duration[0] if duration else .4
            risk = RiskEvaluator()
            risk.update(0., observation(pitch_deg=20))
            for i in range(1, round(end/.1)):
                risk.update(i*.1, observation(pitch_deg=12, **row_changes))
            result = risk.update(end, observation(), [nod_candidate(0, end, **event_changes)])
            self.assertFalse(result['forward_nod_event'])
            self.assertEqual(result['nod_alert_reason'], reason)
        risk = RiskEvaluator()
        risk.update(0, observation())
        for t in (.1, .2, .3):
            risk.update(t, observation(pitch_deg=12))
        event = nod_candidate(0, .4)
        self.assertTrue(risk.update(.4, observation(), [event])['nod_event'])
        self.assertFalse(risk.update(.5, observation(), [event])['nod_event'])
        self.assertEqual(risk.head_alerts['forward_head_bob'], 3.4)
        self.assertEqual(risk.update(.6, observation(), [event])['nod_alert_reason'], 'duplicate_event')

    def test_gap_event_rejected_and_eyes_do_not_gate_nodding(self):
        risk = RiskEvaluator()
        risk.update(0, observation())
        risk.update(.1, observation(pitch_deg=20))
        result = risk.update(.5, observation(), [nod_candidate(.1, .5)])
        self.assertEqual(result['nod_alert_reason'], 'frame_gap')
        for state in ('OPEN', 'CLOSED', 'UNKNOWN'):
            risk = RiskEvaluator()
            for t in (0., .1, .2, .3):
                risk.update(t, observation(pitch_deg=12, eye_state=state, eyes_valid=state != 'UNKNOWN'))
            result = risk.update(.4, observation(eye_state=state, eyes_valid=state != 'UNKNOWN'), [nod_candidate(0, .4)])
            self.assertFalse(result['urgent'])

    def test_held_forward_drop_cancels_on_invalid_pose_gap_or_yaw(self):
        for changes, gap in [(dict(pose_valid=0), .1), (dict(yaw_deg=45), .1), ({}, .5)]:
            risk = RiskEvaluator()
            risk.update(0, observation())
            for i in range(1, 15):
                result = risk.update(i*.1, observation(pitch_deg=20, roll_deg=25))
            self.assertTrue(result['urgent'])
            result = risk.update(1.4+gap, observation(pitch_deg=20, **changes))
            self.assertFalse(result['urgent'])

    def test_eye_sensitivity_boundaries(self):
        for threshold in (1., 1.5, 2.):
            risk = RiskEvaluator(replace(RiskConfig(), eye_closed_seconds=threshold))
            for i, duration in enumerate((threshold-.01, threshold, threshold+.01)):
                result = risk.update(i*.1, observation(eye_state='CLOSED', eye_observed_closed_s=duration))
                self.assertEqual(result['urgent'], duration >= threshold)
            self.assertFalse(risk.update(.4, observation(eyes_valid=0, eye_state='CLOSED',
                                                        eye_observed_closed_s=10))['urgent'])

    def test_unknown_and_calibration(self):
        risk = RiskEvaluator()
        row = observation(eyes_valid=0, mouth_valid=0, pose_valid=0)
        self.assertEqual(risk.update(0, row)['level'], 'UNKNOWN')
        row['phase'] = 'CALIBRATING'
        self.assertEqual(risk.update(.1, row)['level'], 'CALIBRATING')

    def test_yawn_fourth_once_and_expiry(self):
        risk = RiskEvaluator()
        event = dict(kind='yawn_confirmed')
        for t in (0, 20, 40):
            self.assertFalse(risk.update(t, observation(), [event])['yawn_reminder'])
        fourth = risk.update(60, observation(), [event])
        self.assertEqual(fourth['level'], 'NORMAL')
        self.assertFalse(fourth['frequent_yawns_event']); self.assertFalse(fourth['alarm_active'])
        self.assertFalse(risk.update(60.1, observation())['yawn_reminder'])
        self.assertEqual(risk.update(120.01, observation())['yawn_count'], 0)
        risk.update(121, observation(), [dict(kind='mouth_held_flag', start_known=1)])
        self.assertEqual(len(risk.yawns), 0)

    def test_static_tilt_never_triggers_at_various_fps_and_sides(self):
        for fps in (10, 15, 30, 60):
            for angle in (-30., -25., -10., 10., 25., 30.):
                risk = RiskEvaluator()
                for i in range(5*fps+1):
                    t = i/fps
                    result = risk.update(t, observation(roll_deg=angle))
                    self.assertFalse(result['urgent'])
                    self.assertFalse(result['nod_event'])
                    self.assertEqual(result['level'], 'NORMAL')

    def test_tilt_reset_on_gap_invalid_or_side_change(self):
        for row, timestamp in [(observation(pose_valid=0), .15),
                               (observation(roll_deg=-12), .15),
                               (observation(roll_deg=12), .5)]:
            risk = RiskEvaluator()
            risk.update(0, observation(roll_deg=12))
            risk.update(.1, observation(roll_deg=12))
            self.assertFalse(risk.update(timestamp, row)['urgent'])
            self.assertFalse(risk.update(timestamp+.1, observation(roll_deg=12))['urgent'])
        for angle, band in [(5, 'STRAIGHT'), (7, 'LEANING'), (10, 'TILTED')]:
            self.assertEqual(RiskEvaluator().update(0, observation(roll_deg=angle))['tilt_band'], band)

    def nod_sequence(self, speed, invalid=False):
        risk = RiskEvaluator()
        risk.update(0, observation())
        for t in (.1, .2, .3, .4):
            risk.update(t, observation(pitch_deg=20))
        risk.update(.5, observation(pitch_deg=12, pitch_velocity_deg_s=-speed, pose_valid=not invalid))
        return risk, risk.update(.6, observation(pitch_deg=5, pitch_velocity_deg_s=-speed), [nod_candidate(.1, .6)])

    def test_jerk_vs_slow_recovery_and_invalid(self):
        risk, result = self.nod_sequence(70)
        self.assertTrue(result['nod_event'])
        self.assertFalse(result['urgent'])
        for i in range(1, 30):
            self.assertFalse(risk.update(.6+i*.1, observation())['urgent'])
        self.assertFalse(risk.update(3.6, observation())['urgent'])
        self.assertTrue(self.nod_sequence(20)[1]['nod_event'])
        self.assertFalse(self.nod_sequence(70, invalid=True)[1]['nod_event'])

    def test_prolonged_bow_not_rearmed_while_down(self):
        risk = RiskEvaluator()
        risk.update(0, observation())
        for i in range(1, 40):
            result = risk.update(i*.1, observation(pitch_deg=20))
            self.assertEqual(result['urgent'], i >= 9)
            if i >= 9:
                self.assertIn('forward_head_drop', result['reasons'])
        self.assertFalse(risk.update(4., observation(pitch_deg=0, pitch_velocity_deg_s=-150))['nod_event'])

    def test_forward_bob_while_already_tilted(self):
        risk = RiskEvaluator()
        risk.update(0, observation(roll_deg=25))
        for t in (.1, .2, .3, .4):
            self.assertFalse(risk.update(t, observation(pitch_deg=20, roll_deg=25))['urgent'])
        result = risk.update(.5, observation(pitch_deg=0, roll_deg=25, pitch_velocity_deg_s=-100), [nod_candidate(.1, .5)])
        self.assertTrue(result['forward_nod_event'])
        self.assertIn('forward_head_bob', result['observation_reasons'])
        self.assertFalse(result['lateral_nod_event'])

    def lateral_sequence(self, baseline, side, slow=False, yaw_change=False):
        risk = RiskEvaluator()
        for i in range(7):
            risk.update(i*.1, observation(roll_deg=baseline))
        for t in (.7, .8, .9, 1.):
            result = risk.update(t, observation(roll_deg=baseline+side*20, yaw_deg=15 if yaw_change else 0))
            self.assertFalse(result['urgent'])
        if slow:
            for i in range(1, 11):
                result = risk.update(1.+i*.1, observation(roll_deg=baseline+side*(20-i*2)))
            return risk, result
        return risk, risk.update(1.1, observation(roll_deg=baseline))

    def test_lateral_bob_from_straight_or_tilted_rest(self):
        for baseline in (-25., 0., 25.):
            for side in (-1, 1):
                risk, result = self.lateral_sequence(baseline, side)
                self.assertTrue(result['lateral_nod_event'])
                self.assertFalse(result['forward_nod_event'])
                self.assertIn('lateral_head_bob', result['observation_reasons'])
                self.assertFalse(result['urgent'])
        self.assertFalse(self.lateral_sequence(20, 1, slow=True)[1]['urgent'])

    def test_lateral_baseline_must_be_stable(self):
        risk = RiskEvaluator()
        for i in range(10):
            result = risk.update(i*.1, observation(roll_deg=20 if i % 2 else 0))
            self.assertFalse(result['nod_event'])
            self.assertFalse(result['urgent'])

    def test_head_bob_without_known_onset_does_not_trigger(self):
        risk = RiskEvaluator()
        for t in (0, .1, .2, .3):
            risk.update(t, observation(pitch_deg=20))
        self.assertFalse(risk.update(.4, observation(pitch_velocity_deg_s=-100))['nod_event'])

    def test_yaw_gate_and_change_cancel_head_sequences(self):
        for changed in (12., 40.):
            risk = RiskEvaluator()
            risk.update(0, observation())
            for t in (.1, .2, .3, .4):
                risk.update(t, observation(pitch_deg=20))
            result = risk.update(.5, observation(yaw_deg=changed, pitch_velocity_deg_s=-100))
            self.assertFalse(result['urgent'])
            self.assertFalse(result['nod_event'])
        for i in range(10):
            result = risk.update(.6+i*.1, observation(yaw_deg=45, roll_deg=25))
            self.assertFalse(result['urgent'])

    def test_gap_and_missing_pose_cancel_each_axis(self):
        for invalid in (True, False):
            risk = RiskEvaluator()
            for i in range(7):
                risk.update(i*.1, observation())
            for t in (.7, .8, .9, 1.):
                risk.update(t, observation(pitch_deg=20, roll_deg=20))
            t = 1.1 if invalid else 1.5
            result = risk.update(t, observation(pose_valid=not invalid, pitch_velocity_deg_s=-100))
            self.assertFalse(result['nod_event'])
            self.assertFalse(result['urgent'])

    def test_short_drops_and_down_without_return_do_not_trigger(self):
        risk = RiskEvaluator()
        for i in range(7):
            risk.update(i*.1, observation())
        risk.update(.7, observation(pitch_deg=20, roll_deg=20))
        result = risk.update(.8, observation(pitch_velocity_deg_s=-100))
        self.assertFalse(result['nod_event'])
        for i in range(1, 40):
            result = risk.update(.8+i*.1, observation(pitch_deg=20, roll_deg=20))
            self.assertEqual(result['urgent'], i >= 9)

    def test_simultaneous_bobs_share_one_alarm(self):
        risk = RiskEvaluator()
        for i in range(7):
            risk.update(i*.1, observation())
        for t in (.7, .8, .9, 1.):
            risk.update(t, observation(pitch_deg=20, roll_deg=20))
        result = risk.update(1.1, observation(pitch_velocity_deg_s=-100), [nod_candidate(.7, 1.1)])
        self.assertTrue(result['forward_nod_event'])
        self.assertTrue(result['lateral_nod_event'])
        pattern = AlarmPattern()
        pattern.publish(1.1, result)
        self.assertFalse(pattern.active(1.1))
        self.assertEqual(len(result['observation_reasons']), 2); self.assertEqual(result['alarm_reasons'], [])

    def test_eye_closure_while_looking_aside_still_warns(self):
        result = RiskEvaluator().update(0, observation(yaw_deg=45, eye_state='CLOSED', eye_observed_closed_s=2))
        self.assertTrue(result['urgent'])
        self.assertIn('suspected_sleep_eye_closure', result['reasons'])

    def test_timestamp_validation(self):
        risk = RiskEvaluator()
        risk.update(1, observation())
        with self.assertRaises(ValueError):
            risk.update(1, observation())


class RuntimeTests(unittest.TestCase):
    def test_shallow_short_nod_detected_through_fast_filter_without_alarm(self):
        import math
        import numpy as np
        for fps in (10, 15, 30):
            proc, a, _ = self.calibrated_processor()
            risk = RiskEvaluator()
            results = []
            for i in range(fps*2):
                pitch = 4.5 if .4 <= i/fps < .8 else 0
                c, s = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
                matrix = np.eye(4)
                matrix[:3, :3] = [[1, 0, 0], [0, c, -s], [0, s, c]]
                row, events = proc.update(3.+i/fps, self.geometry(), matrix)
                result = risk.update(3.+i/fps, row, events)
                results.append(result)
                self.assertFalse(result['alarm_active'])
            self.assertTrue(any(x['forward_nod_event'] for x in results), fps)

    def test_held_drop_and_eye_closure_send_cdc_and_clear(self):
        class Serial:
            def __init__(self, *args, **kwargs):
                self.commands = []
            def write(self, command):
                self.commands.append(command)
                return len(command)
            def close(self):
                pass
        for kind in ('held_drop', 'eyes'):
            risk = RiskEvaluator()
            risk.update(0, observation())
            for i in range(1, 13):
                row = observation(pitch_deg=20) if kind == 'held_drop' else observation(eye_state='CLOSED', eye_observed_closed_s=1.5)
                result = risk.update(i*.1, row)
            self.assertTrue(result['alarm_active'])
            with patch('serial.Serial', Serial):
                controller = AlarmController('fake')
                try:
                    controller.publish(result, time.monotonic())
                    deadline = time.monotonic()+.15
                    while b'ALARM 1\n' not in controller.transport.serial.commands and time.monotonic() < deadline:
                        time.sleep(.005)
                    self.assertIn(b'ALARM 1\n', controller.transport.serial.commands)
                    cleared = risk.update(1.3, observation())
                    self.assertFalse(cleared['alarm_active'])
                    controller.publish(cleared, time.monotonic())
                    time.sleep(.04)
                    self.assertEqual(controller.transport.serial.commands[-1], b'ALARM 0\n')
                finally:
                    controller.close()

    def test_accepted_nod_keeps_cdc_off(self):
        class Serial:
            def __init__(self, *args, **kwargs):
                self.commands = []
                self.closed = False
            def write(self, command):
                self.commands.append(command)
                return len(command)
            def close(self):
                self.closed = True
        risk = RiskEvaluator()
        for t in (0., .1, .2, .3):
            risk.update(t, observation(pitch_deg=12))
        result = risk.update(.4, observation(), [nod_candidate(0, .4)])
        with patch('serial.Serial', Serial):
            controller = AlarmController('fake')
            try:
                controller.publish(result, time.monotonic())
                deadline = time.monotonic()+.15
                while b'ALARM 1\n' not in controller.transport.serial.commands and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertNotIn(b'ALARM 1\n', controller.transport.serial.commands)
            finally:
                controller.close()
            self.assertEqual(controller.transport.serial.commands[-1], b'ALARM 0\n')
            self.assertTrue(controller.transport.serial.closed)

    def calibrated_processor(self, threshold=1.5):
        import numpy as np
        a = arguments(['--camera', '0', '--alarm-port', 'none', '--calibration-seconds', '.1',
                       '--eye-closed-seconds', str(threshold)])
        proc = Processor(a)
        matrix = np.eye(4)
        geometry = self.geometry()
        with contextlib.redirect_stdout(io.StringIO()):
            for i in range(60):
                proc.update(i*.05, geometry, matrix)
        self.assertIsNotNone(proc.baseline)
        return proc, a, matrix

    def geometry(self, ear=.3, mar=.02):
        import numpy as np
        points = np.zeros((478, 2))
        for indices in (LEFT_EYE, RIGHT_EYE):
            points[list(indices)] = [(0, 0), (10, ear*20), (30, ear*20),
                                     (40, 0), (30, -ear*20), (10, -ear*20)]
        points[78], points[308] = (0, 0), (40, 0)
        points[13], points[14] = (20, -mar*20), (20, mar*20)
        return Geometry(state='GEOMETRY_OK', points=points,
                        valid=dict(left_eye=True, right_eye=True, mouth=True, head=True))

    def test_processor_to_risk_uses_selected_eye_threshold(self):
        proc, a, matrix = self.calibrated_processor(2.)
        risk = RiskEvaluator(replace(RiskConfig(), eye_closed_seconds=2.))
        row, events = proc.update(3., self.geometry(), matrix)
        risk.update(3., row, events)
        for i in range(42):
            t = 3.125 + i*.0625
            row, events = proc.update(t, self.geometry(ear=.03), matrix)
            result = risk.update(t, row, events)
            self.assertEqual(result['urgent'], i >= 32)
            self.assertEqual(bool(row['long_closure']), i >= 32)

    def test_filtered_pose_detects_bobs_while_tilted(self):
        import numpy as np
        import math
        for axis, expected in [('pitch', 'forward_nod_event'), ('roll', 'lateral_nod_event')]:
            proc, a, _ = self.calibrated_processor()
            risk = RiskEvaluator()
            t = 3.

            def feed(pitch, roll):
                nonlocal t
                cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
                cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
                matrix = np.eye(4)
                matrix[:3, :3] = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]]) @ np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
                row, events = proc.update(t, self.geometry(), matrix)
                result = risk.update(t, row, events)
                t += .05
                return result

            # A long static lean must stay silent and become the local side rest.
            for _ in range(100):
                self.assertFalse(feed(0, 25)['urgent'])
            for _ in range(16):
                self.assertFalse(feed(25 if axis == 'pitch' else 0, 45 if axis == 'roll' else 25)['urgent'])
            results = [feed(0, 25) for _ in range(10)]
            self.assertTrue(any(result[expected] for result in results))

    def test_mouth_observation_is_immediate_for_all_eye_states(self):
        for eyes in ('open', 'closed', 'invalid'):
            proc, a, matrix = self.calibrated_processor()
            tracker = MouthObservation()
            geometry = self.geometry(ear=.03 if eyes == 'closed' else .3, mar=.65)
            if eyes == 'invalid':
                geometry.valid.update(left_eye=False, right_eye=False)
            row, events = proc.update(3., geometry, matrix)
            observed = tracker.update(3., row)
            self.assertEqual(observed['state'], 'OPEN')
            self.assertEqual(observed['events'][0]['kind'], 'mouth_observation')
            row, events = proc.update(3.1, geometry, matrix)
            self.assertEqual(tracker.update(3.1, row)['events'], [])

    def test_calibration_retries_and_runtime_errors_propagate(self):
        a = arguments(['--camera', '0', '--alarm-port', 'none'])
        proc = Processor(a)
        with patch.object(proc, 'update', side_effect=ValueError('moving head')):
            with contextlib.redirect_stdout(io.StringIO()):
                new, row, events = update_observation(proc, a, 1., Geometry(), None)
        self.assertIsNot(proc, new)
        self.assertEqual(row['phase'], 'CALIBRATING')
        self.assertEqual(events[0]['kind'], 'calibration_rejected')
        proc.baseline = {}
        with patch.object(proc, 'update', side_effect=ValueError('bad timestamp')):
            with self.assertRaises(ValueError):
                update_observation(proc, a, 2., Geometry(), None)

    def test_app_yawn_duration_range_and_hysteresis(self):
        for duration, expected in [(2.9, 'mouth_open_event'), (3., 'yawn_candidate'),
                                   (4., 'yawn_candidate'), (5., 'yawn_candidate'),
                                   (5.1, 'mouth_open_event')]:
            tr = DurationTracker(DurationConfig('mouth', .45, .30, 3., 5., 3.))
            tr.update(0, .1)
            # Binary fractions keep the exact 3 and 5 second boundary reproducible.
            start = .125
            tr.update(start, .6)
            t = start + .125
            while t < start + duration:
                tr.update(t, .4)  # Within hysteresis band: stays continuously open.
                t += .125
            events = tr.update(start + duration, .1)['events']
            self.assertEqual(events[0]['kind'], expected)

    def test_alarm_cadence_and_stale_cutoff(self):
        pattern = AlarmPattern(.2)
        risk = dict(alarm_active=True, urgent=True, yawn_reminder=False)
        pattern.publish(0, risk)
        self.assertTrue(pattern.active(.1))
        self.assertFalse(pattern.active(.21))
        pattern.publish(.31, risk)
        self.assertFalse(pattern.active(.31))
        pattern.publish(.51, risk)
        self.assertTrue(pattern.active(.51))
        pattern.reset()
        self.assertFalse(pattern.active(.52))

    def test_yawn_reminder_expires_without_retrigger(self):
        pattern = AlarmPattern()
        pattern.publish(0, dict(alarm_active=False, urgent=False, yawn_reminder=True))
        for i in range(1, 31):
            t = i*.1
            pattern.publish(t, dict(alarm_active=False, urgent=False, yawn_reminder=False))
            self.assertFalse(pattern.active(t))

    def test_usb_refresh_off_partial_and_close(self):
        class Serial:
            commands = []
            closed = False
            partial = False
            def __init__(self, *args, **kwargs):
                pass
            def write(self, command):
                self.commands.append(command)
                return 0 if self.partial else len(command)
            def close(self):
                self.closed = True
        with patch('serial.Serial', Serial), patch('usb_alarm.time.monotonic') as clock:
            clock.return_value = 0
            alarm = USBAlarm('fake')
            alarm.update(True)
            clock.return_value = .49
            alarm.update(True)
            self.assertEqual(alarm.serial.commands, [b'ALARM 0\n', b'ALARM 1\n'])
            clock.return_value = .5
            alarm.update(True)
            self.assertEqual(len(alarm.serial.commands), 3)
            alarm.update(False)
            alarm.serial.partial = True
            with self.assertRaises(OSError):
                alarm.close()
            self.assertTrue(alarm.serial.closed)

    def test_alarm_thread_turns_off_if_inference_stalls(self):
        class Transport:
            def __init__(self, port):
                self.calls = []
                self.closed = False
            def update(self, value):
                self.calls.append(value)
            def close(self):
                self.closed = True
        controller = AlarmController('fake', stale_seconds=.06, transport_factory=Transport)
        try:
            controller.publish(dict(alarm_active=True, urgent=True, yawn_reminder=False), time.monotonic())
            time.sleep(.04)
            self.assertIn(True, controller.transport.calls)
            time.sleep(.08)
            self.assertFalse(controller.transport.calls[-1])
        finally:
            controller.close()
        self.assertTrue(controller.transport.closed)

    def test_alarm_write_failure_surfaces_and_closes(self):
        class Broken:
            def __init__(self, port):
                self.closed = False
            def update(self, active):
                raise OSError('disconnected')
            def close(self):
                self.closed = True
        controller = AlarmController('fake', transport_factory=Broken)
        controller.thread.join(.5)
        self.assertIn('disconnected', controller.status)
        self.assertTrue(controller.transport.closed)
        controller.close()

    def test_camera_only_keeps_latest_frame(self):
        import numpy as np
        class Capture:
            def __init__(self):
                self.n = 0
                self.released = False
                self.resume = threading.Event()
            def read(self):
                self.n += 1
                if self.n > 5:
                    self.resume.wait(.5)
                return True, np.zeros((2, 2, 3), dtype=np.uint8)
            def release(self):
                self.released = True
        capture = Capture()
        reader = LatestCamera(capture)
        deadline = time.monotonic()+.5
        while reader.received < 5 and time.monotonic() < deadline:
            time.sleep(.001)
        self.assertEqual(reader.read(0)[0], 5)
        reader.stopping.set()
        capture.resume.set()
        reader.close()
        self.assertTrue(capture.released)

    def test_parser_and_processor_threshold(self):
        a = arguments(['--camera', '0', '--eye-closed-seconds', '2', '--alarm-port', 'none'])
        self.assertEqual(a.camera, 0)
        self.assertEqual(Processor(a).observed_eyes.threshold, 2)
        for argv in (['--eye-closed-seconds', '3'], ['--video', 'missing.mp4'],
                     ['--max-gap', 'nan'], ['--hardware-test', '--seconds', '5']):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                arguments(argv)


if __name__ == '__main__':
    unittest.main()
