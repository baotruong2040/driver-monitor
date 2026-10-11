# Driver Monitor — học và xây dựng từ đầu

## Mục tiêu

Hệ thống quan sát tài xế bằng camera, tổng hợp biểu hiện mắt, miệng và đầu trong cửa sổ trượt 20–30 giây để ước lượng mức buồn ngủ. Một luồng độc lập cảnh báo ngay khi quan sát được mắt nhắm kéo dài hoặc biểu hiện đầu gục đáng tin cậy.

Phiên bản đầu học trạng thái hiện tại: tỉnh táo, giảm cảnh giác, buồn ngủ. Dự đoán một sự kiện ngủ gật trong tương lai là giai đoạn riêng, cần dữ liệu có thời điểm bắt đầu sự kiện. Biểu hiện hình ảnh chưa tự xác nhận microsleep theo nhãn sinh lý EEG.

## Lộ trình

| Bước | Làm gì | Hiểu gì | Điều kiện hoàn thành |
|---|---|---|---|
| 1 — gói này | Tạo môi trường và đọc webcam | Frame, FPS, timestamp, môi trường ảo | Camera chạy ổn 30 giây và có báo cáo |
| 2 | Chạy MediaPipe Face Landmarker | Phát hiện mặt, landmarks, tracking và vùng hợp lệ | Bám được mắt/miệng/đầu, nhận biết mất quan sát |
| 3 | Nhận biết mở/nhắm và từng lần chớp | EAR, hysteresis, thời lượng theo timestamp | Chớp ngắn và nhắm dài được phân biệt |
| 4 | Nhận biết ngáp và tư thế đầu | MAR, chuỗi sự kiện, pitch/yaw/roll | Có log dấu hiệu và kiểm tra các tình huống dễ nhầm |
| 5 | Tổng hợp cửa sổ trượt | Tần suất, phân bố thời lượng, xu hướng, dữ liệu thiếu | Đặc trưng 30 giây cập nhật mỗi giây |
| 6 | Chuẩn bị dữ liệu/nhãn | Nhãn quan sát khác nhãn buồn ngủ; chia theo người | Train/val/test tách người, có kiểm tra nhãn |
| 7 | Train XGBoost baseline, sau đó GRU | Học thống kê so với học chuỗi, ablation | So sánh mắt/miệng/đầu trên cùng split |
| 8 | Tích hợp cảnh báo và đánh giá liên tục | Ngưỡng, hysteresis, báo giả/giờ, độ trễ | Báo cáo hiệu quả toàn hệ thống, không chỉ accuracy |

Các bước sau được bổ sung khi bước trước chạy ổn. Gói này chỉ triển khai bước 1.

## Chuẩn bị

- Máy CachyOS + KDE, terminal, kết nối mạng để cài công cụ và thư viện.
- Webcam tích hợp hoặc USB. Thử webcam có sẵn trước khi mua thiết bị.
- Ngồi yên, camera chắc chắn, gần ngang mặt; nhìn rõ hai mắt và miệng; ánh sáng phía trước, tránh cửa sổ sáng phía sau.
- CPU đủ để thử đọc camera. Chưa cần cấu hình CUDA, PyTorch, YOLO hay tải dataset ở bước 1.
- Chuẩn bị một tệp ghi chú cho camera, độ phân giải, ánh sáng, kính, FPS đo được và lỗi gặp phải.

## Cài công cụ hệ thống

```bash
sudo pacman -S --needed uv unzip v4l-utils
```

`uv` quản lý Python và môi trường; `unzip` giải nén; `v4l-utils` cung cấp công cụ kiểm tra webcam Linux. Nếu pacman báo lỗi mirror/404, xử lý lỗi cài gói trước khi tiếp tục; không chạy `pacman -Sy` riêng.

## Đặt dự án

Tải `driver-monitor-step01.zip`, đặt trong `~/Downloads`. Nếu trình duyệt lưu ở nơi khác, thay đường dẫn bên dưới bằng đường dẫn thực tế.

```bash
mkdir -p ~/Projects
unzip -n ~/Downloads/driver-monitor-step01.zip -d ~/Projects
cd ~/Projects/driver-monitor
```

Gói có `README.md`, `requirements.txt`, `check_camera.py`. `-n` giữ tệp đã có. Nếu thư mục `~/Projects/driver-monitor` chứa dự án khác, chọn thư mục giải nén mới để tránh trộn mã.

## Tạo môi trường Python riêng

```bash
uv python install 3.12
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python check_camera.py --check
```

Chạy lệnh trong thư mục chứa `check_camera.py`. `.venv/bin/python` chọn đúng Python của dự án; không cần activate. Sau mỗi lần mở terminal mới, `cd ~/Projects/driver-monitor` rồi tiếp tục dùng đường dẫn này. Không dùng `sudo pip`.

Chọn Python 3.12 và cố định phiên bản thư viện để giữ môi trường nhất quán. Đây là lựa chọn cho bài học, không tuyên bố là các phiên bản mới nhất. Gói `opencv-contrib-python` chứa OpenCV cùng các mô-đun bổ sung, và phù hợp với dependency của MediaPipe dự định dùng ở bước 2; mã vẫn import bằng `cv2`. OpenCV mở camera/hiển thị ảnh; NumPy biểu diễn ảnh bằng mảng số. `uv` là công cụ môi trường, không phải model AI.

Kết quả kiểm tra phải có Python 3.12.x, OpenCV 4.11.0, NumPy 2.2.6 và dòng `OK`. `--check` chỉ kiểm tra import, chưa kiểm tra phần cứng và cửa sổ.

## Kiểm tra camera

```bash
v4l2-ctl --list-devices
.venv/bin/python check_camera.py --camera 0 --seconds 30
```

Đóng ứng dụng khác đang dùng webcam trước khi chạy. Cửa sổ hiển thị ảnh và FPS vòng lặp; chạy đủ 30 giây. Q/Esc thoát sớm, Ctrl+C dừng từ terminal. Khi dừng bình thường, chương trình tạo `reports/camera_....json` và in đường dẫn.

Chương trình không lưu ảnh hay video. Báo cáo chứa phiên bản môi trường, nguồn camera, cấu hình yêu cầu, kích thước frame thực, số frame, FPS vòng lặp và khoảng cách lớn nhất giữa hai lần đọc frame thành công.

## Hiểu cách chương trình hoạt động

1. `arguments()` đọc lựa chọn dòng lệnh và kiểm tra giá trị.
2. `dependencies()` nạp OpenCV và NumPy; `environment()` in môi trường đang dùng.
3. `VideoCapture` mở camera. `set()` yêu cầu kích thước/FPS; phần cứng có thể không đáp ứng.
4. `read()` nhận một frame: mảng có dạng `(chiều cao, chiều rộng, 3 kênh BGR)`.
5. `time.perf_counter()` đo thời gian trôi qua bằng đồng hồ đơn điệu. Đây là timestamp sau khi đọc, không phải timestamp phơi sáng của cảm biến.
6. Chương trình tính FPS từ các thời điểm đọc frame, vẽ chữ và hiển thị bằng `imshow`/`waitKey`.
7. `release()` trả camera; chương trình ghi JSON để đối chiếu các lần thử.

FPS yêu cầu 30 không bảo đảm camera trả 30 frame mỗi giây. FPS vòng lặp bao gồm tốc độ đọc, xử lý và hiển thị; không tự chứng minh độ trễ từ cảnh thật tới cửa sổ. Với bước sau, mỗi thời lượng chớp/ngáp sẽ tính bằng timestamp, tránh giả định mọi frame cách nhau đúng 1/30 giây.

Ví dụ 30 giây × 30 FPS gần 900 frame, nhưng không cần đúng 900 vì có thời gian khởi động, phần cứng có thể thương lượng FPS khác và vòng lặp có độ trễ.

## Nếu có lỗi

### Camera không mở

```bash
v4l2-ctl --list-devices
.venv/bin/python check_camera.py --camera 1 --seconds 30
```

Chỉ số camera phải khớp thiết bị thực. Một webcam có thể cung cấp nhiều `/dev/video*`, trong đó không phải node nào cũng chứa ảnh. Xem định dạng của node ảnh, ví dụ:

```bash
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

Không chạy chương trình bằng sudo hoặc đổi quyền toàn bộ `/dev/video*` để thử sửa lỗi. Gửi lỗi đầy đủ và danh sách thiết bị để xác định nguyên nhân.

### Lỗi Qt/Wayland khi mở cửa sổ

```bash
QT_QPA_PLATFORM=xcb .venv/bin/python check_camera.py --camera 0 --seconds 30
```

Lệnh này chỉ chọn backend Qt cho lần chạy đó và cần XWayland hoạt động. Có thể tách kiểm tra đọc camera khỏi kiểm tra cửa sổ:

```bash
.venv/bin/python check_camera.py --camera 0 --seconds 30 --headless
```

Nếu headless chạy nhưng cửa sổ lỗi, phần đọc camera và phần hiển thị đang có kết quả khác nhau. Không thay driver GPU trước khi xác định lỗi.

### FPS thấp

Thử tăng ánh sáng phía trước và xem `--list-formats-ext` để biết camera hỗ trợ độ phân giải/FPS nào. Mốc 25–30 FPS là mục tiêu thử nghiệm để quan sát chớp mắt; thấp hơn chưa tự có nghĩa chương trình sai. Ghi lại FPS và hiện tượng giật/đứng hình.

### Thư viện không import được

```bash
uv pip check --python .venv/bin/python
.venv/bin/python check_camera.py --check
```

Dùng cùng môi trường cho install và run. Không cài đồng thời các biến thể `opencv-python`, `opencv-contrib-python` và các bản `headless` trong cùng môi trường; chúng dùng chung namespace `cv2`. Bản headless không phục vụ `imshow`.

## Điều kiện hoàn thành bước 1

- `--check` thành công trong Python của dự án.
- Cửa sổ camera chạy đủ khoảng 30 giây, ảnh đủ rõ để nhìn mắt/miệng và không bị đứng hình kéo dài.
- Có báo cáo JSON; biết FPS yêu cầu, FPS camera báo và FPS vòng lặp là các thông tin khác nhau.
- Ghi lại FPS, độ phân giải thực và lỗi/hiện tượng nếu có.

Gửi output terminal, báo cáo JSON và nhận xét ảnh có mượt/rõ không. Nếu chưa chạy được, gửi nguyên lỗi ở lệnh đầu tiên bị lỗi. Bước tiếp theo là Face Landmarker, chưa phải training.

## Tài liệu gốc

- uv/Python: https://docs.astral.sh/uv/guides/install-python/
- uv/môi trường: https://docs.astral.sh/uv/pip/environments/
- OpenCV VideoCapture: https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html
- Gói OpenCV và lựa chọn GUI/headless: https://pypi.org/project/opencv-python/4.11.0.86/
- MediaPipe Face Landmarker, dùng ở bước 2: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
- UTA-RLDD và nhãn ba mức, dùng ở bước dữ liệu: https://sites.google.com/view/utarldd/home
- Baseline đặc trưng nhiều vùng, cửa sổ 30 giây: https://doi.org/10.3390/info16040294
