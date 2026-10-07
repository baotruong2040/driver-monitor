"""Read the newest USB UVC frame for PC AI without an accumulating queue.

Requires FFmpeg in PATH. read_latest() returns packed BGR24 bytes; frame.bgr()
returns a NumPy array when NumPy is installed. The camera is a standard UVC
device and can also be read by OpenCV/DirectShow without this helper.
"""
import argparse
from collections import deque
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import threading
import time


@dataclass(frozen=True)
class Frame:
    sequence: int
    received_at: float
    width: int
    height: int
    data: bytes

    def bgr(self):
        import numpy as np
        return np.frombuffer(self.data, dtype=np.uint8).reshape(self.height, self.width, 3)


class USBCamera:
    def __init__(self, device="UVC CAM1", width=1280, height=720, fps=None):
        self.device, self.width, self.height, self.fps = device, width, height, fps
        self._condition = threading.Condition()
        self._latest = None
        self._error = None
        self._stop = threading.Event()
        self._logs = deque(maxlen=20)
        self._process = None
        self._threads = []
        self.frames_received = 0
        self.first_received_at = None
        self.last_received_at = None
        self.gaps = deque(maxlen=512)
        self.decode_error_lines = 0
        self.decode_error_examples = deque(maxlen=8)

    def start(self):
        executable = shutil.which("ffmpeg")
        if executable is None:
            raise RuntimeError("Install FFmpeg and add it to PATH.")
        if self._process is not None:
            raise RuntimeError("Camera is already started.")
        if self.fps is None:
            self.fps = self.detect_fps(executable)
            # DirectShow may still be releasing the capability-probe graph.
            time.sleep(0.2)
        command = [executable, "-hide_banner", "-loglevel", "warning",
                   "-f", "dshow", "-rtbufsize", "256k", "-video_size",
                   f"{self.width}x{self.height}", "-framerate", str(self.fps),
                   "-use_video_device_timestamps", "false",
                   "-vcodec", "mjpeg", "-threads", "1", "-analyzeduration", "0",
                   "-probesize", "32", "-i", f"video={self.device}",
                   "-an", "-threads", "1", "-fps_mode", "passthrough",
                   "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
        self._process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, bufsize=0,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self._threads = [threading.Thread(target=self._read, daemon=True),
                         threading.Thread(target=self._read_logs, daemon=True)]
        for thread in self._threads:
            thread.start()
        return self

    def detect_fps(self, executable=None):
        executable = executable or shutil.which("ffmpeg")
        if executable is None:
            raise RuntimeError("Install FFmpeg and add it to PATH.")
        options = subprocess.run(
            [executable, "-hide_banner", "-list_options", "true", "-f", "dshow",
             "-i", f"video={self.device}"], capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        text = options.stderr.decode("utf-8", errors="replace")
        rates = re.findall(rf"vcodec=mjpeg\s+min s={self.width}x{self.height} fps=([0-9.]+)", text)
        if not rates:
            raise RuntimeError("Cannot detect the camera MJPEG frame rate.\n" + text)
        return max(float(rate) for rate in rates)

    def _read_logs(self):
        for line in self._process.stderr:
            message = line.decode("utf-8", errors="replace").strip()
            self._logs.append(message)
            if re.search(r"error|invalid|corrupt|overread|bad vlc|no jpeg data|eoi missing",
                         message, re.IGNORECASE):
                self.decode_error_lines += 1
                self.decode_error_examples.append(message)

    def _read(self):
        size = self.width * self.height * 3
        try:
            while not self._stop.is_set():
                data = bytearray(size)
                view = memoryview(data)
                at = 0
                while at < size and not self._stop.is_set():
                    count = self._process.stdout.readinto(view[at:])
                    if not count:
                        raise RuntimeError("USB camera capture ended.")
                    at += count
                if self._stop.is_set():
                    break
                now = time.monotonic()
                with self._condition:
                    self.frames_received += 1
                    if self.first_received_at is None:
                        self.first_received_at = now
                    if self.last_received_at is not None:
                        self.gaps.append(now - self.last_received_at)
                    self.last_received_at = now
                    self._latest = Frame(self.frames_received, now, self.width, self.height, bytes(data))
                    self._condition.notify_all()
        except (OSError, RuntimeError) as error:
            with self._condition:
                if not self._stop.is_set():
                    self._error = error
                self._condition.notify_all()

    def read_latest(self, after_sequence=0, timeout=5):
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._latest is None or self._latest.sequence <= after_sequence:
                if self._error is not None:
                    raise RuntimeError(str(self._error) + "\n" + "\n".join(self._logs))
                if self._stop.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._latest

    def close(self):
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            for thread in self._threads:
                thread.join(timeout=2)
            self._process.stdout.close()
            self._process.stderr.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="UVC CAM1")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--fps", type=float, help="Requested device FPS; default detects the current USB mode.")
    parser.add_argument("--ai-delay-ms", type=float, default=0,
                        help="Simulate slow AI; the receiver must keep reading and discard older frames.")
    parser.add_argument("--save", type=Path, help="Save one received frame as a PNG (requires Pillow).")
    args = parser.parse_args()
    if args.seconds <= 0 or args.ai_delay_ms < 0 or (args.fps is not None and args.fps <= 0):
        parser.error("seconds/fps must be positive and ai-delay-ms nonnegative")
    with USBCamera(args.device, fps=args.fps) as camera:
        sequence = processed = skipped = 0
        newest = None
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            image = camera.read_latest(sequence)
            if image is None:
                raise RuntimeError("No USB video received within five seconds.")
            skipped += image.sequence - sequence - 1
            sequence = image.sequence
            newest = image
            processed += 1
            if args.ai_delay_ms:
                time.sleep(args.ai_delay_ms / 1000)
        if args.save and newest:
            from PIL import Image
            args.save.parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("RGB", (newest.width, newest.height), newest.data,
                            "raw", "BGR").save(args.save)
        span = (camera.last_received_at - camera.first_received_at
                if camera.frames_received > 1 else 0)
        result = {"device": args.device, "dimensions": [camera.width, camera.height],
                  "requested_fps": camera.fps,
                  "frames_received": camera.frames_received, "frames_processed": processed,
                  "frames_skipped_for_slow_ai": skipped,
                  "receive_fps": round((camera.frames_received - 1) / span, 2) if span else 0,
                  "decode_error_log_lines": camera.decode_error_lines,
                  "decode_error_examples": list(camera.decode_error_examples),
                  "max_frame_gap_ms": round(max(camera.gaps, default=0) * 1000, 1)}
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
