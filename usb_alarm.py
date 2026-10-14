"""CDC alarm transport. Install pyserial in the PC application's environment."""
import time


class USBAlarm:
    """Call update on every live inference frame; refresh active alarm every 0.5 s."""

    def __init__(self, port):
        import serial
        self.serial = serial.Serial(port, 115200, timeout=0, write_timeout=0.2)
        self.state = None
        self.sent_at = float('-inf')
        try:
            self.update(False)
        except Exception:
            self.serial.close()
            raise

    def update(self, active):
        active = bool(active)
        now = time.monotonic()
        if active != self.state or (active and now - self.sent_at >= 0.5):
            command = b'ALARM 1\n' if active else b'ALARM 0\n'
            if self.serial.write(command) != len(command):
                raise IOError('Incomplete alarm command')
            self.state = active
            self.sent_at = now

    def close(self):
        try:
            if self.serial.write(b'ALARM 0\n') != len(b'ALARM 0\n'):
                raise IOError('Incomplete alarm shutdown command')
        finally:
            self.serial.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Test passive buzzer over USB CDC')
    parser.add_argument('--port', required=True)
    args = parser.parse_args()
    with USBAlarm(args.port) as alarm:
        end = time.monotonic() + 3
        while time.monotonic() < end:
            alarm.update(True)
            time.sleep(0.1)
