"""Kiểm tra logic thời gian, ngưỡng, che mặt và gián đoạn; không cần webcam."""
import math
import unittest
from check_eyes import Calibration
from eye_events import EyeConfig, EyeTracker, eye_aspect_ratio


class EyeTests(unittest.TestCase):
    def tracker(self, **kwargs):
        return EyeTracker(EyeConfig(.18, .24, .18, .24, **kwargs))

    def test_ear_shape_and_scale(self):
        points = [(0, 0), (2, -1), (4, -1), (6, 0), (4, 1), (2, 1)]
        self.assertAlmostEqual(eye_aspect_ratio(points, range(6)), 1/3)
        scaled = [(x*10, y*10) for x, y in points]
        self.assertAlmostEqual(eye_aspect_ratio(scaled, range(6)), 1/3)
        closed = [(x, 0) for x, _ in points]
        self.assertEqual(eye_aspect_ratio(closed, range(6)), 0)

    def test_invalid_ear(self):
        self.assertIsNone(eye_aspect_ratio([(0, 0)]*6, range(6)))
        self.assertIsNone(eye_aspect_ratio([(math.nan, 0)]*6, range(6)))

    def test_complete_blink_uses_timestamp(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.04, .10, .10)
        out = tr.update(.17, .30, .30)
        self.assertEqual(out['events'][0]['kind'], 'blink_candidate')
        self.assertAlmostEqual(out['events'][0]['duration_s'], .13)

    def test_hysteresis(self):
        tr = self.tracker()
        self.assertEqual(tr.update(0, .30, .30)['state'], 'OPEN')
        self.assertEqual(tr.update(.03, .21, .21)['state'], 'OPEN')
        self.assertEqual(tr.update(.06, .10, .10)['state'], 'CLOSED')
        self.assertEqual(tr.update(.09, .21, .21)['state'], 'CLOSED')
        self.assertEqual(tr.update(.12, .30, .30)['events'][0]['kind'], 'blink_candidate')

    def test_che_mat_interrupts_then_closed_recovery_has_no_start(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        tr.update(.06, .10, .10)
        out = tr.update(.09, None, None, False, 'no_face')
        self.assertEqual(out['state'], 'UNKNOWN')
        self.assertEqual(out['events'][0]['kind'], 'interrupted_closure')
        self.assertAlmostEqual(out['events'][0]['duration_s'], .03)
        out = tr.update(.12, .10, .10)
        self.assertIsNone(out['closure_s'])
        self.assertEqual(tr.update(.15, .30, .30)['events'], [])
        tr.update(.18, .10, .10)
        self.assertEqual(tr.update(.30, .30, .30)['events'][0]['kind'], 'blink_candidate')

    def test_frame_gap_does_not_create_blink(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        out = tr.update(1, .30, .30)
        self.assertEqual([e['kind'] for e in out['events']], ['interrupted_closure'])
        self.assertEqual(out['events'][0]['reason'], 'frame_gap')

    def test_starting_closed_has_no_assumed_onset(self):
        tr = self.tracker()
        self.assertIsNone(tr.update(0, .10, .10)['closure_s'])
        self.assertEqual(tr.update(.10, .30, .30)['events'], [])

    def test_wink_not_counted_as_bilateral_blink(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        self.assertEqual(tr.update(.03, .10, .30)['state'], 'UNKNOWN')
        self.assertEqual(tr.update(.15, .30, .30)['events'], [])

    def test_asymmetric_reopening_completes_blink(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        tr.update(.15, .10, .10)
        out = tr.update(.18, .30, .21)
        self.assertEqual(out['state'], 'UNKNOWN')
        self.assertEqual(out['left_state'], 'OPEN')
        self.assertEqual(out['right_state'], 'CLOSED')
        self.assertEqual(out['events'], [])
        out = tr.update(.21, .30, .30)
        self.assertEqual(out['events'][0]['kind'], 'blink_candidate')
        self.assertAlmostEqual(out['events'][0]['duration_s'], .15)

    def test_asymmetric_closing_still_arms_bilateral_event(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .30)
        tr.update(.06, .10, .10)
        out = tr.update(.18, .30, .30)
        self.assertEqual(out['events'][0]['kind'], 'blink_candidate')
        self.assertAlmostEqual(out['events'][0]['start_s'], .06)

    def test_disagreement_timeout_interrupts(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        tr.update(.12, .10, .10)
        tr.update(.15, .30, .21)
        tr.update(.24, .30, .21)
        out = tr.update(.30, .30, .30)
        self.assertEqual([x['kind'] for x in out['events']], ['interrupted_closure'])
        self.assertEqual(out['events'][0]['reason'], 'eyes_disagree_timeout')
        self.assertAlmostEqual(out['events'][0]['duration_s'], .09)

    def test_short_disagreement_then_closed_keeps_same_onset(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        tr.update(.12, .30, .10)
        tr.update(.15, .10, .10)
        out = tr.update(.18, .30, .30)
        self.assertAlmostEqual(out['events'][0]['duration_s'], .15)

    def test_face_loss_during_transition_interrupts_immediately(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        tr.update(.12, .30, .10)
        out = tr.update(.15, None, None, False, 'no_face')
        self.assertEqual(out['events'][0]['reason'], 'no_face')
        self.assertEqual(tr.update(.18, .30, .30)['events'], [])

    def test_reported_reopening_trace_no_longer_aborts(self):
        cfg = EyeConfig(.18178642851377022, .22373714278617873,
                        .20133668789624962, .24779900048769182)
        tr = EyeTracker(cfg)
        tr.update(15.287261, .28, .31)
        tr.update(15.319096, .10, .10)
        for i in range(1, 10):
            tr.update(15.319096+i*.03, .10, .10)
        tr.update(15.623339, .217672, .242034)
        out = tr.update(15.655583, .221887, .248255)
        self.assertEqual(out['events'], [])
        out = tr.update(15.687588, .226587, .253809)
        self.assertEqual(out['events'][0]['kind'], 'blink_candidate')
        self.assertAlmostEqual(out['events'][0]['duration_s'], .336487)

    def test_long_flag_emitted_once_and_completed_event_separate(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        events = []
        for i in range(1, 20):
            events.extend(tr.update(.03+i*.10, .10, .10)['events'])
        self.assertEqual([e['kind'] for e in events], ['long_closure_flag'])
        out = tr.update(2.03, .30, .30)
        self.assertEqual(out['events'][0]['kind'], 'prolonged_closure')
        self.assertAlmostEqual(out['events'][0]['duration_s'], 2)

    def test_nan_eye_interrupts(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        self.assertEqual(tr.update(.03, math.nan, .30)['state'], 'UNKNOWN')

    def test_finish_does_not_complete_blink(self):
        tr = self.tracker()
        tr.update(0, .30, .30)
        tr.update(.03, .10, .10)
        self.assertEqual(tr.finish()[0]['kind'], 'interrupted_closure')

    def test_nonmonotonic_time_and_bad_config_rejected(self):
        tr = self.tracker()
        tr.update(1, .30, .30)
        with self.assertRaises(ValueError):
            tr.update(1, .30, .30)
        with self.assertRaises(ValueError):
            EyeConfig(.24, .18, .18, .24)

    def test_different_thresholds_for_each_eye(self):
        tr = EyeTracker(EyeConfig(.18, .24, .12, .16))
        self.assertEqual(tr.update(0, .30, .20)['state'], 'OPEN')
        self.assertEqual(tr.update(.03, .15, .10)['state'], 'CLOSED')

    def test_calibration_excludes_hidden_time(self):
        c = Calibration(8)
        c.add(0, .3, .3, True, .2)
        c.add(.1, .3, .3, True, .2)
        c.add(.2, None, None, False, .2)
        c.add(5, .3, .3, True, .2)
        c.add(5.1, .3, .3, True, .2)
        self.assertAlmostEqual(c.good_s, .2)


if __name__ == '__main__':
    unittest.main()
