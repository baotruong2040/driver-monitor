"""Khôi phục model Google phiên bản 1 nếu tệp model bị thiếu."""

import hashlib
from pathlib import Path
import tempfile
import urllib.request


URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
SIZE = 3758596


def verify(path):
    data = path.read_bytes()
    return len(data) == SIZE and hashlib.sha256(data).hexdigest() == SHA256


def main():
    path = Path(__file__).resolve().parent / "models" / "face_landmarker.task"
    if path.exists():
        if not verify(path):
            raise RuntimeError("Tệp model hiện có khác bản đã kiểm tra. Đổi tên tệp đó rồi chạy lại.")
        print(f"OK: model đã có và đúng checksum: {path}")
        return
    path.parent.mkdir(exist_ok=True)
    temporary = None
    try:
        with urllib.request.urlopen(URL, timeout=30) as response:
            data = response.read(SIZE + 1)
        if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA256:
            raise RuntimeError("Model tải về không khớp kích thước/checksum")
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        temporary.replace(path)
        temporary = None
        print(f"OK: đã tải model: {path}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(f"Error: {error}")
