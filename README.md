# Driver Monitor — Hướng dẫn chạy app

Ứng dụng Python theo dõi mắt, miệng và tư thế đầu bằng MediaPipe, hiển thị camera bằng OpenCV và điều khiển còi qua USB CDC khi dùng ESP32-S3. Điểm chạy chính là `app.py`.

## 1. Chuẩn bị

- Python 3.12 (phiên bản đã kiểm tra trên môi trường phát triển), Git.
- Webcam hoặc ESP32-S3 có firmware cung cấp camera UVC; có thể dùng video để thử.
- Muốn phát còi: firmware ESP32 phải hỗ trợ lệnh `ALARM 1` / `ALARM 0` qua USB CDC ở 115200 baud. Firmware và hướng dẫn nạp không nằm trong repo này; app không tự nạp firmware.

## 2. Tải mã nguồn và cài thư viện

```sh
git clone --branch webcam_plus_ai https://github.com/baotruong2040/driver-monitor.git
cd driver-monitor
```

**Linux / macOS:**

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Windows PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Nếu PowerShell chặn kích hoạt môi trường, dùng trực tiếp `.\.venv\Scripts\python.exe` thay cho `python` trong các lệnh sau.

Kiểm tra model và khả năng suy luận, chưa cần camera:

```sh
python -B download_face_model.py
python -B app.py --check
```

Model có sẵn ở `models/face_landmarker.task`; script kiểm tra checksum và tải lại nếu tệp bị thiếu. Kết quả kiểm tra mong đợi: `OK: model inference; faces=0 (black image expects 0)`.

## 3. Chạy ứng dụng

### Webcam thông thường, không dùng còi

```sh
python -B app.py --camera 0 --alarm-port none
```

Nếu mở nhầm camera, đổi `0` thành `1`, `2`…

### Camera ESP32-S3 và còi

Trên Linux, nếu thiết bị có serial `AI-DETECT-001` và đường dẫn UVC/CDC đúng với cấu hình app:

```sh
python -B app.py
```

App tự tìm thiết bị qua `/dev/v4l/by-id` và `/dev/serial/by-id`. Nếu không tìm được camera, hãy chỉ định thiết bị; nếu không mở được CDC, nhận diện vẫn chạy nhưng còi không hoạt động.

Ví dụ Linux (thay bằng cổng thực tế):

```sh
python -B app.py --camera /dev/video5 --alarm-port /dev/ttyACM0
```

Ví dụ Windows:

```powershell
python -B app.py --camera 0 --alarm-port COM5
```

Windows/macOS cần chỉ định camera và cổng nối tiếp, hoặc dùng `--alarm-port none`. Trên macOS, cổng nối tiếp thường có dạng `/dev/cu.usbmodem...`; môi trường macOS chưa được kiểm tra trong lần cập nhật này. Số camera và cổng có thể đổi sau khi cắm lại thiết bị. Đóng ứng dụng đang giữ camera hoặc serial trước khi chạy.

Kiểm tra riêng camera/CDC trong 30 giây, có gửi lệnh bật còi:

```sh
python -B app.py --hardware-test --headless
```

Nếu không dùng tự tìm thiết bị, thêm `--camera` và `--alarm-port` như ví dụ trên. Bài kiểm tra không chạy AI và không nhận ACK từ firmware; cần quan sát camera/còi thực tế để xác nhận phần cứng.

### Video có sẵn

```sh
python -B app.py --video data/test.mp4
```

Có thể thay bằng đường dẫn video của bạn. Chế độ video luôn tắt còi và mặc định đọc đến hết video.

### Chạy không mở cửa sổ

```sh
python -B app.py --camera 0 --alarm-port none --headless --seconds 30
```

Bỏ `--seconds` để chạy tới khi dừng. Camera mặc định yêu cầu MJPG 1280×720, 30 FPS; tốc độ thực tế phụ thuộc thiết bị và máy tính.

## 4. Sử dụng khi app đang chạy

1. Giữ mắt mở tự nhiên, miệng khép và đầu nhìn thẳng trong 8 giây quan sát hợp lệ để hiệu chỉnh (ít nhất 60 mẫu). Nếu đầu chuyển động quá nhiều, app tự bắt đầu lại hiệu chỉnh.
2. Khi hiệu chỉnh xong, theo dõi trạng thái mắt, miệng, góc đầu và trạng thái còi trên cửa sổ.
3. Nhấn **C** để hiệu chỉnh lại; **Q** hoặc **Esc** để thoát. Trong terminal hoặc chế độ headless, dùng **Ctrl+C**.

Còi bật khi hai mắt nhắm liên tục ít nhất **1,5 giây**, hoặc giữ cúi trước ít nhất **10° trong 0,75 giây** sau khi quan sát tư thế nghỉ. Nhịp còi là 0,3 giây bật / 0,2 giây tắt. Ngáp, nghiêng đầu và chuỗi gật rồi dựng đầu chỉ được hiển thị/ghi log, không tự bật còi. Mất quan sát làm ngắt chuỗi liên tục; hiệu chỉnh lại và thoát gửi lệnh tắt còi.

Đây là các quy tắc quan sát, chưa có model phân loại buồn ngủ đã huấn luyện. Mở miệng khi nói cũng có thể được ghi nhận là miệng mở; cúi chủ động đủ ngưỡng có thể kích hoạt cảnh báo.

## 5. Tùy chỉnh và báo cáo

Xem đầy đủ tham số:

```sh
python -B app.py --help
```

Nếu cúi xuống nhưng pitch hiển thị âm:

```sh
python -B app.py --camera 0 --alarm-port none --pitch-sign -1
```

Ví dụ thay ngưỡng nhắm mắt:

```sh
python -B app.py --camera 0 --alarm-port none --eye-closed-seconds 2
```

App tự tạo báo cáo trong `reports/`:

- `app_<thời_gian>.json`: cấu hình, kết quả phiên chạy, FPS và trạng thái CDC.
- `app_<thời_gian>.csv`: sự kiện và quyết định cảnh báo.
- `app_<thời_gian>_frames.csv`: các đặc trưng và trạng thái theo frame.
- `hardware_<thời_gian>.json`: kết quả chế độ kiểm tra phần cứng.

## 6. Xử lý lỗi thường gặp

| Lỗi | Cách xử lý |
|---|---|
| `ESP32 camera not found` | Dùng `--camera 0` hoặc đường dẫn camera thực tế. |
| `Cannot open camera/video` | Kiểm tra index/đường dẫn, quyền camera và đóng ứng dụng khác đang dùng thiết bị. |
| Lỗi CDC / không phát còi | Kiểm tra `--alarm-port`, quyền truy cập cổng và firmware hỗ trợ lệnh ALARM. Chọn `--alarm-port none` nếu chỉ cần nhận diện. |
| `Missing/invalid model` | Chạy `python -B download_face_model.py`. Nếu checksum model hiện có sai, đổi tên tệp đó rồi chạy lại. |
| Không mở được cửa sổ OpenCV | Chạy trong phiên desktop hoặc thêm `--headless`; môi trường server có thể thiếu thư viện hệ thống cho OpenCV. |
| Hiệu chỉnh mãi chưa xong | Tăng ánh sáng, để toàn bộ mặt trong khung hình, giữ mắt mở và đầu ổn định. |

## 7. Kiểm tra logic của dự án

```sh
python -B -m unittest test_app test_behavior test_ear_windows test_eye_events test_windows
```

Kiểm thử logic không thay thế việc thử camera và còi trên thiết bị thực tế.
