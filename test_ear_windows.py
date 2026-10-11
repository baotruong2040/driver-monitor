import csv
import json
import math
from pathlib import Path
import tempfile
import unittest
from window_features import aggregate, weighted_stats, with_baselines, export
from test_windows import frame


def ear_frame(t,left=.3,right=.4,lb=.3,rb=.4,eye='OPEN'):
    r=frame(t,eye)
    r.update(left_ear=left,right_ear=right,left_ear_baseline=lb,right_ear_baseline=rb,eyes_valid=1)
    return r


def calibration(t,left=.3,right=.4):
    return dict(completed_at_s=t,baseline=dict(left_baseline=left,right_baseline=right))


class EarWindowTests(unittest.TestCase):
    def calc(self,rows):
        return aggregate(rows,[],window=1,stride=1,max_gap=.6)[0]

    def test_time_weighted_mean_std_and_p10(self):
        r=self.calc([ear_frame(0,left=.1),ear_frame(.1,left=.3),ear_frame(.6,left=.3),ear_frame(1,left=.3)])
        self.assertAlmostEqual(r['left_ear_mean'],.28)
        self.assertAlmostEqual(r['left_ear_std'],.06)
        self.assertAlmostEqual(r['left_ear_p10'],.1)
        self.assertAlmostEqual(r['left_ear_norm_mean'],.28/.3)

    def test_p10_uses_duration_not_sample_count(self):
        s=weighted_stats([(0.,.01)]*5+[(1.,.95)])
        self.assertEqual(s['p10'],1)

    def test_separate_per_eye_baselines(self):
        r=self.calc([ear_frame(t,left=.15,right=.2) for t in (0,.5,1)])
        self.assertAlmostEqual(r['left_ear_norm_mean'],.5)
        self.assertAlmostEqual(r['right_ear_norm_mean'],.5)
        self.assertAlmostEqual(r['bilateral_ear_norm_mean'],.5)
        self.assertAlmostEqual(r['ear_norm_absdiff_mean'],0)

    def test_disagreement_retains_geometry(self):
        r=self.calc([ear_frame(t,left=.09,right=.4,eye='UNKNOWN') for t in (0,.5,1)])
        self.assertEqual(r['eyes_valid_s'],0)
        self.assertEqual(r['ear_norm_valid_s'],1)
        self.assertAlmostEqual(r['ear_norm_absdiff_mean'],.7)
        self.assertEqual(r['ear_norm_usable'],1)
        self.assertEqual(r['model_input_usable'],0)

    def test_missing_baseline_not_guessed(self):
        r=self.calc([ear_frame(t,lb=None,rb=None) for t in (0,.5,1)])
        self.assertAlmostEqual(r['left_ear_mean'],.3)
        self.assertIsNone(r['left_ear_norm_mean'])
        self.assertIsNone(r['ear_norm_absdiff_mean'])
        self.assertEqual(r['ear_norm_valid_s'],0)

    def test_missing_invalid_ear_excluded(self):
        rows=[ear_frame(t) for t in (0,.2,.4,.6,.8,1)]
        rows[2]['left_ear']=float('nan')
        r=self.calc(rows)
        self.assertAlmostEqual(r['ear_valid_s'],.6)
        self.assertEqual(r['ear_norm_usable'],0)

    def test_gap_excluded(self):
        r=aggregate([ear_frame(t) for t in (0,.1,.9,1)],[],window=1,stride=1,max_gap=.2)[0]
        self.assertAlmostEqual(r['ear_norm_valid_s'],.2)

    def test_baseline_change_interval_excluded(self):
        r=self.calc([ear_frame(0),ear_frame(.5,lb=.6,rb=.8),ear_frame(1,lb=.6,rb=.8)])
        self.assertAlmostEqual(r['ear_valid_s'],1)
        self.assertAlmostEqual(r['ear_norm_valid_s'],.5)
        self.assertAlmostEqual(r['bilateral_ear_norm_mean'],.5)

    def test_values_above_one_not_clipped(self):
        r=self.calc([ear_frame(t,left=.6,right=.8) for t in (0,.5,1)])
        self.assertAlmostEqual(r['bilateral_ear_norm_mean'],2)

    def test_calibration_time_is_causal_and_recalibration_uses_new(self):
        rows=[frame(t) for t in (1,3,5)]
        r=with_baselines(rows,[calibration(2),calibration(4,left=.6,right=.8)])
        self.assertNotIn('left_ear_baseline',r[0])
        self.assertEqual(r[1]['left_ear_baseline'],.3)
        self.assertEqual(r[2]['left_ear_baseline'],.6)
        self.assertNotIn('left_ear_baseline',rows[1])

    def test_bad_baselines_and_conflicts_rejected(self):
        for c in ([calibration(2),calibration(1)],[calibration(0,left=0)],[calibration(math.nan)]):
            with self.assertRaises(ValueError):with_baselines([frame(1)],c)
        with self.assertRaises(ValueError):with_baselines([ear_frame(1,lb=.6)],[calibration(0)])

    def test_report_export_and_filename_guard(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);f=d/'b_frames.csv';e=d/'b_events.csv';p=d/'b.json'
            rows=[ear_frame(t,lb=None,rb=None) for t in (0,.5,1)]
            with f.open('w',newline='') as out:
                w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            e.write_text('channel,kind,start_s,end_s,duration_s,start_known,available_at_s\n')
            report=dict(files=dict(frames=f.name,events=e.name),calibrations=[calibration(0)])
            p.write_text(json.dumps(report))
            path,r=export(f,e,report_path=p,window=1,stride=1,max_gap=.6)
            self.assertAlmostEqual(r[0]['left_ear_norm_mean'],1)
            meta=json.loads(path.with_suffix('.json').read_text())
            self.assertEqual(meta['schema_version'],2)
            self.assertEqual(meta['normalization_source'],'report_calibrations')
            report['files']['frames']='other_frames.csv';p.write_text(json.dumps(report))
            with self.assertRaises(ValueError):export(f,e,d/'other.csv',report_path=p,window=1)

    def test_processor_writes_baselines(self):
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        import numpy as np
        from check_behavior import Processor, FRAME_FIELDS
        from eye_events import EyeTracker, EyeConfig
        from behavior_features import DurationTracker, DurationConfig
        proc=Processor(NS(calibration_seconds=8,max_gap=.2,pitch_sign=1))
        proc.baseline=dict(neutral_rotation=np.eye(3),left_baseline=.3,right_baseline=.4)
        proc.eyes=EyeTracker(EyeConfig(.18,.24,.18,.24))
        proc.mouth=DurationTracker(DurationConfig('mouth',.45,.30,1.5,10,1.5))
        proc.head=DurationTracker(DurationConfig('head',15,8,.2,2.5,2))
        points=np.zeros((478,2))
        points[:6]=[(0,0),(2,-1),(4,-1),(6,0),(4,1),(2,1)]
        points[13]=[1,0];points[14]=[1,.1];points[78]=[0,0];points[308]=[2,0]
        geometry=NS(points=points,valid=dict(left_eye=True,right_eye=True,mouth=True,head=True),state='OK',reasons=[])
        with patch.dict('sys.modules',face_geometry=NS(LEFT_EYE=range(6),RIGHT_EYE=range(6))):
            row,_=proc.update(1,geometry,np.eye(4))
        self.assertEqual(row['left_ear_baseline'],.3)
        self.assertEqual(row['right_ear_baseline'],.4)
        self.assertIn('left_ear_baseline',FRAME_FIELDS)
        self.assertIn('right_ear_baseline',FRAME_FIELDS)


if __name__=='__main__':unittest.main()
