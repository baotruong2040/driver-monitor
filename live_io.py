"""Latest-frame capture and alarm scheduler with stale-inference cutoff."""
import threading
import time


class LatestCamera:
    def __init__(self, capture):
        self.capture = capture
        self.condition = threading.Condition()
        self.stopping = threading.Event()
        self.sequence = self.received = 0
        self.frame = self.captured_at = self.error = None
        self.thread = threading.Thread(target=self._run, name='camera-reader', daemon=True)
        self.thread.start()

    def _run(self):
        try:
            while not self.stopping.is_set():
                ok, frame = self.capture.read()
                if not ok or frame is None or frame.size == 0:
                    raise RuntimeError('Camera stopped returning frames')
                with self.condition:
                    self.sequence += 1
                    self.received += 1
                    self.frame, self.captured_at = frame, time.monotonic()
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = str(exc)
                self.condition.notify_all()
        finally:
            self.capture.release()

    def read(self, after, timeout=.2):
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > after or self.error or self.stopping.is_set(), timeout)
            if self.error:
                raise RuntimeError(self.error)
            if self.sequence <= after:
                return None
            return self.sequence, self.captured_at, self.frame

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=1.)
        # A blocked V4L2 read is left to this daemon/process teardown; never
        # release VideoCapture concurrently with read(), which can crash OpenCV.


class AlarmPattern:
    def __init__(self, stale_seconds=.2):
        self.stale_seconds = stale_seconds
        self.urgent = False
        self.fresh_at = float('-inf')
        self.urgent_start = None

    def publish(self, now, risk, captured_at=None):
        self.fresh_at = now if captured_at is None else captured_at
        urgent = risk['alarm_active']
        if urgent and not self.urgent:
            self.urgent_start = now
        self.urgent = urgent

    def active(self, now):
        if now - self.fresh_at > self.stale_seconds:
            return False
        if self.urgent:
            return (now - self.urgent_start) % .5 < .3
        return False

    def reset(self):
        self.__init__(self.stale_seconds)


class AlarmController:
    """Only the worker touches serial; never refresh from stale AI results."""
    def __init__(self, port, stale_seconds=.2, transport_factory=None):
        if transport_factory is None:
            from usb_alarm import USBAlarm
            transport_factory = USBAlarm
        self.transport = None
        self.error = None
        self.port = port
        self.pattern = AlarmPattern(stale_seconds)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        try:
            self.transport = transport_factory(port)
        except Exception as exc:
            self.error = str(exc)
        self.thread = threading.Thread(target=self._run, name='cdc-alarm', daemon=True)
        self.thread.start()

    def publish(self, risk, captured_at):
        with self.lock:
            self.pattern.publish(time.monotonic(), risk, captured_at)

    def reset(self):
        with self.lock:
            self.pattern.reset()

    def _run(self):
        try:
            while not self.stop.is_set() and self.transport is not None:
                with self.lock:
                    active = self.pattern.active(time.monotonic())
                self.transport.update(active)
                self.stop.wait(.02)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if self.transport is not None:
                try:
                    self.transport.close()
                except Exception as exc:
                    self.error = str(exc)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1.)

    @property
    def requested_active(self):
        with self.lock:
            return bool(self.transport is not None and not self.error and self.pattern.active(time.monotonic()))

    @property
    def status(self):
        return 'ERROR: ' + self.error if self.error else 'CONNECTED (no firmware ACK)'
