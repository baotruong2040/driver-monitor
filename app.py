"""Live driver observations from ESP32 UVC, with USB CDC buzzer alerts."""
import argparse
import csv
from dataclasses import asdict
from datetime import datetime
import glob
import json
import math
from pathlib import Path
import sys
import time

from check_behavior import Processor, SourceClock
from drowsiness import RiskConfig, RiskEvaluator, MouthObservation
from live_io import AlarmController, LatestCamera

ROOT = Path(__file__).resolve().parent
DEVICE = 'usb-Espressif_ESP32-S3_AI_Camera_AI-DETECT-001'


def device_path(kind):
    folder, suffix = ('v4l', '-video-index0') if kind == 'camera' else ('serial', '-if02')
    paths = glob.glob(f'/dev/{folder}/by-id/{DEVICE}{suffix}')
    if len(paths) != 1:
        raise RuntimeError(f'ESP32 {kind} not found; specify --{kind if kind == "camera" else "alarm-port"} explicitly')
    return paths[0]


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group()
    source.add_argument('--camera', default='auto', help='auto, camera index, or /dev/video path')
    source.add_argument('--video', help='Recorded video: buzzer is disabled')
    p.add_argument('--alarm-port', default='auto', help='auto, none, /dev/ttyACM*, or COMxx')
    p.add_argument('--hardware-test', action='store_true', help='30-second UVC/CDC test without inference')
    p.add_argument('--check', action='store_true', help='Check model on black image, without hardware')
    p.add_argument('--headless', action='store_true')
    p.add_argument('--seconds', type=float, help='Default: run until stopped; hardware test: 30 seconds')
    p.add_argument('--width', type=int, default=1280)
    p.add_argument('--height', type=int, default=720)
    for name, default in [('fps', 30), ('calibration-seconds', 8), ('close-ratio', .65),
                          ('open-ratio', .8), ('mouth-open', .45), ('mouth-close', .30),
                          ('eye-closed-seconds', 1.5),
                          ('nod-enter', 4), ('nod-exit', 2), ('nod-min', .03), ('nod-max', 4),
                          ('head-drop-angle', 10), ('head-rest-angle', 5), ('nod-filter-tau', .03),
                          ('jerk-speed', 60), ('head-hold-seconds', .75), ('max-gap', .2),
                          ('lateral-drop-angle', 15), ('lateral-return-angle', 8),
                          ('lateral-min-seconds', .2), ('lateral-max-seconds', 2.5),
                          ('lateral-baseline-seconds', .5), ('lateral-baseline-spread', 3),
                          ('head-max-yaw', 35), ('head-yaw-change', 10)]:
        p.add_argument('--' + name, type=float, default=default)
    p.add_argument('--tilt-angle', type=float, default=10, help='Display-only angle boundary; does not trigger alarms')
    p.add_argument('--tilt-seconds', type=float, default=.8, help='Legacy compatibility setting; no alarm effect')
    p.add_argument('--pitch-sign', type=int, choices=(-1, 1), default=1)
    a = p.parse_args(argv)
    vals = [v for k, v in vars(a).items() if isinstance(v, (int, float)) and not isinstance(v, bool) and k != 'pitch_sign']
    if not all(math.isfinite(v) and v > 0 for v in vals):
        p.error('Numeric settings must be finite and positive')
    if not 0 < a.close_ratio < a.open_ratio < 1 or not a.mouth_close < a.mouth_open:
        p.error('Invalid eye/mouth thresholds')
    if a.tilt_angle <= 5:
        p.error('tilt-angle must be greater than 5 degrees')
    if a.check and a.hardware_test:
        p.error('--check and --hardware-test are mutually exclusive')
    if a.video and (a.hardware_test or a.alarm_port not in ('auto', 'none')):
        p.error('Recorded video cannot control a buzzer or run hardware tests')
    if a.hardware_test and a.seconds is not None and a.seconds < 8:
        p.error('Hardware test needs at least 8 seconds for alarm and watchdog stages')
    if a.video and not Path(a.video).is_file():
        p.error('Video file does not exist')
    if a.camera.isdecimal():
        a.camera = int(a.camera)
    elif a.camera.startswith('-') and a.camera[1:].isdecimal():
        p.error('Camera index must be nonnegative')
    # Compatibility with the observation Processor; app risk rules own alarms.
    a.head_hold = a.head_hold_seconds
    a.yawn_min, a.yawn_max = .1, 10.  # Compatibility with the measurement-only Processor.
    try:
        risk_config(a)
    except ValueError as exc:
        p.error(str(exc))
    return a


def risk_config(a):
    return RiskConfig(**{k: getattr(a, k) for k in RiskConfig.__dataclass_fields__})


def open_capture(a, cv2):
    source = a.video or (device_path('camera') if a.camera == 'auto' else a.camera)
    backend = cv2.CAP_V4L2 if not a.video and sys.platform.startswith('linux') else cv2.CAP_ANY
    capture = cv2.VideoCapture(source, backend)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f'Cannot open camera/video: {source}')
    if not a.video:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, a.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
        capture.set(cv2.CAP_PROP_FPS, a.fps)
    return capture, source


def alarm_port(a):
    if a.video or a.alarm_port == 'none':
        return None, None
    try:
        return device_path('cdc') if a.alarm_port == 'auto' else a.alarm_port, None
    except RuntimeError as exc:
        return None, str(exc)


def report_path(prefix):
    folder = ROOT / 'reports'
    folder.mkdir(exist_ok=True)
    return folder / (prefix + datetime.now().strftime('_%Y%m%d_%H%M%S_%f'))


def save_report(path, report):
    target = path.with_suffix('.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Report: {target}')


def update_observation(proc, a, t, geometry, matrix):
    """Retry an unstable neutral calibration without killing camera/CDC."""
    calibrating = proc.baseline is None
    try:
        row, events = proc.update(t, geometry, matrix)
        return proc, row, events
    except ValueError as exc:
        if not calibrating:
            raise
        print(f'Calibration retry: {exc} Keep looking straight with eyes open and mouth closed.')
        history = proc.history
        proc = Processor(a)
        proc.history = history
        row, events = proc.update(t, geometry, matrix)
        events.append(dict(channel='app', kind='calibration_rejected', reason=str(exc)))
        return proc, row, events


def hardware_test(a, cv2):
    """Exercise the existing firmware without modifying or flashing it."""
    from usb_alarm import USBAlarm
    path = report_path('hardware')
    report = dict(created_at=datetime.now().astimezone().isoformat(), configuration=vars(a),
                  status='running', firmware_modified=False, buzzer_audible='unconfirmed',
                  watchdog_observed='unconfirmed', cdc_has_ack=False, commands=[], frames=0)
    capture = alarm = None
    started = time.monotonic()
    first = last = None
    failures = 0
    try:
        capture, report['camera'] = open_capture(a, cv2)
        port, error = alarm_port(a)
        if not port:
            raise RuntimeError(error or '--hardware-test requires an alarm port')
        report['alarm_port'] = port
        alarm = USBAlarm(port)
        report['commands'].append(dict(stage='startup_off', time_s=0))
        print('Hardware test: ON during seconds 1-4; OFF at 4; ON once at 5, then watchdog silence until 8.')
        stop_at = a.seconds or 30.
        started = time.monotonic()
        watchdog_sent = off_sent = False
        while time.monotonic() - started < stop_at:
            ok, frame = capture.read()
            now = time.monotonic()
            elapsed = now - started
            if not ok or frame is None or frame.size == 0:
                failures += 1
                raise RuntimeError('UVC read failed')
            first = now if first is None else first
            last = now
            report['frames'] += 1
            report['actual_size'] = [frame.shape[1], frame.shape[0]]
            if 1 <= elapsed < 4:
                before = alarm.sent_at
                alarm.update(True)
                if alarm.sent_at != before:
                    report['commands'].append(dict(stage='active_refresh', time_s=round(elapsed, 3)))
            elif elapsed >= 4 and not off_sent:
                alarm.update(False)
                off_sent = True
                report['commands'].append(dict(stage='explicit_off', time_s=round(elapsed, 3)))
            elif elapsed >= 5 and not watchdog_sent:
                alarm.update(True)
                watchdog_sent = True
                report['commands'].append(dict(stage='watchdog_one_shot', time_s=round(elapsed, 3)))
            # No ON refresh after the one-shot: firmware must expire its deadline.
        stages = {item['stage'] for item in report['commands']}
        report['status'] = 'transport_passed' if {'active_refresh', 'explicit_off', 'watchdog_one_shot'} <= stages else 'incomplete'
    except KeyboardInterrupt:
        report['status'] = 'interrupted'
    except Exception as exc:
        report.update(status='error', error=str(exc))
    finally:
        if alarm is not None:
            try:
                alarm.close()
            except Exception as exc:
                report.update(status='error', shutdown_error=str(exc))
        if capture is not None:
            capture.release()
        report.update(elapsed_seconds=round(time.monotonic() - started, 3), read_failures=failures,
                      receive_fps=round((report['frames'] - 1) / (last - first), 2) if first is not None and last > first else 0.)
        save_report(path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'transport_passed' else 1


def run(a, cv2, mp, landmarker, inspect_face, draw_geometry):
    path = report_path('app')
    report = dict(created_at=datetime.now().astimezone().isoformat(), configuration=vars(a),
                  rules=asdict(risk_config(a)), frames=0, status='running',
                  note='MediaPipe + observation rules; not physiological microsleep confirmation; no image/video saved.')
    capture = reader = alarm = None
    proc, evaluator = Processor(a), RiskEvaluator(risk_config(a))
    yawn_tracker = MouthObservation()
    started = time.monotonic()
    sequence = last_ms = 0
    last_capture = None
    inference_total = 0.
    last_level = last_alarm_status = None
    intervals = []
    events_count = {}
    try:
        capture, report['source'] = open_capture(a, cv2)
        reported_fps = capture.get(cv2.CAP_PROP_FPS)
        report['reported_fps'] = reported_fps if math.isfinite(reported_fps) else None
        clock = SourceClock(reported_fps if math.isfinite(reported_fps) and reported_fps > 0 else a.fps)
        if not a.video:
            reader = LatestCamera(capture)
            port, error = alarm_port(a)
            report['alarm_port'] = port
            report['alarm_status'] = error or 'DISABLED'
            if port:
                alarm = AlarmController(port, a.max_gap)
        print('Keep eyes open, mouth closed and head neutral for calibration. Q/Esc: quit; C: recalibrate.')
        frame_path = path.parent / (path.name + '_frames.csv')
        report['features_csv'] = str(frame_path)
        with path.with_suffix('.csv').open('x', newline='', encoding='utf-8') as output, frame_path.open('x', newline='', encoding='utf-8') as frames_output:
            fields = ['t_seconds', 'channel', 'kind', 'details']
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            frame_fields = ['t_seconds', 'phase', 'frame_age_s', 'left_ear', 'right_ear',
                            'eyes_valid', 'eye_state', 'mar_simple', 'mouth_enter', 'mouth_exit',
                            'mouth_valid', 'mouth_reason', 'mouth_state', 'mouth_observation',
                            'pose_valid', 'head_reason', 'pitch_raw_deg', 'yaw_raw_deg',
                            'roll_raw_deg', 'pitch_deg', 'yaw_deg', 'roll_deg', 'pitch_velocity_deg_s', 'roll_velocity_deg_s',
                            'head_motion', 'head_drop_duration', 'head_block_reason', 'nod_alert_reason', 'nod_pitch_deg',
                            'lateral_baseline', 'lateral_block_reason', 'risk_level', 'alarm_active', 'alarm_reasons',
                            'observation_reasons', 'alarm_requested', 'cdc_status']
            frame_writer = csv.DictWriter(frames_output, fieldnames=frame_fields)
            frame_writer.writeheader()
            next_features_t = 0.

            def log(t, channel, kind, details):
                writer.writerow(dict(t_seconds=round(t, 6), channel=channel, kind=kind,
                                     details=json.dumps(details, ensure_ascii=False)))
                output.flush()
                events_count[kind] = events_count.get(kind, 0) + 1

            while True:
                if not a.video and a.seconds is not None and time.monotonic() - started >= a.seconds:
                    break
                if a.video:
                    ok, frame = capture.read()
                    if not ok:
                        expected = capture.get(cv2.CAP_PROP_FRAME_COUNT)
                        if math.isfinite(expected) and expected > 0 and report['frames'] < expected - 1:
                            raise RuntimeError('Video ended before expected frame count')
                        break
                    captured_at = time.monotonic()
                    t = clock.video_time(capture.get(cv2.CAP_PROP_POS_MSEC) / 1000)
                    if a.seconds is not None and t >= a.seconds:
                        break
                else:
                    item = reader.read(sequence)
                    if item is None:
                        if alarm:
                            alarm.reset()
                        if time.monotonic() - (last_capture or started) > 2:
                            raise RuntimeError('No fresh camera frame for 2 seconds')
                        continue
                    sequence, captured_at, frame = item
                    t = captured_at - started
                    if time.monotonic() - captured_at > a.max_gap:
                        if alarm:
                            alarm.reset()
                        continue
                if last_capture is not None:
                    intervals.append(captured_at - last_capture)
                    if len(intervals) > 60:
                        intervals.pop(0)
                last_capture = captured_at
                last_ms = max(last_ms + 1, int(t * 1000))
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                inference_started = time.monotonic()
                result = landmarker.detect_for_video(image, last_ms)
                inference_total += time.monotonic() - inference_started
                face = result.face_landmarks[0] if result.face_landmarks else None
                matrix = result.facial_transformation_matrixes[0] if result.facial_transformation_matrixes else None
                geometry = inspect_face(face, frame.shape[1], frame.shape[0])
                proc, row, events = update_observation(proc, a, t, geometry, matrix)
                yawn = yawn_tracker.update(t, row)
                events = [e for e in events if e['kind'] != 'mouth_held_flag']
                for event in events:
                    if event['kind'] == 'yawn_candidate':
                        event['kind'] = 'mouth_open_event'
                events += yawn['events']
                risk = evaluator.update(t, row, events)
                for decision in risk['nod_decisions']:
                    log(t, 'head', decision['kind'], decision)
                    print(f'{t:.2f}s: NODDING {"CONFIRMED (observation only)" if decision["reason"] == "accepted" else "REJECTED: " + decision["reason"]}')
                if alarm:
                    if row['phase'] == 'CALIBRATING':
                        alarm.reset()
                    else:
                        alarm.publish(risk, captured_at)
                    report['alarm_status'] = alarm.status
                if report.get('alarm_status') != last_alarm_status:
                    last_alarm_status = report.get('alarm_status')
                    print('CDC:', last_alarm_status)
                    log(t, 'cdc', 'transport_status', dict(status=last_alarm_status))
                for event in events:
                    log(t, event['channel'], event['kind'], event)

                if t >= next_features_t:
                    diagnostic = {name: row.get(name) for name in frame_fields}
                    diagnostic.update(t_seconds=round(t, 6), frame_age_s=round(time.monotonic()-captured_at, 6),
                                      mouth_enter=proc.mouth.config.enter if proc.mouth else None,
                                      mouth_exit=proc.mouth.config.exit if proc.mouth else None,
                                      mouth_observation=yawn['state'], head_motion=risk['head_motion'],
                                      roll_velocity_deg_s=risk['roll_velocity_deg_s'],
                                      head_drop_duration=risk['head_drop_duration'], head_block_reason=risk['head_block_reason'],
                                      nod_alert_reason=risk['nod_alert_reason'],
                                      lateral_baseline=evaluator.lateral.baseline, lateral_block_reason=evaluator.lateral.block_reason,
                                      risk_level=risk['level'], alarm_requested=alarm.requested_active if alarm else False,
                                      alarm_active=risk['alarm_active'], alarm_reasons='|'.join(risk['alarm_reasons']),
                                      observation_reasons='|'.join(risk['observation_reasons']),
                                      cdc_status=report.get('alarm_status', 'DISABLED'))
                    frame_writer.writerow(diagnostic)
                    frames_output.flush()
                    next_features_t = (math.floor(t / .2) + 1) * .2
                state = (risk['level'], tuple(risk['reasons']))
                if state != last_level or risk['nod_event'] or risk['frequent_yawns_event']:
                    log(t, 'risk', 'risk_changed', risk)
                    print(f'{t:.2f}s: {risk["level"]} {", ".join(risk["reasons"])}')
                    last_level = state
                report['frames'] += 1
                report['actual_size'] = [frame.shape[1], frame.shape[0]]
                if a.headless:
                    continue
                display = frame.copy()
                draw_geometry(display, geometry, cv2)
                fps = len(intervals) / sum(intervals) if intervals and sum(intervals) > 0 else 0.
                fmt = lambda value: '--' if value is None else f'{value:.2f}'
                lines = [f'{row["phase"]} | {risk["level"]} | FPS {fps:.1f} | C: calibrate Q: quit',
                         f'Eyes: {row["eye_state"]} closed {fmt(row["eye_observed_closed_s"])}s / {a.eye_closed_seconds}s',
                         f'Mouth / yawn sign (observation only): {yawn["state"]}',
                         f'Pitch/Yaw/Roll: {fmt(row["pitch_deg"])} / {fmt(row["yaw_deg"])} / {fmt(row["roll_deg"])} deg',
                         f'Tilt (observation only): {risk["tilt_band"]} held {risk["tilt_duration"]:.2f}s',
                         f'Head: {risk["head_motion"]} down {risk["head_drop_duration"]:.2f}/{a.head_hold_seconds:g}s | {risk["head_block_reason"]}',
                         f'Nodding pitch: {fmt(row["nod_pitch_deg"])} deg | down >= {a.nod_enter:g}, return <= {a.nod_exit:g}',
                         'Nodding decision: ' + (risk['nod_alert_reason'] or '--'),
                         'Reasons: ' + (', '.join(risk['reasons']) or row['geometry_state']),
                         'Buzzer: ' + ('ALERT: ' + ', '.join(risk['alarm_reasons']) if risk['alarm_active'] else 'OFF'),
                         'CDC: ' + report.get('alarm_status', 'DISABLED')]
                if row['phase'] == 'CALIBRATING':
                    lines.append(f'Neutral calibration: {proc.calibration.valid_seconds:.1f}/{a.calibration_seconds:g}s')
                color = (0, 0, 255) if risk['urgent'] else (0, 220, 255) if risk['level'] == 'HIGH' else (0, 255, 0)
                for index, line in enumerate(lines):
                    y = 28 + index * 28
                    cv2.putText(display, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 3, cv2.LINE_AA)
                    cv2.putText(display, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, .55, color, 1, cv2.LINE_AA)
                cv2.imshow('Driver Monitor', display)
                key = cv2.waitKey(1) & 255
                if key in (27, ord('q'), ord('Q')):
                    break
                if key in (ord('c'), ord('C')):
                    if alarm:
                        alarm.reset()
                    for event in proc.interrupt(t, 'recalibration'):
                        log(t, event['channel'], event['kind'], event)
                    history = proc.history
                    proc, evaluator = Processor(a), RiskEvaluator(risk_config(a))
                    yawn_tracker = MouthObservation()
                    proc.history = history
                    log(t, 'app', 'recalibration', {})
            report['status'] = 'completed'
    except KeyboardInterrupt:
        report['status'] = 'interrupted'
    except Exception as exc:
        report.update(status='error', error=str(exc))
        print('Error:', exc, file=sys.stderr)
    finally:
        if alarm:
            alarm.close()
            report['alarm_status'] = alarm.status
            if alarm.error:
                report['alarm_error'] = alarm.error
        if reader:
            reader.close()
            report['received_frames'] = reader.received
        elif capture is not None:
            capture.release()
        if not a.headless:
            cv2.destroyAllWindows()
        elapsed = time.monotonic() - started
        report.update(elapsed_seconds=round(elapsed, 3), inference_fps=round(report['frames'] / elapsed, 2),
                      average_inference_ms=round(inference_total * 1000 / max(1, report['frames']), 2),
                      calibrations=proc.history, event_counts=events_count)
        save_report(path, report)
    return 1 if report['status'] == 'error' else 0


def main(argv=None):
    a = arguments(argv)
    try:
        import cv2
        if a.hardware_test:
            return hardware_test(a, cv2)
        from check_face import dependencies
        from download_face_model import verify
        cv2, np, mp, python, vision, inspect_face, draw_geometry = dependencies()
        model = ROOT / 'models' / 'face_landmarker.task'
        if not model.is_file() or not verify(model):
            raise RuntimeError('Missing/invalid model: run download_face_model.py')
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model), delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=.5, min_face_presence_confidence=.5,
            min_tracking_confidence=.5, output_facial_transformation_matrixes=True)
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            if a.check:
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((480, 640, 3), dtype=np.uint8))
                result = landmarker.detect_for_video(image, 0)
                print(f'OK: model inference; faces={len(result.face_landmarks)} (black image expects 0)')
                return 0
            return run(a, cv2, mp, landmarker, inspect_face, draw_geometry)
    except Exception as exc:
        print('Error:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
