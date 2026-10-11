# Bước 2 — theo dõi khuôn mặt và kiểm tra vùng quan sát

## Kết quả bước 1 của bạn

Camera ACER HD ở `/dev/video0`, backend V4L2; 640×480; 884 frame trong 30,032 giây; FPS vòng lặp 29,75. Khoảng cách lớn nhất giữa hai frame 60,73 ms, không có khoảng vượt 200 ms. Chương trình báo completed, không có error. Đây là nền tảng phù hợp để thử thêm model; chưa đo chất lượng nhận diện.

Python thực dùng là `/home/riyaki/Documents/AI/driver-monitor/.venv/bin/python`, phiên bản 3.12.15. Số 3.14.7 trên prompt là thông tin khác của shell, không phải interpreter đã chạy lệnh này.

Dòng Qt thiếu plugin Wayland chưa làm thất bại luồng đọc camera trong báo cáo này. Dùng `QT_QPA_PLATFORM=xcb` cho lệnh có cửa sổ, dựa trên backend Qt5 của gói OpenCV; lựa chọn này cần XWayland hoạt động và chỉ áp dụng cho lần chạy đó.

## Mục tiêu bước 2

- Dùng model đã huấn luyện sẵn để lấy landmarks trên từng frame.
- Hiển thị đường bao mắt/miệng và điểm tham chiếu đầu.
- Quan sát FPS sau khi thêm suy luận.
- Nhận biết mất mặt và kiểm tra hình học sơ bộ khi vùng quan sát quá nhỏ/ngoài khung.
- Hiểu input, output và timestamp của model.

Bước này chưa tính EAR/MAR, chưa đếm chớp mắt/ngáp, chưa tính góc đầu, chưa train và chưa phát cảnh báo buồn ngủ.

## Những tệp được thêm

| Tệp | Vai trò |
|---|---|
| `requirements-step02.txt` | Bổ sung MediaPipe 0.10.32, giữ các phiên bản bước 1 |
| `models/face_landmarker.task` | Model Face Landmarker Google, float16/version 1, đã kèm trong gói |
| `download_face_model.py` | Kiểm tra hoặc khôi phục đúng bản model nếu cần |
| `face_geometry.py` | Chọn điểm mắt/miệng/đầu; đổi tọa độ; kiểm tra và vẽ |
| `check_face.py` | Camera → RGB → model → kiểm tra hình học → hiển thị/log |
| `README-step02.md` | Bài hướng dẫn này |

Giữ `check_camera.py`, `requirements.txt` và báo cáo cũ. Gói bổ sung không thay những tệp đó. Gói bước 2 cần thư mục dự án bước 1 đã có.

## Cài và kiểm tra

Tải `driver-monitor-step02.zip` vào Downloads. Nếu vị trí tải khác, thay đường dẫn thực tế.

```bash
unzip -n ~/Downloads/driver-monitor-step02.zip -d /home/riyaki/Documents/AI
cd /home/riyaki/Documents/AI/driver-monitor
sudo pacman -S --needed portaudio
uv pip install --python .venv/bin/python -r requirements-step02.txt
uv pip check --python .venv/bin/python
.venv/bin/python download_face_model.py
.venv/bin/python check_face.py --check
```

Không tạo lại `.venv`. Lệnh `download_face_model.py` chỉ kiểm tra checksum khi model trong gói đã có; không tải lại và không cần mạng trong trường hợp đó. File model là dữ liệu đã huấn luyện, còn thư viện MediaPipe cung cấp mã chạy model: cần cả hai.

MediaPipe có dependency `sounddevice`; trên Linux thư viện này có thể cần PortAudio của hệ thống. Ta cài `portaudio` để dependency đầy đủ. Bước này không mở microphone hoặc phát âm thanh.

`--check` phải in MediaPipe 0.10.32, CPU, dòng model chạy trên ảnh đen và faces=0. Ảnh đen chỉ kiểm tra nạp/chạy model; không đo độ chính xác. Một số log INFO/WARNING từ MediaPipe có thể xuất hiện: nếu lệnh báo lỗi hoặc không có OK, gửi toàn bộ output để kiểm tra; không tự coi mọi warning đều vô hại.

## Lần chạy A — nhìn thẳng 30 giây

```bash
QT_QPA_PLATFORM=xcb .venv/bin/python check_face.py --camera 0 --seconds 30
```

Ngồi như bước 1, chỉ một người trước camera. Giữ mặt tương đối chính diện và đủ ánh sáng. Quan sát đường bao có bám đúng mắt/miệng không, không chỉ nhìn trạng thái OK. Mắt trái theo model màu xanh lá, mắt phải màu cyan, miệng màu cam, các điểm tham chiếu đầu màu trắng. Ảnh không lật gương trong mã; vị trí trái/phải trên màn hình có thể khác cách nhìn của bạn.

- Q/Esc thoát sớm.
- M bật/tắt toàn bộ điểm landmarks để xem lưới mặt.
- Chạy đủ 30 giây để so FPS với bước 1.

## Lần chạy B — kiểm tra hành vi trong 60 giây

```bash
QT_QPA_PLATFORM=xcb .venv/bin/python check_face.py --camera 0 --seconds 60
```

| Thời gian gợi ý | Hành động | Quan sát |
|---|---|---|
| 0–15 s | Nhìn thẳng | Đường bao bám mặt, phần lớn frame có hình học phù hợp |
| 15–25 s | Chớp mắt và mở/khép miệng | Các điểm đi theo chuyển động; chưa có nhãn OPEN/CLOSED/YAWN |
| 25–35 s | Quay/cúi đầu nhẹ | Theo dõi điểm có bám đúng không; vùng có thể nhỏ/ngoài khung |
| 35–45 s | Ra khỏi khung hình | Chuyển NO_FACE sau khi model không còn trả khuôn mặt |
| 45–60 s | Trở lại, nhìn thẳng | Model lấy lại landmarks |

Không yêu cầu trạng thái LIMITED xuất hiện ở mọi góc quay. Nó chỉ phụ thuộc kiểm tra tọa độ/kích thước hiện tại. Không yêu cầu điểm biến mất khi che mắt/miệng: model có thể vẫn ước lượng điểm trên vùng bị che; đây là hạn chế cần nhận biết bằng quan sát thủ công ở bước này.

Thao tác chớp/mở miệng ở đây chỉ kiểm tra tracking, không phải dữ liệu có nhãn buồn ngủ.

## Hiểu model làm gì

Một frame là mảng ảnh BGR từ OpenCV. MediaPipe nhận ảnh RGB, nên mã chuyển bằng `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)` trước khi tạo `mp.Image`.

Face Landmarker xuất khoảng 478 điểm của mặt; mỗi điểm có x, y, z. Các chỉ số điểm mô tả những vị trí tương ứng trên mô hình mặt. Gói cũng có thể xuất blendshapes và ma trận biến đổi. Bước này tắt blendshapes và bật ma trận để kiểm tra đầu ra, chưa đổi ma trận thành pitch/yaw/roll.

Tọa độ x/y là tọa độ chuẩn hóa. Đổi về pixel bằng:

```python
x_pixel = landmark.x * frame_width
y_pixel = landmark.y * frame_height
```

Ví dụ x=0,5 với ảnh rộng 640 tương ứng x≈320 px. Kiểm tra tọa độ ngoài khung trước khi coi điểm là sử dụng được. z của landmarks không tự là khoảng cách theo mét; bước này không dùng z để đo khoảng cách thật.

Phát hiện mặt tìm vị trí khuôn mặt; landmarks tìm các điểm trên mặt; tracking tận dụng kết quả theo thời gian. Tracking ở đây không phải nhận dạng danh tính tài xế.

## Tại sao dùng VIDEO cho webcam?

`VIDEO` xử lý đồng bộ: đọc một frame, gọi model, nhận kết quả rồi xử lý frame tiếp. Nó vẫn có tracking, nên phù hợp cho bài học đầu vì dễ đối chiếu frame với kết quả.

`LIVE_STREAM` xử lý bất đồng bộ và có thể bỏ frame đầu vào khi model đang bận. Ta chưa dùng chế độ đó để tránh trộn thêm luồng/callback trước khi hiểu pipeline cơ bản.

Model nhận `timestamp_ms` tăng nghiêm ngặt. Chương trình lấy thời gian đơn điệu sau khi đọc frame và đổi sang mili giây; `max(last_ms + 1, ...)` tránh trùng ms. Đây không phải timestamp phơi sáng của cảm biến. VIDEO không có nghĩa phải đọc từ tệp video.

`num_faces=1` giới hạn đầu ra và cho phép smoothing theo cơ chế MediaPipe. Trong thử nghiệm này chỉ có một người. Nó không bảo đảm chọn đúng tài xế nếu có nhiều mặt trong ảnh; chọn ROI tài xế là việc cần làm ở giai đoạn triển khai.

## Các trạng thái trên màn hình

| Trạng thái | Ý nghĩa chính xác |
|---|---|
| `NO_FACE` | Model không trả khuôn mặt ở frame hiện tại |
| `LIMITED_GEOMETRY` | Có mặt nhưng số điểm/tọa độ/kích thước của một vùng không đạt kiểm tra sơ bộ |
| `GEOMETRY_OK` | Các điểm kiểm tra có tọa độ hữu hạn, nằm trong khung; bề rộng mắt >=14 px, miệng >=20 px |

Ngưỡng pixel là tham số prototype ở độ phân giải khởi đầu. GEOMETRY_OK không là xác nhận landmarks chính xác, mắt mở, tài xế tỉnh táo, hoặc mọi vùng mặt nhìn rõ. Kính râm, phản sáng, bóng tối hoặc che khuất có thể làm landmarks sai dù hình học vẫn đạt. Bước sau sẽ bổ sung đánh giá chất lượng theo tác vụ.

Ta không kiểm tra chiều cao mắt tối thiểu ở bước này vì mắt đang nhắm vẫn là quan sát cần giữ. Nếu coi mắt nhắm là vùng không hợp lệ, hệ thống sau này sẽ mất chính tín hiệu cần phát hiện.

## Đọc báo cáo

Chương trình tạo một cặp tệp mới trong `reports/`, không ghi đè các lần trước:

- `face_....json`: tóm tắt môi trường, FPS, thời gian suy luận, số frame từng trạng thái.
- `face_....csv`: từng frame với thời gian, trạng thái, kích thước vùng, cờ hình học và lý do LIMITED.

`inference_mean_ms` là thời gian trung bình của lời gọi model; `inference_p95_ms` là mức mà 95% phép đo không vượt quá. Chúng không bao gồm toàn bộ đọc camera/chuyển màu/hiển thị. `loop_fps` là FPS vòng lặp toàn hệ thống, nên có thể giảm so với 29,75 ở bước 1.

`geometry_ok_fraction` là tỷ lệ frame đạt kiểm tra hình học, không phải accuracy của model. Lần B cố ý ra khỏi khung nên tỷ lệ này giảm là bình thường. Muốn so hiệu năng/độ ổn định, dùng lần A cùng bối cảnh bước 1.

CSV chỉ lưu số liệu kiểm tra và không lưu ảnh/video. Những báo cáo này chưa là dataset training buồn ngủ và chưa có nhãn buồn ngủ.

## Thứ tự đọc mã

1. `check_face.py/main()`: import → kiểm tra model → chọn options.
2. `check_face.py/run()`: đọc frame → chuyển RGB → suy luận → kiểm tra → ghi log/hiển thị.
3. `face_geometry.py/inspect_face()`: đổi tọa độ, kiểm tra vùng, tạo trạng thái.
4. `face_geometry.py/draw_geometry()`: chỉ vẽ, không quyết định trạng thái buồn ngủ.
5. `download_face_model.py`: URL bản cố định, checksum và tải/khôi phục model.

Đọc từng đoạn, đối chiếu với cửa sổ và CSV. Không cần học toàn bộ API của MediaPipe ngay.

## Nếu có lỗi

Nếu thiếu model, chạy `download_face_model.py`. Nếu checksum khác, đổi tên model hiện có trước khi khôi phục; script không tự ghi đè bản khác.

Nếu camera/GUI lỗi, thử tách phần hiển thị:

```bash
.venv/bin/python check_face.py --camera 0 --seconds 30 --headless
```

Nếu FPS thấp hoặc nhiều LIMITED khi nhìn thẳng, gửi báo cáo và output trước khi đổi ngưỡng. Ghi thêm kính, ánh sáng, khoảng cách và vị trí camera. Nếu không có OK ở `--check`, xử lý lỗi đó trước webcam.

## Điều kiện hoàn thành

- Kiểm tra model thành công.
- Lần nhìn thẳng có landmarks bám hợp lý quanh mắt/miệng và có báo cáo FPS.
- Hiểu ba trạng thái hình học không phải ba mức buồn ngủ.
- Ra khỏi khung có NO_FACE, trở lại có landmarks; quan sát được các trường hợp bám sai nếu có.

Gửi JSON của lần nhìn thẳng và lần hành vi; thêm CSV nếu thấy trạng thái bất thường. Ghi rõ hình có mượt và điểm có bám đúng không. Bước 3 sẽ đo EAR và xây sự kiện chớp/nhắm mắt theo timestamp.

## Nguồn chính thức

- MediaPipe Python: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
- Model và đầu ra: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker
- MediaPipe 0.10.32: https://pypi.org/project/mediapipe/0.10.32/
- Topology các vùng mặt: https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/python/vision/face_landmarker.py
- Qt platform: https://doc.qt.io/qt-6/qpa.html
- Sounddevice/PortAudio: https://python-sounddevice.readthedocs.io/en/0.5.3/installation.html
- Model bản 1: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

Checksum SHA-256 của model trong gói: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`. Checksum cố định để đối chiếu đúng tệp đã kiểm tra, không là chữ ký chứng thực riêng của Google.
