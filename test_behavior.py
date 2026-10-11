"""Kiểm tra đặc trưng, thời gian, che mặt và tư thế; không cần model/webcam."""
import math
import unittest
from types import SimpleNamespace as NS
import numpy as np
from behavior_features import (mouth_ratio, rotation_from_matrix, mean_rotation, euler_degrees,
                               relative_angles, AngleFilter, DurationConfig, DurationTracker, NeutralCalibration)
from check_behavior import SourceClock, Processor


def rx(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([[1,0,0],[0,c,-s],[0,s,c]])


class BehaviorTests(unittest.TestCase):
    def mouth(self):
        return DurationTracker(DurationConfig('mouth', .45, .30, 1.5, 10, 1.5))

    def head(self):
        return DurationTracker(DurationConfig('head', 15, 8, .2, 2.5, 2))

    def advance(self, tr, first, last, value):
        events = []
        for t in np.arange(first, last+.001, .1):
            events += tr.update(float(t), value)['events']
        return events

    def test_mouth_ratio_and_scale(self):
        p = np.zeros((478,2)); p[13]=[15,-3]; p[14]=[15,3]; p[78]=[0,0]; p[308]=[30,0]
        self.assertAlmostEqual(mouth_ratio(p), .2)
        self.assertAlmostEqual(mouth_ratio(p*2), .2)

    def test_invalid_mouth(self):
        self.assertIsNone(mouth_ratio(None))
        self.assertIsNone(mouth_ratio(np.zeros((478,2))))

    def test_rotation_separates_scale_translation(self):
        m = np.eye(4); m[:3,:3] = 2*rx(20); m[:3,3] = [10,20,30]
        r = rotation_from_matrix(m)
        np.testing.assert_allclose(r, rx(20), atol=1e-8)
        self.assertAlmostEqual(euler_degrees(r)[0], 20)

    def test_reject_reflection_and_bad_matrix(self):
        self.assertIsNone(rotation_from_matrix(np.zeros((4,4))))
        self.assertIsNone(rotation_from_matrix(np.eye(3)))
        m=np.eye(4); m[0,0]=-1
        self.assertIsNone(rotation_from_matrix(m))
        m=np.eye(4); m[0,0]=math.nan
        self.assertIsNone(rotation_from_matrix(m))

    def test_relative_rotation_and_sign(self):
        self.assertAlmostEqual(relative_angles(rx(25),rx(10))[0], 15)
        self.assertAlmostEqual(relative_angles(rx(25),rx(10),-1)[0], -15)

    def test_mean_rotation_handles_wrap(self):
        r=mean_rotation([rx(179),rx(-179)])
        self.assertAlmostEqual(abs(euler_degrees(r)[0]), 180)

    def test_filter_resets_after_missing(self):
        f=AngleFilter()
        f.update(0,(0,0,0))
        angles,v=f.update(.1,(10,0,0))
        self.assertGreater(angles[0],0);self.assertLess(angles[0],10)
        self.assertGreater(v,0)
        self.assertEqual(f.update(.2,None),(None,None))
        angles,v=f.update(.3,(20,0,0))
        self.assertEqual(angles[0],20);self.assertIsNone(v)

    def test_mouth_hysteresis(self):
        tr=self.mouth();tr.update(0,.1)
        self.assertEqual(tr.update(.1,.5)['state'],'ACTIVE')
        self.assertEqual(tr.update(.2,.4)['state'],'ACTIVE')
        self.assertEqual(tr.update(.3,.2)['state'],'REST')

    def test_short_open_is_not_yawn(self):
        tr=self.mouth();tr.update(0,.1);tr.update(.1,.6)
        self.advance(tr,.2,.5,.6)
        self.assertEqual(tr.update(.6,.1)['events'][0]['kind'],'mouth_open_event')

    def test_yawn_candidate_and_single_flag(self):
        tr=self.mouth();tr.update(0,.1);tr.update(.1,.7)
        events=self.advance(tr,.2,2.0,.7)
        self.assertEqual([x['kind'] for x in events],['mouth_held_flag'])
        self.assertEqual(tr.update(2.1,.1)['events'][0]['kind'],'yawn_candidate')

    def test_face_loss_interrupts_mouth(self):
        tr=self.mouth();tr.update(0,.1);tr.update(.1,.7);tr.update(.2,.7)
        out=tr.update(.3,None,False,'no_face')
        self.assertEqual(out['events'][0]['reason'],'no_face')
        self.assertAlmostEqual(out['events'][0]['duration_s'],.1)
        self.assertEqual(out['state'],'UNKNOWN')

    def test_recovery_open_is_segment_not_complete_yawn(self):
        tr=self.mouth();tr.update(0,None,False);tr.update(.1,.7)
        events=self.advance(tr,.2,1.8,.7)
        self.assertEqual(events[0]['start_known'],0)
        out=tr.update(1.9,.1)
        self.assertEqual(out['events'][0]['kind'],'observed_mouth_segment')

    def test_timestamp_gap_interrupts(self):
        tr=self.mouth();tr.update(0,.1);tr.update(.1,.7)
        out=tr.update(1,.1)
        self.assertEqual(out['events'][0]['reason'],'source_gap')

    def test_nod_requires_down_then_return(self):
        tr=self.head();tr.update(0,0);tr.update(.1,20)
        self.assertEqual(tr.update(.2,20)['events'],[])
        self.assertEqual(tr.update(.4,0)['events'][0]['kind'],'nod_candidate')

    def test_held_head_is_not_short_nod(self):
        tr=self.head();tr.update(0,0);tr.update(.1,20)
        events=self.advance(tr,.2,3.0,20)
        self.assertEqual([x['kind'] for x in events],['head_held_flag'])
        self.assertEqual(tr.update(3.1,0)['events'][0]['kind'],'head_down_event')

    def test_upward_pitch_does_not_start_down(self):
        tr=self.head();out=tr.update(0,-20)
        self.assertEqual(out['state'],'REST');self.assertIsNone(out['duration_s'])

    def test_bad_timestamp_and_config(self):
        tr=self.mouth();tr.update(1,.1)
        with self.assertRaises(ValueError):tr.update(1,.1)
        with self.assertRaises(ValueError):DurationConfig('head',8,15,.2,2.5,2)

    def test_neutral_calibration_excludes_gaps(self):
        c=NeutralCalibration(8)
        c.add(0,.3,.3,.02,np.eye(3),True)
        c.add(.1,.3,.3,.02,np.eye(3),True)
        c.add(.2,None,None,None,None,False)
        c.add(5,.3,.3,.02,np.eye(3),True)
        self.assertAlmostEqual(c.valid_seconds,.1)

    def test_moving_calibration_rejected(self):
        c=NeutralCalibration()
        for i in range(60):c.add(i/30,.3,.3,.02,rx(20 if i%2 else -20),True)
        with self.assertRaises(ValueError):c.result()

    def test_video_timestamp_fallback(self):
        c=SourceClock(25)
        self.assertEqual(c.video_time(0),0)
        self.assertAlmostEqual(c.video_time(0),.04)
        self.assertAlmostEqual(c.video_time(math.nan),.08)
        self.assertEqual(c.fallbacks,2)

    def test_video_variable_intervals_preserved(self):
        c=SourceClock(30)
        self.assertEqual([c.video_time(x) for x in (0,.033,.075,.11)],[0,.033,.075,.11])
        self.assertEqual(c.fallbacks,0)


if __name__ == '__main__':
    unittest.main()
