"""Bước 3: EAR, hiệu chỉnh mắt mở, sự kiện nhắm và chớp mắt."""
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

from eye_events import EyeConfig, EyeTracker, eye_aspect_ratio

ROOT = Path(__file__).resolve().parent
FRAME_FIELDS = ['t_seconds', 'timestamp_ms', 'geometry_state', 'left_ear', 'right_ear',
                'eyes_valid', 'phase', 'eye_state', 'left_state', 'right_state',
                'closure_s', 'long_closure', 'blink_candidates', 'inference_ms', 'reason']
EVENT_FIELDS = ['kind', 'start_s', 'end_s', 'duration_s', 'reason']


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check', action='store_true', help='Kiểm tra model trên ảnh đen')
    source = p.add_mutually_exclusive_group()
    source.add_argument('--camera', type=int, default=0)
    source.add_argument('--video', help='Đường dẫn video; mặc định xử lý đến hết tệp')
    p.add_argument('--seconds', type=float, default=None, help='Giới hạn thời gian nguồn; webcam mặc định 90 giây, video mặc định hết tệp')
    p.add_argument('--width', type=int, default=640)
    p.add_argument('--height', type=int, default=480)
    p.add_argument('--fps', type=float, default=30)
    p.add_argument('--headless', action='store_true')
    p.add_argument('--calibration-seconds', type=float, default=8)
    p.add_argument('--close-ratio', type=float, default=0.65)
    p.add_argument('--open-ratio', type=float, default=0.80)
    p.add_argument('--blink-min', type=float, default=0.06)
    p.add_argument('--blink-max', type=float, default=0.50)
    p.add_argument('--long-seconds', type=float, default=1.50)
    p.add_argument('--max-gap', type=float, default=0.20)
    a = p.parse_args()
    if a.camera < 0 or min(a.width, a.height) <= 0:
        p.error('camera >= 0; kích thước > 0')
    values = [a.fps, a.calibration_seconds, a.close_ratio, a.open_ratio,
              a.blink_min, a.blink_max, a.long_seconds, a.max_gap]
    if not all(math.isfinite(v) and v > 0 for v in values):
        p.error('Tham số số thực phải hữu hạn và > 0')
    if a.seconds is not None and (not math.isfinite(a.seconds) or a.seconds <= 0):
        p.error('seconds phải hữu hạn và > 0')
    if a.video and not Path(a.video).is_file():
        p.error(f'Không tìm thấy video: {a.video}')
    if not 0 < a.close_ratio < a.open_ratio < 1:
        p.error('Cần 0 < close-ratio < open-ratio < 1')
    if not a.blink_min < a.blink_max < a.long_seconds:
        p.error('Cần blink-min < blink-max < long-seconds')
    return a


class Calibration:
    """Tích lũy thời gian hai mắt hợp lệ; không tính khoảng bị mất quan sát."""
    def __init__(self, seconds):
        self.required = seconds
        self.good_s = 0.0
        self.samples = []
        self.previous_t = None

    def add(self, t, left, right, valid, max_gap):
        if not valid:
            self.previous_t = None
            return False
        if self.previous_t is not None and 0 < t-self.previous_t <= max_gap:
            self.good_s += t-self.previous_t
        self.previous_t = t
        self.samples.append((left, right))
        return self.good_s >= self.required and len(self.samples) >= 60


def run(a, cv2, np, mp, landmarker, inspect_face, draw_geometry):
    from face_geometry import LEFT_EYE, RIGHT_EYE
    is_video = bool(a.video)
    camera = cv2.VideoCapture(a.video if is_video else a.camera)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(f'Không mở được nguồn {a.video if is_video else a.camera}')
    folder = ROOT / 'reports'
    try:
        folder.mkdir(exist_ok=True)
    except OSError:
        camera.release()
        raise
    prefix = 'eyes_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    frames_path = folder / (prefix + '_frames.csv')
    events_path = folder / (prefix + '_events.csv')
    report_path = folder / (prefix + '.json')
    counts, state_counts = Counter(), Counter()
    geometry_counts = Counter()
    inference_times, intervals = [], []
    calibration = Calibration(a.calibration_seconds)
    tracker = None
    calibrations = []
    first = last = None
    last_ms = -1
    frames = 0
    status, error = 'completed', None
    title = 'Driver Monitor - Step 3'
    started = time.perf_counter()
    backend, reported_fps, actual_size = None, None, None
    limit = a.seconds if a.seconds is not None else (None if is_video else 90.0)
    timeline = None
    timestamp_fallbacks = 0
    processing_first = processing_last = None
    print('Calibration: nhìn thẳng, giữ mắt mở tự nhiên. Chớp bình thường được.')
    print('C: hiệu chỉnh lại | Q/Esc: thoát. Chưa phát âm thanh ở bước 3.')
    try:
        if not is_video:
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, a.width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
            camera.set(cv2.CAP_PROP_FPS, a.fps)
        backend = camera.getBackendName()
        value = camera.get(cv2.CAP_PROP_FPS)
        reported_fps = value if math.isfinite(value) and value > 0 else None
        source_fps = reported_fps or a.fps
        if is_video and reported_fps is None:
            print(f'Video không cung cấp FPS hợp lệ; dùng --fps={a.fps} để dự phòng timestamp.')
        with frames_path.open('x', newline='', encoding='utf-8') as ff, events_path.open('x', newline='', encoding='utf-8') as ef:
            fw, ew = csv.DictWriter(ff, fieldnames=FRAME_FIELDS), csv.DictWriter(ef, fieldnames=EVENT_FIELDS)
            fw.writeheader()
            ew.writeheader()

            def log_events(events):
                for event in events:
                    ew.writerow({k: round(v, 6) if isinstance(v, float) else v for k, v in event.items()})
                    counts[event['kind']] += 1
                    if event['kind'] != 'brief_closure':
                        print(f"{event['kind']}: {event['duration_s']:.3f}s ({event['reason']})")
                if events:
                    ef.flush()

            try:
                while True:
                    if not is_video and time.perf_counter()-started >= limit:
                        break
                    ok, frame = camera.read()
                    if not ok or frame is None or frame.size == 0:
                        if is_video:
                            break  # OpenCV không phân biệt EOF với lỗi giải mã.
                        raise RuntimeError('Camera ngừng trả frame')
                    captured = time.perf_counter()
                    if is_video:
                        raw = camera.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                        if math.isfinite(raw) and raw >= 0 and (timeline is None or raw > timeline):
                            t = raw
                        else:
                            t = 0.0 if timeline is None else timeline + 1.0/source_fps
                            timestamp_fallbacks += 1
                        if limit is not None and t >= limit:
                            break
                        timeline = t
                    else:
                        t = captured-started
                    processing_first = captured if processing_first is None else processing_first
                    processing_last = captured
                    if first is None:
                        first = t
                        actual_size = {'width': int(frame.shape[1]), 'height': int(frame.shape[0])}
                    if last is not None:
                        intervals.append(t-last)
                    last = t
                    ms = max(last_ms+1, int(t*1000))
                    last_ms = ms
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    inference_started = time.perf_counter()
                    result = landmarker.detect_for_video(image, ms)
                    inference_ms = (time.perf_counter()-inference_started)*1000
                    inference_times.append(inference_ms)
                    face = result.face_landmarks[0] if result.face_landmarks else None
                    geometry = inspect_face(face, frame.shape[1], frame.shape[0])
                    left = eye_aspect_ratio(geometry.points, LEFT_EYE) if geometry.valid.get('left_eye') else None
                    right = eye_aspect_ratio(geometry.points, RIGHT_EYE) if geometry.valid.get('right_eye') else None
                    valid = left is not None and right is not None
                    reason = '' if valid else ('no_face' if face is None else 'invalid_eye_geometry')
                    phase = 'TRACKING' if tracker is not None else 'CALIBRATING'
                    obs = dict(state='UNKNOWN', left_state='UNKNOWN', right_state='UNKNOWN', closure_s=None, long_closure=False, events=[])
                    if tracker is None:
                        ready = calibration.add(t, left, right, valid, a.max_gap)
                        if ready:
                            # Phân vị 70 giúp giảm ảnh hưởng của vài lần chớp trong hiệu chỉnh.
                            baseline = np.percentile(np.asarray(calibration.samples), 70, axis=0)
                            cfg = EyeConfig(float(baseline[0])*a.close_ratio, float(baseline[0])*a.open_ratio,
                                            float(baseline[1])*a.close_ratio, float(baseline[1])*a.open_ratio,
                                            a.blink_min, a.blink_max, a.long_seconds, a.max_gap)
                            tracker = EyeTracker(cfg)
                            calibrations.append(dict(completed_at_s=t, samples=len(calibration.samples),
                                                     valid_seconds=calibration.good_s,
                                                     left_open_baseline=float(baseline[0]),
                                                     right_open_baseline=float(baseline[1]), config=asdict(cfg)))
                            print('Calibration:', json.dumps(calibrations[-1], ensure_ascii=False))
                            # Bắt đầu đo ở frame sau; frame này vẫn được ghi CALIBRATING.
                    else:
                        obs = tracker.update(t, left, right, valid, reason)
                        log_events(obs['events'])
                    frames += 1
                    geometry_counts[geometry.state] += 1
                    state_counts[phase + ':' + obs['state']] += 1
                    row = dict(t_seconds=round(t, 6), timestamp_ms=ms, geometry_state=geometry.state,
                               left_ear='' if left is None else round(left, 6),
                               right_ear='' if right is None else round(right, 6), eyes_valid=int(valid),
                               phase=phase, eye_state=obs['state'], left_state=obs['left_state'], right_state=obs['right_state'],
                               closure_s='' if obs['closure_s'] is None else round(obs['closure_s'], 6),
                               long_closure=int(obs['long_closure']), blink_candidates=counts['blink_candidate'],
                               inference_ms=round(inference_ms, 3), reason=reason or (
                                   'eyes_disagree_or_uncertain' if phase == 'TRACKING' and obs['state'] == 'UNKNOWN' else ''))
                    fw.writerow(row)
                    if frames % 30 == 0:
                        ff.flush()
                    if a.headless:
                        continue
                    draw_geometry(frame, geometry, cv2)
                    ear_text = lambda v: '--' if v is None else f'{v:.3f}'
                    if phase == 'CALIBRATING':
                        label = f'CALIBRATING {calibration.good_s:.1f}/{a.calibration_seconds:.1f}s - keep eyes naturally open'
                    else:
                        duration = '?' if obs['closure_s'] is None else f"{obs['closure_s']:.2f}s"
                        label = f"{obs['state']} | closed: {duration} | blink candidates: {counts['blink_candidate']}"
                    labels = [label, f'EAR left: {ear_text(left)} | right: {ear_text(right)}',
                              f'Geometry: {geometry.state} | C: recalibrate | Q/Esc: quit']
                    if tracker is not None:
                        cfg = tracker.config
                        labels.append(f'Close/Open L: {cfg.left_close:.3f}/{cfg.left_open:.3f} R: {cfg.right_close:.3f}/{cfg.right_open:.3f}')
                    if obs['long_closure']:
                        labels.append('LONG CLOSURE - observed eye closure, not a sleep diagnosis')
                    color = (0, 0, 255) if obs['long_closure'] else (230, 230, 230)
                    cv2.rectangle(frame, (0, 0), (frame.shape[1], 125), (25, 25, 25), -1)
                    for i, label in enumerate(labels):
                        cv2.putText(frame, label, (8, 21+24*i), cv2.FONT_HERSHEY_SIMPLEX, .40, color, 1, cv2.LINE_AA)
                    cv2.imshow(title, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord('q'), ord('Q'), 27):
                        status = 'user_stopped'
                        break
                    if key in (ord('c'), ord('C')):
                        if tracker is not None:
                            log_events(tracker.interrupt(t, 'recalibration'))
                        tracker = None
                        calibration = Calibration(a.calibration_seconds)
                        print('Bắt đầu hiệu chỉnh lại. Giữ mắt mở tự nhiên.')
                    if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                        status = 'window_closed'
                        break
            finally:
                if tracker is not None:
                    log_events(tracker.finish())
    except KeyboardInterrupt:
        status = 'interrupted'
    except (RuntimeError, OSError, ValueError, cv2.error) as exc:
        status, error = 'error', str(exc)
    finally:
        camera.release()
        if not a.headless:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
    span = last-first if frames >= 2 else 0
    report = dict(created_at=datetime.now().astimezone().isoformat(), status=status, error=error,
                  environment=dict(python=platform.python_version(), python_executable=sys.executable,
                                   opencv=cv2.__version__, numpy=np.__version__, mediapipe=mp.__version__, delegate='CPU'),
                  arguments=vars(a), backend=backend, camera_reported_fps=reported_fps,
                  actual_size=actual_size, frames=frames, elapsed_seconds=round(time.perf_counter()-started, 3),
                  loop_fps=round((frames-1)/(processing_last-processing_first), 2) if frames >= 2 and processing_last > processing_first else None,
                  source_type='video' if is_video else 'camera',
                  source_span_seconds=round(span, 6), timestamp_fallbacks=timestamp_fallbacks,
                  time_basis='video_position_with_fps_fallback' if is_video else 'monotonic_clock',
                  max_frame_interval_ms=round(max(intervals)*1000, 2) if intervals else None,
                  intervals_over_max_gap=sum(dt > a.max_gap for dt in intervals),
                  inference_mean_ms=float(np.mean(inference_times)) if inference_times else None,
                  state_counts=dict(state_counts), geometry_counts=dict(geometry_counts), event_counts=dict(counts),
                  calibrations=calibrations, calibration_active_at_end=tracker is None,
                  files=dict(frames=frames_path.name, events=events_path.name),
                  note='Video read failure may mean EOF or decode failure. FPS fallback assumes constant frame rate. Bilateral EAR heuristic. Blink candidates are not ground truth. Long flag and completed closure can describe the same event.')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(f'JSON: {report_path}\nFrames: {frames_path}\nEvents: {events_path}')
    print(f'Status: {status}; FPS: {report["loop_fps"]}; events: {dict(counts)}')
    if not calibrations:
        print('Chưa hiệu chỉnh xong. Cần thêm thời gian quan sát mắt mở hợp lệ.')
    if error:
        print('Error:', error, file=sys.stderr)
    return 0 if error is None and frames >= 2 and calibrations and tracker is not None else 1


def main():
    a = arguments()
    try:
        from check_face import dependencies
        from download_face_model import verify
        cv2, np, mp, python, vision, inspect_face, draw_geometry = dependencies()
        model = ROOT / 'models' / 'face_landmarker.task'
        if not model.is_file() or not verify(model):
            raise RuntimeError('Model thiếu/sai checksum. Chạy .venv\\Scripts\\python.exe download_face_model.py')
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model), delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=.5, min_face_presence_confidence=.5,
            min_tracking_confidence=.5, output_face_blendshapes=False,
            output_facial_transformation_matrixes=False)
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            if a.check:
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((480, 640, 3), dtype=np.uint8))
                result = landmarker.detect_for_video(image, 0)
                print(f'OK: model chạy; faces={len(result.face_landmarks)} (ảnh đen dự kiến 0)')
                return 0
            return run(a, cv2, np, mp, landmarker, inspect_face, draw_geometry)
    except (ImportError, RuntimeError, OSError, ValueError) as exc:
        print('Error:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
