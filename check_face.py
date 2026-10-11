"""Bước 2: Face Landmarker, hiển thị vùng mặt và ghi số liệu quan sát."""

import argparse
from collections import Counter, deque
import csv
from datetime import datetime
import json
import math
import os
from pathlib import Path
import platform
import sys
import time


ROOT = Path(__file__).resolve().parent
FIELDS = ["t_seconds", "timestamp_ms", "state", "landmarks_count", "left_eye_width_px",
          "right_eye_width_px", "mouth_width_px", "left_eye_valid", "right_eye_valid",
          "mouth_valid", "head_valid", "has_face_matrix", "inference_ms", "reasons"]


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Kiểm tra model trên ảnh đen, không mở camera")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if args.camera < 0 or min(args.width, args.height) <= 0:
        parser.error("camera phải >= 0; width và height phải > 0")
    if not all(math.isfinite(x) and x > 0 for x in (args.seconds, args.fps)):
        parser.error("seconds và fps phải hữu hạn > 0")
    return args


def dependencies():
    try:
        import cv2
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        from face_geometry import inspect_face, draw_geometry
    except ImportError as error:
        raise RuntimeError("Thiếu thư viện. Cài requirements-step02.txt trong .venv của dự án") from error
    return cv2, np, mp, python, vision, inspect_face, draw_geometry


def run(args, cv2, np, mp, landmarker, inspect_face, draw_geometry, environment):
    if not args.headless and sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise RuntimeError("Không có phiên đồ họa. Mở terminal trên KDE hoặc dùng --headless")
    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(f"Không mở được camera {args.camera}")
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    prefix = "face_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    csv_path, json_path = reports / f"{prefix}.csv", reports / f"{prefix}.json"
    report = {"created_at": datetime.now().astimezone().isoformat(), "environment": environment,
              "camera_index": args.camera, "requested": {"width": args.width, "height": args.height, "fps": args.fps},
              "headless": args.headless, "geometry_thresholds_px": {"eye_width": 14, "mouth_width": 20}}
    counts, frame_times = Counter(), deque()
    intervals, inference_times = [], []
    first = last = None
    last_ms = -1
    frames = 0
    actual_size = None
    status, error_message = "completed", None
    full_mesh = False
    title = "Driver Monitor - Step 2"
    started = time.perf_counter()
    try:
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        camera.set(cv2.CAP_PROP_FPS, args.fps)
        report["backend"] = camera.getBackendName()
        reported_fps = camera.get(cv2.CAP_PROP_FPS)
        report["camera_reported_fps"] = reported_fps if math.isfinite(reported_fps) else None
        print(f"Backend: {report['backend']}; camera reported FPS: {report['camera_reported_fps']}")
        print("Q/Esc: thoát; M: bật/tắt toàn bộ điểm landmarks. Chạy chỉ một người trước camera.")
        with csv_path.open("x", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            while time.perf_counter() - started < args.seconds:
                ok, frame = camera.read()
                if not ok or frame is None or frame.size == 0:
                    raise RuntimeError("Camera ngừng trả frame")
                captured = time.perf_counter()
                t = captured - started
                timestamp_ms = max(last_ms + 1, int(t * 1000))
                last_ms = timestamp_ms
                if first is None:
                    first = captured
                    actual_size = {"width": int(frame.shape[1]), "height": int(frame.shape[0])}
                if last is not None:
                    intervals.append(captured - last)
                last = captured
                frame_times.append(captured)
                while len(frame_times) > 1 and captured - frame_times[0] > 2:
                    frame_times.popleft()
                span = frame_times[-1] - frame_times[0]
                fps = (len(frame_times) - 1) / span if span > 0 else 0
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                inference_started = time.perf_counter()
                result = landmarker.detect_for_video(image, timestamp_ms)
                inference_ms = (time.perf_counter() - inference_started) * 1000
                inference_times.append(inference_ms)
                face = result.face_landmarks[0] if result.face_landmarks else None
                geometry = inspect_face(face, frame.shape[1], frame.shape[0])
                frames += 1
                counts[geometry.state] += 1
                row = {"t_seconds": f"{t:.6f}", "timestamp_ms": timestamp_ms,
                       "state": geometry.state, "landmarks_count": len(face) if face else 0,
                       "has_face_matrix": int(bool(result.facial_transformation_matrixes)),
                       "inference_ms": f"{inference_ms:.3f}", "reasons": "|".join(geometry.reasons)}
                for region in ("left_eye", "right_eye", "mouth"):
                    value = geometry.widths.get(region)
                    row[f"{region}_width_px"] = f"{value:.3f}" if value is not None else ""
                    row[f"{region}_valid"] = int(geometry.valid.get(region, False))
                row["head_valid"] = int(geometry.valid.get("head", False))
                writer.writerow(row)
                if frames % 30 == 0:
                    output.flush()
                if args.headless:
                    continue
                draw_geometry(frame, geometry, cv2, full_mesh)
                color = (0, 255, 0) if geometry.state == "GEOMETRY_OK" else (0, 180, 255)
                labels = [f"{geometry.state} | points: {len(face) if face else 0}",
                          f"Loop FPS: {fps:.1f} | inference: {inference_ms:.1f}ms",
                          "Left eye: green | right eye: cyan | mouth: orange",
                          "Q/Esc: quit | M: all landmarks"]
                cv2.rectangle(frame, (0, 0), (frame.shape[1], 102), (25, 25, 25), -1)
                for index, label in enumerate(labels):
                    cv2.putText(frame, label, (10, 22 + index * 24), cv2.FONT_HERSHEY_SIMPLEX,
                                .50, color if index == 0 else (230, 230, 230), 1, cv2.LINE_AA)
                cv2.imshow(title, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    status = "user_stopped"
                    break
                if key in (ord("m"), ord("M")):
                    full_mesh = not full_mesh
                if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                    status = "window_closed"
                    break
    except KeyboardInterrupt:
        status = "interrupted"
    except (RuntimeError, cv2.error) as error:
        status, error_message = "error", str(error)
    finally:
        camera.release()
        if not args.headless:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
    span = last - first if frames >= 2 else 0
    report.update({"status": status, "error": error_message, "frames": frames,
                   "elapsed_seconds": round(time.perf_counter() - started, 3), "actual_size": actual_size,
                   "loop_fps": round((frames - 1) / span, 2) if span > 0 else None,
                   "max_frame_interval_ms": round(max(intervals) * 1000, 2) if intervals else None,
                   "intervals_over_200ms": sum(x > .2 for x in intervals),
                   "inference_mean_ms": round(float(np.mean(inference_times)), 2) if inference_times else None,
                   "inference_p95_ms": round(float(np.percentile(inference_times, 95)), 2) if inference_times else None,
                   "state_counts": {key: counts[key] for key in ("GEOMETRY_OK", "LIMITED_GEOMETRY", "NO_FACE")},
                   "geometry_ok_fraction": round(counts["GEOMETRY_OK"] / frames, 4) if frames else None,
                   "csv_file": csv_path.name,
                   "measurement_note": "FPS vòng lặp gồm đọc camera + suy luận + log/hiển thị; geometry OK chỉ là kiểm tra tọa độ/kích thước."})
    with json_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
    print(f"JSON report: {json_path}\nCSV observations: {csv_path}")
    print(f"Status: {status}; frames: {frames}; loop FPS: {report['loop_fps']}; states: {report['state_counts']}")
    if error_message:
        print(f"Error: {error_message}", file=sys.stderr)
        return 1
    return 0 if frames >= 2 else 1


def main():
    args = arguments()
    try:
        cv2, np, mp, python, vision, inspect_face, draw_geometry = dependencies()
        from download_face_model import verify
        model = ROOT / "models" / "face_landmarker.task"
        if not model.is_file() or not verify(model):
            raise RuntimeError("Model thiếu hoặc không đúng bản. Chạy .venv/bin/python download_face_model.py")
        environment = {"python": platform.python_version(), "python_executable": sys.executable,
                       "opencv": cv2.__version__, "numpy": np.__version__, "mediapipe": mp.__version__,
                       "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
                       "qt_platform": os.environ.get("QT_QPA_PLATFORM", "default"),
                       "delegate": "CPU", "model_version": "face_landmarker/float16/1"}
        for name, value in environment.items():
            print(f"{name}: {value}")
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model), delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=.5, min_face_presence_confidence=.5, min_tracking_confidence=.5,
            output_face_blendshapes=False, output_facial_transformation_matrixes=True,
        )
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            if args.check:
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((480, 640, 3), dtype=np.uint8))
                result = landmarker.detect_for_video(image, 0)
                print(f"OK: model chạy trên ảnh đen; faces={len(result.face_landmarks)} (dự kiến 0)")
                print("Đây là kiểm tra nạp/chạy model; chưa đo độ chính xác hoặc kiểm tra webcam.")
                return 0
            return run(args, cv2, np, mp, landmarker, inspect_face, draw_geometry, environment)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
