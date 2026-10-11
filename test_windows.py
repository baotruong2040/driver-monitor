import csv
import tempfile
import unittest
from pathlib import Path
from window_features import aggregate, export, ObservedClosed


def frame(t, eye='OPEN', mouth='CLOSED', head='NEUTRAL', phase='TRACKING'):
    return dict(t_seconds=t, phase=phase, eyes_valid=int(eye!='UNKNOWN'), eye_state=eye,
                mouth_valid=int(mouth!='UNKNOWN'), mouth_state=mouth,
                pose_valid=int(head!='UNKNOWN'), head_state=head, pitch_deg=10.)


def event(kind, end, available=None, channel='eyes', start=0.):
    return dict(kind=kind, end_s=end, available_at_s=end if available is None else available,
                channel=channel, start_s=start, duration_s=end-start, start_known=1)


class WindowTests(unittest.TestCase):
    def calc(self, rows, events=()):
        return aggregate(rows, events, window=1, stride=1, max_gap=.6)[0]

    def test_time_weighted(self):
        r=self.calc([frame(0,'CLOSED'),frame(.1,'CLOSED'),frame(.2),frame(.7),frame(1)])
        self.assertAlmostEqual(r['eyes_closed_ratio'],.1)
        self.assertAlmostEqual(r['eyes_valid_s'],1)

    def test_missing_does_not_bridge(self):
        r=self.calc([frame(0,'CLOSED'),frame(.2,'CLOSED'),frame(.4,'UNKNOWN'),frame(.6,'CLOSED'),frame(.8,'CLOSED'),frame(1)])
        self.assertAlmostEqual(r['eyes_valid_s'],.6)
        self.assertAlmostEqual(r['eyes_closed_s'],.4)
        self.assertAlmostEqual(r['longest_observed_closed_s'],.2)
        self.assertEqual(r['eyes_usable'],0)

    def test_gap_unknown(self):
        r=aggregate([frame(0),frame(.1),frame(.9),frame(1)],[],window=1,stride=1,max_gap=.2)[0]
        self.assertAlmostEqual(r['eyes_valid_s'],.2)
        self.assertAlmostEqual(r['mouth_valid_s'],.2)

    def test_zero_denominator_and_independent_quality(self):
        r=self.calc([frame(t,'UNKNOWN') for t in (0,.5,1)])
        self.assertIsNone(r['eyes_closed_ratio'])
        self.assertIsNone(r['blink_candidate_per_valid_min'])
        self.assertEqual(r['mouth_usable'],1)

    def test_overlap_keeps_both_channels(self):
        r=self.calc([frame(t,'CLOSED','OPEN') for t in (0,.5,1)])
        self.assertEqual(r['eyes_closed_s'],1)
        self.assertEqual(r['eyes_closed_mouth_open_s'],1)
        self.assertEqual(r['eyes_closed_without_mouth_open_s'],0)

    def test_flags_excluded(self):
        r=self.calc([frame(t) for t in (0,.5,1)], [event('mouth_held_flag',.4,channel='mouth'),event('yawn_candidate',.8,channel='mouth')])
        self.assertEqual(r['yawn_candidate_count'],1)
        self.assertEqual(r['yawn_candidate_per_valid_min'],60)

    def test_confirmation_causal(self):
        r=self.calc([frame(t) for t in (0,.5,1)],[event('blink_candidate',.9,1.1)])
        self.assertEqual(r['blink_candidate_count'],0)

    def test_frame_after_window_end_not_used(self):
        r=self.calc([frame(0),frame(.4),frame(.8),frame(1.2)])
        self.assertAlmostEqual(r['eyes_valid_s'],.8)

    def test_processor_unknown_onset_integration(self):
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        import numpy as np
        from check_behavior import Processor
        from eye_events import EyeTracker, EyeConfig
        from behavior_features import DurationTracker, DurationConfig
        proc=Processor(NS(calibration_seconds=8,max_gap=.2,pitch_sign=1))
        proc.baseline={'neutral_rotation':np.eye(3)}
        proc.eyes=EyeTracker(EyeConfig(.18,.24,.18,.24))
        proc.mouth=DurationTracker(DurationConfig('mouth',.45,.30,1.5,10,1.5))
        proc.head=DurationTracker(DurationConfig('head',15,8,.2,2.5,2))
        points=np.zeros((478,2))
        points[:6]=[(0,0),(2,-.3),(4,-.3),(6,0),(4,.3),(2,.3)]
        points[13]=[1,0];points[14]=[1,.1];points[78]=[0,0];points[308]=[2,0]
        geometry=NS(points=points,valid=dict(left_eye=True,right_eye=True,mouth=True,head=True),state='OK',reasons=[])
        events=[]
        with patch.dict('sys.modules',face_geometry=NS(LEFT_EYE=range(6),RIGHT_EYE=range(6))):
            for i in range(21):
                row,ev=proc.update(i*.1,geometry,np.eye(4));events+=ev
            self.assertEqual(row['long_closure'],1)
            self.assertEqual(row['eye_observed_start_known'],0)
            points[1:3,1]=-1.;points[4:6,1]=1.
            _,ev=proc.update(2.1,geometry,np.eye(4));events+=ev
        self.assertEqual([e['kind'] for e in events],['observed_long_closure_flag'])

    def test_half_open_boundary(self):
        r=aggregate([frame(t) for t in (0,.5,1,1.5,2)],[event('blink_candidate',1)],window=1,stride=1,max_gap=.6)
        self.assertEqual([x['blink_candidate_count'] for x in r],[0,1])

    def test_recalibration_segments(self):
        rows=[frame(t,phase='CALIBRATING' if t in (0,2) else 'TRACKING') for t in (0,1,1.5,2,3,3.5,4)]
        r=aggregate(rows,[],window=1,stride=1,max_gap=.6)
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]['window_start_s'],3)
        self.assertEqual(r[0]['segment_id'],1)

    def test_durations_exclude_interrupted(self):
        r=self.calc([frame(t) for t in (0,.5,1)],[event('blink_candidate',.2,start=.1),event('interrupted_closure',.8)])
        self.assertAlmostEqual(r['completed_eye_duration_mean_s'],.1)
        self.assertEqual(r['interrupted_event_count'],1)

    def test_window_edge_clipping(self):
        r=aggregate([frame(t,'CLOSED') for t in (0,.3,.6,.9,1.2,1.5,1.8)],[],window=1,stride=.4,max_gap=.4)
        self.assertEqual(len(r),3)
        self.assertAlmostEqual(r[-1]['eyes_closed_s'],1)

    def test_bad_input(self):
        for times in ((0,0),(0,-1),(0,float('nan'))):
            with self.assertRaises(ValueError):aggregate([frame(t) for t in times],[])
        with self.assertRaises(ValueError):aggregate([],[],window=0)
        with self.assertRaises(ValueError):aggregate([],[],min_valid=2)
        with self.assertRaises(ValueError):aggregate([frame(0),frame(1)],[event('blink_candidate',1,.5)])

    def test_export_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            f,e=Path(d)/'behavior_frames.csv',Path(d)/'behavior_events.csv'
            rows=[frame(t) for t in (0,.5,1)]
            with f.open('w',newline='') as out:
                w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            e.write_text('channel,kind,start_s,end_s,duration_s,start_known,available_at_s\n')
            path,result=export(f,e,window=1,stride=1,max_gap=.6)
            self.assertTrue(path.is_file())
            self.assertTrue(path.with_suffix('.json').is_file())
            self.assertEqual(result[0]['label'],'')
            with self.assertRaises(FileExistsError):export(f,e,window=1,stride=1,max_gap=.6)


class ObservationTests(unittest.TestCase):
    def test_unknown_onset_threshold_once(self):
        tr=ObservedClosed();events=[]
        for i in range(21):
            duration,flag,e=tr.update(i*.1,'CLOSED',None)
            if e:events.append(e)
            if i<15:self.assertFalse(flag)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['start_known'],0)
        self.assertAlmostEqual(events[0]['duration_s'],1.5)

    def test_no_face_resets(self):
        tr=ObservedClosed()
        for i in range(11):tr.update(i*.1,'CLOSED',None)
        self.assertEqual(tr.update(1.1,'UNKNOWN',None),(None,False,None))
        self.assertEqual(tr.update(1.2,'CLOSED',None),(0.,False,None))

    def test_gap_and_disagreement_reset(self):
        tr=ObservedClosed();tr.update(0,'CLOSED',None)
        self.assertEqual(tr.update(2,'CLOSED',None)[0],0)
        tr.update(2.1,'UNKNOWN',None)
        self.assertEqual(tr.update(2.2,'CLOSED',None)[0],0)

    def test_known_onset_no_duplicate(self):
        tr=ObservedClosed();events=[]
        for i in range(21):
            _,_,e=tr.update(i*.1,'CLOSED',i*.1)
            if e:events.append(e)
        self.assertEqual(events,[])


if __name__=='__main__':unittest.main()
