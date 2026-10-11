"""Bước 5: mắt, miệng/ngáp ứng viên, góc đầu và cúi–trở lại, webcam hoặc MP4."""
import argparse
from collections import Counter
from dataclasses import asdict
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import platform
import sys
import time
import numpy as np

from window_features import ObservedClosed, export as export_windows

from eye_events import EyeConfig, EyeTracker, eye_aspect_ratio
from behavior_features import (mouth_ratio, rotation_from_matrix, relative_angles,
                               AngleFilter, DurationConfig, DurationTracker, NeutralCalibration)

ROOT = Path(__file__).resolve().parent
EVENT_FIELDS = ['channel', 'kind', 'start_s', 'end_s', 'duration_s', 'start_known', 'peak', 'reason', 'available_at_s']
FRAME_FIELDS = ['t_seconds', 'timestamp_ms', 'phase', 'geometry_state', 'geometry_reasons',
                'left_ear', 'right_ear', 'left_ear_baseline', 'right_ear_baseline', 'eyes_valid', 'eye_state', 'eye_closure_s',
                'long_closure', 'eye_reason', 'eye_observed_closed_s', 'eye_observed_start_known', 'mar_simple', 'mouth_valid', 'mouth_state',
                'mouth_duration_s', 'mouth_start_known', 'mouth_held_flag', 'mouth_reason',
                'pose_valid', 'pitch_raw_deg', 'yaw_raw_deg', 'roll_raw_deg',
                'pitch_deg', 'yaw_deg', 'roll_deg', 'pitch_velocity_deg_s', 'head_state',
                'head_duration_s', 'head_start_known', 'head_held_flag', 'head_reason', 'inference_ms']


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group()
    source.add_argument('--camera', type=int, default=0)
    source.add_argument('--video')
    p.add_argument('--seconds', type=float, help='Giới hạn theo thời gian nguồn; video mặc định hết tệp')
    p.add_argument('--check', action='store_true')
    p.add_argument('--headless', action='store_true')
    p.add_argument('--width', type=int, default=640)
    p.add_argument('--height', type=int, default=480)
    p.add_argument('--fps', type=float, default=30)
    p.add_argument('--calibration-seconds', type=float, default=8)
    p.add_argument('--close-ratio', type=float, default=.65)
    p.add_argument('--open-ratio', type=float, default=.8)
    p.add_argument('--mouth-open', type=float, default=.45, help='Ngưỡng tối thiểu MAR_simple mở')
    p.add_argument('--mouth-close', type=float, default=.30, help='Ngưỡng tối thiểu MAR_simple đóng lại')
    p.add_argument('--yawn-min', type=float, default=1.5)
    p.add_argument('--yawn-max', type=float, default=10)
    p.add_argument('--nod-enter', type=float, default=15)
    p.add_argument('--nod-exit', type=float, default=8)
    p.add_argument('--nod-max', type=float, default=2.5)
    p.add_argument('--head-hold', type=float, default=2)
    p.add_argument('--pitch-sign', type=int, choices=(-1, 1), default=1,
                   help='Đổi thành -1 nếu cúi xuống làm pitch âm trong phép thử')
    p.add_argument('--window', type=float, default=30)
    p.add_argument('--stride', type=float, default=5)
    p.add_argument('--min-valid', type=float, default=.8)
    p.add_argument('--max-gap', type=float, default=.2)
    a = p.parse_args()
    vals = [a.fps, a.calibration_seconds, a.close_ratio, a.open_ratio, a.mouth_open,
            a.mouth_close, a.yawn_min, a.yawn_max, a.nod_enter, a.nod_exit,
            a.nod_max, a.head_hold, a.max_gap, a.window, a.stride]
    if a.camera < 0 or min(a.width, a.height) <= 0 or not all(math.isfinite(v) and v > 0 for v in vals):
        p.error('Kích thước/tham số phải hữu hạn và > 0; camera >= 0')
    if not math.isfinite(a.min_valid) or not 0 <= a.min_valid <= 1:
        p.error('min-valid phải nằm trong [0,1]')
    if a.seconds is not None and (not math.isfinite(a.seconds) or a.seconds <= 0):
        p.error('seconds phải > 0 và hữu hạn')
    if a.video and not Path(a.video).is_file():
        p.error('Không tìm thấy video')
    if not 0 < a.close_ratio < a.open_ratio < 1:
        p.error('Cần 0 < close-ratio < open-ratio < 1')
    if not a.mouth_close < a.mouth_open or a.yawn_min > a.yawn_max:
        p.error('Ngưỡng/thời lượng miệng không hợp lệ')
    if not a.nod_exit < a.nod_enter or a.nod_max < .2:
        p.error('Ngưỡng/thời lượng đầu không hợp lệ')
    return a


class SourceClock:
    def __init__(self, fps):
        self.fps, self.last, self.fallbacks = fps, None, 0

    def video_time(self, raw_seconds):
        if math.isfinite(raw_seconds) and raw_seconds >= 0 and (self.last is None or raw_seconds > self.last):
            t = raw_seconds
        else:
            t = 0.0 if self.last is None else self.last+1/self.fps
            self.fallbacks += 1
        self.last = t
        return t


class Processor:
    def __init__(self, a):
        self.a = a
        self.calibration = NeutralCalibration(a.calibration_seconds)
        self.baseline = None
        self.eyes = self.mouth = self.head = None
        self.filter = AngleFilter(max_gap=a.max_gap)
        self.history = []
        self.observed_eyes = ObservedClosed(max_gap=a.max_gap)

    def configs(self):
        if self.baseline is None:
            return None
        return dict(eyes=asdict(self.eyes.config), mouth=asdict(self.mouth.config), head=asdict(self.head.config))

    def interrupt(self, t, reason):
        events = []
        if self.eyes is not None:
            events += [dict(channel='eyes', start_known=1, peak=None, **e)
                       for e in self.eyes.interrupt(t, reason)]
            events += self.mouth.finish(reason)+self.head.finish(reason)
        return events

    def update(self, t, geometry, matrix):
        from face_geometry import LEFT_EYE, RIGHT_EYE
        a = self.a
        left = eye_aspect_ratio(geometry.points, LEFT_EYE) if geometry.valid.get('left_eye') else None
        right = eye_aspect_ratio(geometry.points, RIGHT_EYE) if geometry.valid.get('right_eye') else None
        eyes_valid = left is not None and right is not None
        mar = mouth_ratio(geometry.points) if geometry.valid.get('mouth') else None
        rotation = rotation_from_matrix(matrix) if geometry.valid.get('head') else None
        missing = geometry.points is None
        row = dict(phase='CALIBRATING' if self.baseline is None else 'TRACKING',
                   geometry_state=geometry.state, geometry_reasons='|'.join(geometry.reasons),
                   left_ear=left, right_ear=right,
                   left_ear_baseline=self.baseline.get('left_baseline') if self.baseline is not None else None,
                   right_ear_baseline=self.baseline.get('right_baseline') if self.baseline is not None else None,
                   eyes_valid=int(eyes_valid),
                   eye_state='UNKNOWN', eye_closure_s=None, long_closure=0,
                   eye_observed_closed_s=None, eye_observed_start_known=0,
                   eye_reason='' if eyes_valid else ('no_face' if missing else 'invalid_eye_geometry'),
                   mar_simple=mar, mouth_valid=0, mouth_state='UNKNOWN', mouth_duration_s=None,
                   mouth_start_known=0, mouth_held_flag=0, mouth_reason='calibrating',
                   pose_valid=int(rotation is not None), pitch_raw_deg=None, yaw_raw_deg=None,
                   roll_raw_deg=None, pitch_deg=None, yaw_deg=None, roll_deg=None,
                   pitch_velocity_deg_s=None, head_state='UNKNOWN', head_duration_s=None,
                   head_start_known=0, head_held_flag=0, head_reason='calibrating')
        events = []
        if self.baseline is None:
            ready = self.calibration.add(t, left, right, mar, rotation,
                                         eyes_valid and mar is not None and rotation is not None, a.max_gap)
            if ready:
                self.baseline = self.calibration.result()
                b = self.baseline
                self.eyes = EyeTracker(EyeConfig(b['left_baseline']*a.close_ratio, b['left_baseline']*a.open_ratio,
                                                b['right_baseline']*a.close_ratio, b['right_baseline']*a.open_ratio,
                                                max_gap_s=a.max_gap))
                self.mouth = DurationTracker(DurationConfig('mouth', max(a.mouth_open, b['mouth_baseline']+.25),
                                            max(a.mouth_close, b['mouth_baseline']+.15),
                                            a.yawn_min, a.yawn_max, a.yawn_min, a.max_gap))
                self.head = DurationTracker(DurationConfig('head', a.nod_enter, a.nod_exit, .2,
                                           a.nod_max, a.head_hold, a.max_gap))
                entry = dict(completed_at_s=t, valid_seconds=self.calibration.valid_seconds,
                             samples=len(self.calibration.samples),
                             baseline={k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in b.items()},
                             configs=self.configs())
                self.history.append(entry)
                print('Calibration:', json.dumps(entry, ensure_ascii=False))
            return row, events
        eye = self.eyes.update(t, left, right, eyes_valid, row['eye_reason'])
        row.update(eye_state=eye['state'], eye_closure_s=eye['closure_s'], long_closure=int(eye['long_closure']))
        observed_s, observed_long, observed_event = self.observed_eyes.update(t, eye['state'], eye['closure_s'])
        row.update(eye_observed_closed_s=observed_s,
                   eye_observed_start_known=int(observed_s is not None and not self.observed_eyes.unknown_onset),
                   long_closure=int(eye['long_closure'] or observed_long))
        if observed_event is not None:
            events.append(observed_event)
        if eyes_valid and eye['state'] == 'UNKNOWN':
            row['eye_reason'] = 'eyes_disagree_or_uncertain'
        events += [dict(channel='eyes', start_known=1, peak=None, **e) for e in eye['events']]
        angles = relative_angles(rotation, self.baseline['neutral_rotation'], a.pitch_sign) if rotation is not None else None
        head_valid = angles is not None and all(abs(x) <= 60 for x in angles)
        row['pose_valid'] = int(head_valid)
        filtered, velocity = self.filter.update(t, angles if head_valid else None)
        if angles is not None:
            row.update(pitch_raw_deg=angles[0], yaw_raw_deg=angles[1], roll_raw_deg=angles[2])
        if filtered is not None:
            row.update(pitch_deg=filtered[0], yaw_deg=filtered[1], roll_deg=filtered[2], pitch_velocity_deg_s=velocity)
        head_reason = '' if head_valid else ('no_face' if missing else 'invalid_matrix_or_extreme_pose')
        head = self.head.update(t, filtered[0] if filtered is not None else None, head_valid, head_reason)
        row.update(head_state={'ACTIVE': 'DOWN', 'REST': 'NEUTRAL', 'UNKNOWN': 'UNKNOWN'}[head['state']],
                   head_duration_s=head['duration_s'], head_start_known=head['start_known'],
                   head_held_flag=int(head['held_flag']), head_reason=head_reason)
        events += head['events']
        # Cửa sổ góc cho miệng dùng góc chưa lọc để ngắt ngay khi quay lớn.
        mouth_valid = mar is not None and head_valid and abs(angles[0]) <= 35 and abs(angles[1]) <= 45 and abs(angles[2]) <= 35
        mouth_reason = '' if mouth_valid else ('no_face' if missing else 'invalid_mouth_or_pose_gate')
        mouth = self.mouth.update(t, mar, mouth_valid, mouth_reason)
        row.update(mouth_valid=int(mouth_valid), mouth_state={'ACTIVE': 'OPEN', 'REST': 'CLOSED', 'UNKNOWN': 'UNKNOWN'}[mouth['state']],
                   mouth_duration_s=mouth['duration_s'], mouth_start_known=mouth['start_known'],
                   mouth_held_flag=int(mouth['held_flag']), mouth_reason=mouth_reason)
        events += mouth['events']
        return row, events


def run(a, cv2, mp, landmarker, inspect_face, draw_geometry):
    video = bool(a.video)
    capture = cv2.VideoCapture(a.video if video else a.camera)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError('Không mở được nguồn ảnh')
    started = time.perf_counter()
    proc = Processor(a)
    status, error, stop_reason = 'completed', None, None
    frames, read_frames, last_ms = 0, 0, -1
    first_t = last_t = first_wall = last_wall = None
    source_intervals, inference_times = [], []
    counts, states = Counter(), Counter()
    source_fps, backend, expected_frames = a.fps, None, None
    clock = None
    limit = a.seconds if a.seconds is not None else (None if video else 90)
    prefix = 'behavior_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder = ROOT/'reports'
    frames_path, events_path, json_path = [folder/(prefix+suffix) for suffix in ('_frames.csv', '_events.csv', '.json')]
    actual_size = None
    print('Hiệu chỉnh: nhìn thẳng, mắt mở tự nhiên, miệng khép, giữ đầu trung tính.')
    print('Q/Esc thoát | C hiệu chỉnh lại | Chưa có âm thanh hoặc model buồn ngủ.')
    try:
        folder.mkdir(exist_ok=True)
        if not video:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, a.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
            capture.set(cv2.CAP_PROP_FPS, a.fps)
        backend = capture.getBackendName()
        fps = capture.get(cv2.CAP_PROP_FPS)
        if math.isfinite(fps) and fps > 0:
            source_fps = fps
        if video:
            value = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            expected_frames = int(round(value)) if math.isfinite(value) and value > 0 else None
        clock = SourceClock(source_fps)
        with frames_path.open('x', encoding='utf-8', newline='') as ff, events_path.open('x', encoding='utf-8', newline='') as ef:
            fw, ew = csv.DictWriter(ff, fieldnames=FRAME_FIELDS), csv.DictWriter(ef, fieldnames=EVENT_FIELDS)
            fw.writeheader(); ew.writeheader()

            def log(events):
                for event in events:
                    counts[event['channel']+':'+event['kind']] += 1
                    event = dict(event, available_at_s=last_t if last_t is not None else 0.)
                    ew.writerow({k: '' if v is None else round(v, 6) if isinstance(v, float) else v for k, v in event.items()})
                    print(f"{event['channel']} {event['kind']}: {event['duration_s']:.3f}s [{event['reason']}]")
                if events:
                    ef.flush()

            try:
                while True:
                    if not video and time.perf_counter()-started >= limit:
                        stop_reason = 'source_limit'
                        break
                    ok, frame = capture.read()
                    if not ok or frame is None or frame.size == 0:
                        if not video:
                            raise RuntimeError('Camera ngừng trả frame')
                        if expected_frames is not None and read_frames < expected_frames-1:
                            raise RuntimeError(f'Đọc video dừng sớm: {read_frames}/{expected_frames} frame (metadata có thể không chính xác)')
                        stop_reason = 'end_of_video' if expected_frames is not None else 'video_end_or_decode_failure'
                        break
                    read_frames += 1
                    captured = time.perf_counter()
                    t = clock.video_time(capture.get(cv2.CAP_PROP_POS_MSEC)/1000) if video else captured-started
                    if limit is not None and t >= limit:
                        stop_reason = 'source_limit'
                        break
                    first_t = t if first_t is None else first_t
                    first_wall = captured if first_wall is None else first_wall
                    last_wall = captured
                    if last_t is not None:
                        source_intervals.append(t-last_t)
                    last_t = t
                    actual_size = dict(width=int(frame.shape[1]), height=int(frame.shape[0]))
                    ms = max(last_ms+1, int(t*1000)); last_ms = ms
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    tic = time.perf_counter()
                    result = landmarker.detect_for_video(image, ms)
                    inference_ms = (time.perf_counter()-tic)*1000
                    inference_times.append(inference_ms)
                    face = result.face_landmarks[0] if result.face_landmarks else None
                    geometry = inspect_face(face, frame.shape[1], frame.shape[0])
                    matrix = result.facial_transformation_matrixes[0] if result.facial_transformation_matrixes else None
                    row, events = proc.update(t, geometry, matrix)
                    log(events)
                    row.update(t_seconds=t, timestamp_ms=ms, inference_ms=inference_ms)
                    fw.writerow({k: '' if v is None else round(v, 6) if isinstance(v, float) else v for k, v in row.items()})
                    frames += 1
                    for channel in ('eye', 'mouth', 'head'):
                        states[row['phase']+':'+channel+':'+row[channel+'_state']] += 1
                    if frames % 30 == 0:
                        ff.flush()
                    if a.headless:
                        continue
                    draw_geometry(frame, geometry, cv2)
                    fmt = lambda v: '--' if v is None else f'{v:.2f}'
                    labels = [f"{row['phase']} | source t={t:.2f}s | C: recalibrate | Q/Esc: quit",
                              f"Eyes {row['eye_state']} | EAR {fmt(row['left_ear'])}/{fmt(row['right_ear'])} | long={row['long_closure']}",
                              f"Mouth {row['mouth_state']} | MAR_simple {fmt(row['mar_simple'])} | held={row['mouth_held_flag']}",
                              f"Pitch/Yaw/Roll {fmt(row['pitch_deg'])}/{fmt(row['yaw_deg'])}/{fmt(row['roll_deg'])} deg",
                              f"Head {row['head_state']} | duration {fmt(row['head_duration_s'])}s | held={row['head_held_flag']}"]
                    if row['phase'] == 'CALIBRATING':
                        labels.append(f'Keep neutral: {proc.calibration.valid_seconds:.1f}/{a.calibration_seconds:.1f}s valid')
                    else:
                        labels.append('Candidate events only. Verify pitch sign by tilting down.')
                    # Overlay riêng phía dưới; landmarks vẫn còn nhìn thấy.
                    font_scale = max(.35, min(.6, frame.shape[1]/1400))
                    step = max(18, int(frame.shape[0]*.037))
                    y0 = max(0, frame.shape[0]-(len(labels)*step+10))
                    cv2.rectangle(frame, (0, y0), (frame.shape[1], frame.shape[0]), (25,25,25), -1)
                    for i, label in enumerate(labels):
                        cv2.putText(frame, label, (8, y0+step*(i+1)), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (235,235,235), 1, cv2.LINE_AA)
                    cv2.imshow('Driver Monitor - Step 5', frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord('q'), ord('Q'), 27):
                        status, stop_reason = 'user_stopped', 'key'
                        break
                    if key in (ord('c'), ord('C')):
                        log(proc.interrupt(t, 'recalibration'))
                        history = proc.history
                        proc = Processor(a); proc.history = history
                    if cv2.getWindowProperty('Driver Monitor - Step 5', cv2.WND_PROP_VISIBLE) < 1:
                        status, stop_reason = 'window_closed', 'window'
                        break
            finally:
                log(proc.interrupt(last_t or 0.0, 'run_ended'))
    except KeyboardInterrupt:
        status, stop_reason = 'interrupted', 'keyboard_interrupt'
    except (RuntimeError, ValueError, OSError, cv2.error) as exc:
        status, error = 'error', str(exc)
    finally:
        capture.release()
        if not a.headless:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
    report = dict(created_at=datetime.now().astimezone().isoformat(), status=status, error=error,
                  stop_reason=stop_reason, arguments=vars(a), source_type='video' if video else 'camera',
                  backend=backend, source_fps=source_fps, expected_video_frames=expected_frames,
                  actual_size=actual_size, frames=frames, elapsed_seconds=time.perf_counter()-started,
                  processing_fps=(frames-1)/(last_wall-first_wall) if frames >= 2 and last_wall>first_wall else None,
                  source_span_seconds=last_t-first_t if frames >= 2 else 0,
                  time_basis='video_position_with_fps_fallback' if video else 'monotonic_clock',
                  timestamp_fallbacks=clock.fallbacks if clock else 0,
                  max_source_interval_ms=max(source_intervals)*1000 if source_intervals else None,
                  intervals_over_max_gap=sum(v>a.max_gap for v in source_intervals),
                  inference_mean_ms=float(np.mean(inference_times)) if inference_times else None,
                  environment=dict(python=platform.python_version(), python_executable=sys.executable,
                                   opencv=cv2.__version__, numpy=np.__version__, mediapipe=mp.__version__, delegate='CPU'),
                  state_counts=dict(states), event_counts=dict(counts), calibrations=proc.history,
                  calibration_active_at_end=proc.baseline is None,
                  files=dict(frames=frames_path.name, events=events_path.name),
                  definitions=dict(mar_simple='distance(13,14)/distance(78,308) in pixels',
                                   pose='SVD rotation from MediaPipe matrix; delta R @ neutral.T; RzRyRx Euler; pitch sign configurable'),
                  note='Heuristic candidates, not drowsiness diagnosis. Held flag and completed event may describe one event. FPS fallback assumes constant FPS. Matrix pose and region geometry do not guarantee visibility. Unknown-onset eye flag uses strict observed lower-bound duration; no inferred blink.')
    if frames >= 2:
        try:
            windows_path, windows = export_windows(frames_path, events_path, window=a.window, stride=a.stride,
                                                   max_gap=a.max_gap, min_valid=a.min_valid,calibrations=proc.history)
            report['files']['windows'] = windows_path.name
            report['window_count'] = len(windows)
            report['usable_window_count'] = sum(r['all_channels_usable'] for r in windows)
            report['model_input_usable_window_count'] = sum(r['model_input_usable'] for r in windows)
            print(f'Windows: {windows_path}; rows={len(windows)}')
        except (ValueError, OSError) as exc:
            report['windows_error'] = str(exc)
            print(f'Windows unavailable: {exc}')
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(f'JSON: {json_path}\nFrames: {frames_path}\nEvents: {events_path}')
    print(f'Status: {status}; stop: {stop_reason}; frames: {frames}; events: {dict(counts)}')
    if error:
        print('Error:', error, file=sys.stderr)
    if not proc.history:
        print('Chưa hiệu chỉnh đủ. Đầu/mắt/miệng cần hợp lệ và giữ tư thế trung tính.')
    return 0 if error is None and frames >= 2 and proc.baseline is not None else 1


def main():
    a = arguments()
    try:
        from check_face import dependencies
        from download_face_model import verify
        cv2, _, mp, python, vision, inspect_face, draw_geometry = dependencies()
        model = ROOT/'models'/'face_landmarker.task'
        if not model.is_file() or not verify(model):
            raise RuntimeError('Model thiếu hoặc sai checksum. Chạy download_face_model.py')
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model), delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=.5, min_face_presence_confidence=.5,
            min_tracking_confidence=.5, output_face_blendshapes=False,
            output_facial_transformation_matrixes=True)
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            if a.check:
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((480,640,3), dtype=np.uint8))
                result = landmarker.detect_for_video(image, 0)
                print(f'OK: model chạy; faces={len(result.face_landmarks)} (ảnh đen dự kiến 0)')
                return 0
            return run(a, cv2, mp, landmarker, inspect_face, draw_geometry)
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        print('Error:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
