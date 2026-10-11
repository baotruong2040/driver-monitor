"""Bước 1: kiểm tra camera, FPS vòng lặp và tạo báo cáo JSON."""

import argparse
from collections import deque
from datetime import datetime
import json
import math
import os
from pathlib import Path
import platform
import sys
import time


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Kiểm tra thư viện, không mở camera")
    parser.add_argument("--camera", type=int, default=0, help="Chỉ số camera, mặc định 0")
    parser.add_argument("--seconds", type=float, default=30, help="Thời gian chạy tối đa")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=30, help="FPS yêu cầu, camera có thể không đáp ứng")
    parser.add_argument("--headless", action="store_true", help="Đọc camera nhưng không mở cửa sổ")
    parser.add_argument("--v4l2", action="store_true", help="Chọn backend V4L2 trên Linux")
    args = parser.parse_args()
    if args.camera < 0 or min(args.width, args.height) <= 0:
        parser.error("Camera phải >= 0; width và height phải > 0")
    if not all(math.isfinite(x) and x > 0 for x in (args.seconds, args.fps)):
        parser.error("seconds và fps phải là số hữu hạn > 0")
    return args


def dependencies():
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise RuntimeError(
            "Thiếu thư viện. Chạy uv pip install --python .venv/bin/python -r requirements.txt"
        ) from error
    return cv2, np


def environment(cv2, np):
    details = {
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "system": platform.system(),
        "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
    }
    for name, value in details.items():
        print(f"{name}: {value}")
    for line in cv2.getBuildInformation().splitlines():
        if line.strip().startswith(("GUI:", "v4l/v4l2:")):
            print(line.strip())
    return details


def save_report(report):
    folder = Path(__file__).resolve().parent / "reports"
    folder.mkdir(exist_ok=True)
    name = datetime.now().strftime("camera_%Y%m%d_%H%M%S_%f.json")
    path = folder / name
    with path.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
    print(f"Report: {path}")


def measure(args, cv2, info):
    if not args.headless and sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise RuntimeError("Không có phiên đồ họa. Mở terminal trên KDE hoặc thêm --headless")

    backend = cv2.CAP_V4L2 if args.v4l2 else cv2.CAP_ANY
    camera = cv2.VideoCapture(args.camera, backend)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(
            f"Không mở được camera {args.camera}. Đóng app đang dùng webcam, "
            "kiểm tra v4l2-ctl --list-devices, hoặc thử --camera 1"
        )

    frame_times = deque()
    intervals = []
    frames = 0
    first_time = last_time = None
    actual_size = None
    status = "completed"
    error_message = None
    title = "Driver Monitor - Step 1"
    started = time.perf_counter()
    report = {
        "created_at": datetime.now().astimezone().isoformat(),
        "environment": info,
        "camera_index": args.camera,
        "requested": {"width": args.width, "height": args.height, "fps": args.fps},
        "headless": args.headless,
    }

    try:
        accepted = {
            "width": bool(camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)),
            "height": bool(camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)),
            "fps": bool(camera.set(cv2.CAP_PROP_FPS, args.fps)),
        }
        reported_fps = camera.get(cv2.CAP_PROP_FPS)
        report["backend"] = camera.getBackendName()
        report["property_set_returned"] = accepted
        report["camera_reported_fps"] = reported_fps if math.isfinite(reported_fps) else None
        print(f"Backend: {report['backend']}; camera reported FPS: {report['camera_reported_fps']}")
        print("Q/Esc trong cửa sổ để thoát; Ctrl+C trong terminal để dừng.")
        while time.perf_counter() - started < args.seconds:
            ok, frame = camera.read()
            if not ok or frame is None or frame.size == 0:
                raise RuntimeError("Camera mở được nhưng không đọc được frame")
            now = time.perf_counter()
            if first_time is None:
                first_time = now
                actual_size = {"width": int(frame.shape[1]), "height": int(frame.shape[0])}
                print(f"Actual frame size: {actual_size['width']}x{actual_size['height']}")
            if last_time is not None:
                intervals.append(now - last_time)
            last_time = now
            frames += 1
            frame_times.append(now)
            while len(frame_times) > 1 and now - frame_times[0] > 2:
                frame_times.popleft()
            span = frame_times[-1] - frame_times[0]
            loop_fps = (len(frame_times) - 1) / span if span > 0 else 0
            if not args.headless:
                labels = [
                    f"Loop FPS: {loop_fps:.1f}",
                    f"Elapsed: {now - started:.1f}s | frames: {frames}",
                    "Q / Esc: quit",
                ]
                for row, text in enumerate(labels):
                    cv2.putText(frame, text, (12, 28 + row * 28), cv2.FONT_HERSHEY_SIMPLEX,
                                0.65, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.imshow(title, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    status = "user_stopped"
                    break
                if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                    status = "window_closed"
                    break
    except KeyboardInterrupt:
        status = "interrupted"
    except (RuntimeError, cv2.error) as error:
        status = "error"
        error_message = str(error)
    finally:
        camera.release()
        if not args.headless:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass

    duration = time.perf_counter() - started
    observed_span = last_time - first_time if frames >= 2 else 0
    report.update({
        "status": status,
        "error": error_message,
        "frames": frames,
        "elapsed_seconds": round(duration, 3),
        "actual_size": actual_size,
        "loop_fps": round((frames - 1) / observed_span, 2) if observed_span > 0 else None,
        "max_frame_interval_ms": round(max(intervals) * 1000, 2) if intervals else None,
        "intervals_over_200ms": sum(interval > 0.2 for interval in intervals),
        "measurement_note": "Loop FPS = tốc độ đọc + xử lý/hiển thị; không đo timestamp phơi sáng của cảm biến.",
    })
    save_report(report)
    print(f"Status: {status}; frames: {frames}; loop FPS: {report['loop_fps']}")
    if error_message:
        print(f"Error: {error_message}", file=sys.stderr)
        return 1
    if frames < 2:
        print("Chưa có đủ frame để đo FPS. Chạy lại đủ 30 giây.", file=sys.stderr)
        return 1
    return 0


def main():
    args = arguments()
    try:
        cv2, np = dependencies()
        info = environment(cv2, np)
        if args.check:
            print("OK: import thư viện thành công. Camera/cửa sổ vẫn cần kiểm tra bằng lần chạy thực tế.")
            return 0
        return measure(args, cv2, info)
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
